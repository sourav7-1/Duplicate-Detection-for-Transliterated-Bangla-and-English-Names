"""Build labelled record pairs from data/names.csv -> data/gold_pairs.csv.

Columns: record_id_a, record_id_b, is_duplicate, source. record_id_a < record_id_b.

Duplicates (source "duplicate"): every pair of records with the same person_id.
Non-duplicates, until there are as many as duplicates:
  1. "hard_negative": each hard_negative record x every record of the base person it
     was made from (one word swapped via generate_dataset.CONFUSABLE);
  2. similar-name pairs of different people, drawn round-robin from three pools so each
     method contributes about the same number (a pool that runs out stops early):
       "trigram"     fn_trigram_score >= 0.5
       "dmetaphone"  same multiset of Double Metaphone codes (fn_phonetic_score = 1)
       "levenshtein" fn_lev_score >= 0.7
     A pair that is in several pools is labelled with the pool that drew it;
  3. "random": random pairs of different people to fill the rest.

The pools are computed in PostgreSQL with the project's own functions (sql/02, sql/03)
on a temp copy of names.csv, so name_record does not need to be loaded first.

Usage: python src/make_pairs.py [--seed 42]
"""
import argparse
import csv
import random
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from generate_dataset import CONFUSABLE
from load_data import connect, copy_csv

DATA = Path(__file__).resolve().parents[1] / "data"
SOURCES = ("trigram", "dmetaphone", "levenshtein")   # round-robin order
TRIGRAM_MIN, LEV_MIN = 0.5, 0.7

CANDIDATE_SQL = {
    "trigram": """
        SELECT a.record_id, b.record_id FROM cand a JOIN cand b
          ON a.x % b.x AND a.record_id < b.record_id AND a.person_id <> b.person_id""",
    "dmetaphone": """
        SELECT a.record_id, b.record_id FROM cand a JOIN cand b
          ON a.dm = b.dm AND a.record_id < b.record_id AND a.person_id <> b.person_id""",
    # fn_lev_score >= 0.7  <=>  distance <= 0.3 * longer length, in integers so a score of
    # exactly 0.7 counts (as it does in evaluate.py); the length check prunes cheaply.
    "levenshtein": """
        SELECT a.record_id, b.record_id FROM cand a JOIN cand b
          ON a.record_id < b.record_id AND a.person_id <> b.person_id
         AND 10 * abs(length(a.x) - length(b.x)) <= 3 * greatest(length(a.x), length(b.x))
         AND 10 * levenshtein_less_equal(a.x, b.x, 3 * greatest(length(a.x), length(b.x)) / 10)
             <= 3 * greatest(length(a.x), length(b.x))""",
}


def find_candidates(names_csv):
    """{source: set of (a, b)} for different-person pairs, computed in PostgreSQL."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""CREATE TEMP TABLE cand_raw (record_id INTEGER, person_id INTEGER,
                       full_name TEXT, variant_type TEXT) ON COMMIT DROP""")
        copy_csv(cur, "COPY cand_raw FROM STDIN (FORMAT csv, HEADER true)", names_csv)
        cur.execute("""
            CREATE TEMP TABLE cand ON COMMIT DROP AS
            SELECT record_id, person_id, fn_clean(full_name) AS x,
                   (SELECT array_agg(dmetaphone(w) ORDER BY dmetaphone(w))
                    FROM fn_words(full_name) AS w) AS dm
            FROM cand_raw""")
        cur.execute("CREATE INDEX ON cand USING gin (x gin_trgm_ops)")
        cur.execute("ANALYZE cand")
        cur.execute("SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
                    (str(TRIGRAM_MIN),))
        out = {}
        for source, sql in CANDIDATE_SQL.items():
            cur.execute(sql)
            out[source] = set(cur.fetchall())
    return out


def base_person(neg_name, originals):
    """person_id of the original name that neg_name differs from by one CONFUSABLE word."""
    t = neg_name.split()
    for pid, name in originals:
        u = name.split()
        diff = [(x, y) for x, y in zip(u, t) if x != y] if len(u) == len(t) else []
        if len(diff) == 1 and diff[0][1] in CONFUSABLE.get(diff[0][0], []):
            return pid
    return None


