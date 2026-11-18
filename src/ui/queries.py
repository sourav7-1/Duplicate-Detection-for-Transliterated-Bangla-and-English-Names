"""Data access for the app: every SQL call, plus reading results/metrics.csv."""
import json
import time
from textwrap import dedent

from psycopg import ClientCursor

from plots import RESULTS, read_csv
from ui.db import get_conn

def load_hybrid_weights(path=RESULTS / "hybrid_weights.json"):
    """Best Hybrid weights picked by evaluate.py, or None if it hasn't been run."""
    try:
        weights = json.loads(path.read_text(encoding="utf-8"))["weights"]
        return {k: float(weights[k]) for k in ("dmetaphone", "trigram", "levenshtein")}
    except (OSError, ValueError, KeyError, TypeError):
        return None


# Hybrid = weighted mix of three scores on normalized names. Uses the best-F1 weight set
# from results/hybrid_weights.json; until evaluate.py has written it, the old untuned mix.
HYBRID_DEFAULT = {"dmetaphone": 0.3, "trigram": 0.4, "levenshtein": 0.3}
HYBRID_TUNED = load_hybrid_weights()
HYBRID_WEIGHTS = HYBRID_TUNED or HYBRID_DEFAULT

# method -> (score SQL, optional index-backed prefilter). %(q)s = raw query,
# %(nq)s = normalized query. Trigram methods use the GIN index through the % operator.
METHODS = {
    "Custom normalization": ("similarity(normalized_name, %(nq)s)", "normalized_name %% %(nq)s"),
    "Trigram": ("similarity(full_name, %(q)s)", "full_name %% %(q)s"),
    "Levenshtein": ("fn_lev_score(full_name, %(q)s)", None),
    "Double Metaphone": ("fn_phonetic_score(full_name, %(q)s)", None),
    "Soundex": ("fn_soundex_score(full_name, %(q)s)", None),
    "Hybrid": (
        f"{HYBRID_WEIGHTS['dmetaphone']} * fn_phonetic_score(normalized_name, %(nq)s)"
        f" + {HYBRID_WEIGHTS['trigram']} * fn_trigram_score(normalized_name, %(nq)s)"
        f" + {HYBRID_WEIGHTS['levenshtein']} * fn_lev_score(normalized_name, %(nq)s)",
        None,
    ),
}
METHOD_NAMES = list(METHODS)
# Methods that score the raw name; with normalize=True they score normalized names instead.
RAW_METHODS = {"Trigram", "Levenshtein", "Double Metaphone", "Soundex"}


def method_sql(method, normalize=False):
    """(score SQL, prefilter) for a method, optionally switched to normalized names."""
    score_sql, prefilter = METHODS[method]
    if normalize and method in RAW_METHODS:
        swap = lambda s: s and s.replace("full_name", "normalized_name").replace("%(q)s", "%(nq)s")
        return swap(score_sql), swap(prefilter)
    return score_sql, prefilter


def search(name, method, threshold, ignore_common=False, normalize=False, limit=10):
    """Top 10 records scoring >= threshold.

    Returns (normalized query, rows, elapsed ms, sql) where
    rows = [(record_id, person_id, full_name, normalized_name, score, core_score), ...]
    core_score = trigram similarity of the normalized names after fn_strip_common_tokens
                 (muhammad, rahman, islam, ...) when ignore_common is on, else None.
                 Rows stay ranked by score; the UI bases the verdict on the lower of
                 the two (see components.duplicates_table_html).
    sql  = the exact statements sent to PostgreSQL. A ClientCursor binds the values
           into the SQL text itself, so what is shown is byte-for-byte what ran.
    normalize: score normalized names with the raw-name methods (see RAW_METHODS).
    """
    score_sql, prefilter = method_sql(method, normalize)
    where = f"WHERE {prefilter}" if prefilter else ""
    core_sql = ("similarity(fn_strip_common_tokens(normalized_name), "
                "fn_strip_common_tokens(%(nq)s))::float8" if ignore_common else "NULL::float8")
    query = dedent(f"""        SELECT record_id, person_id, full_name, normalized_name, score, core_score
        FROM (SELECT record_id, person_id, full_name, normalized_name,
                     ({score_sql})::float8 AS score,
                     {core_sql} AS core_score
              FROM name_record {where}) AS s
        WHERE score >= %(t)s
        ORDER BY score DESC, record_id
        LIMIT %(limit)s""")
    with ClientCursor(get_conn()) as cur:
        t0 = time.perf_counter()
        normalize_sql = cur.mogrify(
            "SELECT fn_normalize_bn_name(%s), "
            "set_config('pg_trgm.similarity_threshold', %s, false)",
            (name, str(threshold)))
        cur.execute(normalize_sql)
        nq = cur.fetchone()[0]
        search_sql = cur.mogrify(query, {"q": name, "nq": nq, "t": threshold, "limit": limit})
        cur.execute(search_sql)
        rows = cur.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
    return nq, rows, elapsed_ms, f"{normalize_sql};\n\n{search_sql};"


