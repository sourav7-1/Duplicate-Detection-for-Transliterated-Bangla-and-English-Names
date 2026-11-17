"""Streamlit demo: search for possible duplicate names in PostgreSQL.

Run: streamlit run app.py
Tables are rendered as Markdown and charts with matplotlib because pandas/pyarrow
(which st.dataframe and st.bar_chart need) are blocked by this machine's App Control policy.
"""
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from load_data import connect  # noqa: E402
from plots import RESULTS, plot_f1_bars, read_csv  # noqa: E402

# Hybrid = weighted mix of three normalized scores (not yet evaluated in metrics.csv).
HYBRID_WEIGHTS = {"trigram": 0.4, "levenshtein": 0.3, "phonetic": 0.3}

# method -> (score SQL, optional index-backed prefilter). %(q)s = raw query,
# %(nq)s = normalized query. Trigram methods use the GIN index through the % operator.
METHODS = {
    "Trigram": ("similarity(full_name, %(q)s)", "full_name %% %(q)s"),
    "Levenshtein": ("fn_lev_score(full_name, %(q)s)", None),
    "Phonetic": ("fn_phonetic_score(full_name, %(q)s)", None),
    "Custom normalization": ("similarity(normalized_name, %(nq)s)", "normalized_name %% %(nq)s"),
    "Hybrid": (
        f"{HYBRID_WEIGHTS['trigram']} * fn_trigram_score(normalized_name, %(nq)s)"
        f" + {HYBRID_WEIGHTS['levenshtein']} * fn_lev_score(normalized_name, %(nq)s)"
        f" + {HYBRID_WEIGHTS['phonetic']} * fn_phonetic_score(normalized_name, %(nq)s)",
        None,
    ),
}
DESCRIPTIONS = {
    "Trigram": "pg_trgm similarity on the raw name (GIN index).",
    "Levenshtein": "1 − edit distance / longer length, on the raw name (full scan).",
    "Phonetic": "Share of words whose Double Metaphone codes match (full scan).",
    "Custom normalization": "Bangla rules (Md→muhammad, sh→s, …) then trigram similarity "
                            "(GIN index on normalized_name).",
    "Hybrid": "0.4 × trigram + 0.3 × Levenshtein + 0.3 × phonetic, all on normalized names. "
              "Not evaluated yet.",
}


@st.cache_resource
def get_conn():
    conn = connect()
    conn.autocommit = True
    return conn


def md_cell(value):
    """Show a name in a code span so leading/trailing spaces and punctuation stay visible."""
    return f"`{value}`" if value is not None else "–"


def search(name, method, threshold):
    score_sql, prefilter = METHODS[method]
    where = f"WHERE {prefilter}" if prefilter else ""
    query = f"""
        SELECT record_id, person_id, full_name, normalized_name, score
        FROM (SELECT record_id, person_id, full_name, normalized_name,
                     ({score_sql})::float8 AS score
              FROM name_record {where}) AS s
        WHERE score >= %(t)s
        ORDER BY score DESC, record_id
        LIMIT 10
    """
    with get_conn().cursor() as cur:
        t0 = time.perf_counter()
        cur.execute("SELECT fn_normalize_bn_name(%s), "
                    "set_config('pg_trgm.similarity_threshold', %s, false)",
                    (name, str(threshold)))
        nq = cur.fetchone()[0]
        cur.execute(query, {"q": name, "nq": nq, "t": threshold})
        rows = cur.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
    return nq, rows, elapsed_ms


def search_tab():
    name = st.text_input("Name (English or Banglish spelling)", placeholder="e.g. Md. Rakib Uddin Islam")
    col1, col2 = st.columns(2)
    method = col1.selectbox("Method", list(METHODS))
    threshold = col2.slider("Threshold (minimum score)", 0.0, 1.0, 0.5, 0.05)
    st.caption(DESCRIPTIONS[method])

    if not name.strip():
        st.info("Type a name to search for possible duplicates.")
        return

    try:
        nq, rows, elapsed_ms = search(name, method, threshold)
    except Exception as e:  # DB down, functions missing, ...
        st.error(f"Query failed: {e}")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Query time", f"{elapsed_ms:.1f} ms")
    c2.metric("Matches shown", len(rows))
    c3.metric("Normalized query", nq or "–")

    if not rows:
        st.warning("No records at or above this threshold. Try lowering it.")
        return
    lines = ["| # | record_id | person_id | full_name | normalized_name | score |",
             "|---:|---:|---:|---|---|---:|"]
    for i, (rid, pid, full, norm, score) in enumerate(rows, 1):
        lines.append(f"| {i} | {rid} | {pid} | {md_cell(full)} | {md_cell(norm)} | {score:.3f} |")
    st.markdown("\n".join(lines))
    st.caption("person_id is the ground truth: rows sharing the top hit's person_id are "
               "true duplicates; others are false matches.")


def evaluation_tab():
    path = RESULTS / "metrics.csv"
    if not path.exists():
        st.warning("results/metrics.csv not found. Run: python src/evaluate.py")
        return
    metrics = read_csv(path)
    best = sorted((r for r in metrics if r["is_best"] == "True"), key=lambda r: -float(r["f1"]))

    st.subheader("Best threshold per method")
    lines = ["| method | normalized | threshold | precision | recall | F1 |",
             "|---|---|---:|---:|---:|---:|"]
    for r in best:
        lines.append(f"| {r['method']} | {r['normalized']} | {float(r['threshold']):.2f} | "
                     f"{float(r['precision']):.3f} | {float(r['recall']):.3f} | "
                     f"**{float(r['f1']):.3f}** |")
    st.markdown("\n".join(lines))

    st.pyplot(plot_f1_bars(metrics))

    with st.expander("Full threshold sweep (all rows of metrics.csv)"):
        lines = ["| method | normalized | threshold | TP | FP | FN | precision | recall | F1 |",
                 "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for r in metrics:
            lines.append(f"| {r['method']} | {r['normalized']} | {r['threshold']} | {r['tp']} | "
                         f"{r['fp']} | {r['fn']} | {r['precision']} | {r['recall']} | {r['f1']} |")
        st.markdown("\n".join(lines))


st.set_page_config(page_title="Name Duplicate Finder", page_icon="🔎", layout="wide")
st.title("Duplicate detection for Bangla & English names")
tab_search, tab_eval = st.tabs(["Search", "Evaluation results"])
with tab_search:
    search_tab()
with tab_eval:
    evaluation_tab()