def build_pairs(rows, candidates, seed=42):
    """rows: dicts with record_id, person_id, full_name, variant_type.
    candidates: {source: set of (a, b)} as from find_candidates (missing sources = empty).

    Returns (pairs, stats): pairs = sorted [(a, b, is_dup, source), ...];
    stats = pair count per source, plus "unmatched_hard_negatives".
    """
    rows = [{**r, "record_id": int(r["record_id"]), "person_id": int(r["person_id"])}
            for r in rows]
    by_person = defaultdict(list)
    for r in rows:
        by_person[r["person_id"]].append(r["record_id"])
    person_of = {r["record_id"]: r["person_id"] for r in rows}

    dups = [(a, b) for ids in by_person.values() for a, b in combinations(sorted(ids), 2)]
    need = len(dups)
    negs = {}                                    # (a, b) -> source

    # 1. hard negative x every record of its base person
    originals = [(r["person_id"], r["full_name"]) for r in rows
                 if r["variant_type"] == "original"]
    unmatched = 0
    for r in rows:
        if r["variant_type"] != "hard_negative":
            continue
        base = base_person(r["full_name"], originals)
        if base is None:
            unmatched += 1
            continue
        for o in by_person[base]:
            negs[tuple(sorted((r["record_id"], o)))] = "hard_negative"
    if len(negs) > need:
        raise ValueError(f"{len(negs)} hard-negative pairs exceed {need} duplicates")

    # 2. round-robin over the similarity pools
    rng = random.Random(seed)
    pools = {}
    for s in SOURCES:
        pool = sorted(candidates.get(s, ()))
        rng.shuffle(pool)
        pools[s] = pool
    while len(negs) < need and any(pools.values()):
        for s in SOURCES:
            while pools[s] and pools[s][-1] in negs:   # already drawn by another pool
                pools[s].pop()
            if pools[s] and len(negs) < need:
                negs[pools[s].pop()] = s

    # 3. random fill
    ids = sorted(person_of)
    max_negs = len(ids) * (len(ids) - 1) // 2 - len(dups)
    if need > max_negs:
        raise ValueError(f"only {max_negs} non-duplicate pairs exist, need {need}")
    while len(negs) < need:
        a, b = sorted(rng.sample(ids, 2))
        if person_of[a] != person_of[b] and (a, b) not in negs:
            negs[(a, b)] = "random"

    pairs = sorted([(a, b, 1, "duplicate") for a, b in dups]
                   + [(a, b, 0, s) for (a, b), s in negs.items()])
    stats = {"duplicate": need, **Counter(negs.values()),
             "unmatched_hard_negatives": unmatched}
    return pairs, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--names", type=Path, default=DATA / "names.csv")
    ap.add_argument("--out", type=Path, default=DATA / "gold_pairs.csv")
    args = ap.parse_args()

    with open(args.names, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    candidates = find_candidates(args.names)
    pairs, s = build_pairs(rows, candidates, args.seed)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["record_id_a", "record_id_b", "is_duplicate", "source"])
        w.writerows(pairs)

    print(f"total records:        {len(rows)}")
    print(f"persons:              {len({r['person_id'] for r in rows})}")
    print(f"duplicate pairs:      {s['duplicate']}")
    print(f"non-duplicate pairs:  {len(pairs) - s['duplicate']}")
    print(f"  {'source':<14} {'pairs':>6}   candidate pool (different people)")
    print(f"  {'hard_negative':<14} {s.get('hard_negative', 0):>6}")
    rules = {"trigram": f"trigram >= {TRIGRAM_MIN}", "dmetaphone": "same Double Metaphone codes",
             "levenshtein": f"Levenshtein score >= {LEV_MIN}"}
    for src in SOURCES:
        print(f"  {src:<14} {s.get(src, 0):>6}   {len(candidates[src]):>5}  {rules[src]}")
    print(f"  {'random':<14} {s.get('random', 0):>6}")
    if s["unmatched_hard_negatives"]:
        print(f"  warning: {s['unmatched_hard_negatives']} hard negatives had no base person")
    print(f"wrote {len(pairs)} pairs -> {args.out}")


if __name__ == "__main__":
    main()