def normalize_steps(name):
    """Replay fn_normalize_bn_name rule by rule (sql/04_normalize.sql).

    Returns (steps, result): steps = one dict per step that changed the string
    ({"rule", "rule_group", "before", "after"}), starting with lower-casing and ending
    with whitespace clean-up; result equals fn_normalize_bn_name(name).
    """
    steps = []

    def step(rule, group, before, after):
        if before != after:
            steps.append({"rule": rule, "rule_group": group, "before": before, "after": after})
        return after

    with get_conn().cursor() as cur:
        cur.execute("SELECT rule_group, rule_type, pattern, replacement FROM name_variant_rule "
                    "WHERE is_active ORDER BY apply_order, rule_id")
        rules = cur.fetchall()
        s = step("lower-case", "setup", name, name.lower())
        for group, rtype, pattern, repl in rules:
            regex = rf"\m{pattern}\M" if rtype == "word" else pattern
            cur.execute("SELECT regexp_replace(%s, %s, %s, 'g')", (s, regex, repl))
            shown = {"": "(delete)", " ": "(space)"}.get(repl, repl)
            label = f"{pattern} -> {shown}" + (" (whole word)" if rtype == "word" else "")
            s = step(label, group, s, cur.fetchone()[0])
        cur.execute("SELECT btrim(regexp_replace(%s, '\\s+', ' ', 'g'))", (s,))
        s = step("collapse spaces", "cleanup", s, cur.fetchone()[0])
    return steps, s


def score_all(name, nq, record_ids):
    """{record_id: {method: score}} for every method in METHODS, in one query."""
    if not record_ids:
        return {}
    cols = ", ".join(f"({sql})::float8" for sql, _ in METHODS.values())
    with get_conn().cursor() as cur:
        cur.execute(f"SELECT record_id, {cols} FROM name_record "
                    "WHERE record_id = ANY(%(ids)s)",
                    {"q": name, "nq": nq, "ids": list(record_ids)})
        return {rid: dict(zip(METHOD_NAMES, scores)) for rid, *scores in cur.fetchall()}


def normalize_words(words):
    """{word: fn_normalize_bn_name(word)} for each distinct word, in one query."""
    words = sorted(set(words))
    if not words:
        return {}
    with get_conn().cursor() as cur:
        cur.execute("SELECT w, fn_normalize_bn_name(w) FROM unnest(%s::text[]) AS w", (words,))
        return dict(cur.fetchall())


def counts():
    """{"records": rows in name_record, "gold_pairs": rows in gold_pair}."""
    with get_conn().cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM name_record), (SELECT count(*) FROM gold_pair)")
        records, pairs = cur.fetchone()
    return {"records": records, "gold_pairs": pairs}


def load_metrics_by_source():
    """Rows of results/metrics_by_source.csv, or None if evaluate.py hasn't been run."""
    path = RESULTS / "metrics_by_source.csv"
    return read_csv(path) if path.exists() else None


def dataset_sizes():
    """Record counts of the datasets loaded in the database (empty list if none).

    Only name_record holds searchable data today; the benchmark sizes live in a
    scratch table that benchmark.py drops, so they are not listed.
    """
    with get_conn().cursor() as cur:
        cur.execute("SELECT count(*) FROM name_record")
        n = cur.fetchone()[0]
    return [n] if n else []


def load_metrics():
    """Rows of results/metrics.csv as dicts, or None if evaluate.py hasn't been run."""
    path = RESULTS / "metrics.csv"
    return read_csv(path) if path.exists() else None


def load_benchmark():
    """Rows of results/benchmark.csv as dicts, or None if benchmark.py hasn't been run."""
    path = RESULTS / "benchmark.csv"
    return read_csv(path) if path.exists() else None
