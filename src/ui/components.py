"""Reusable UI pieces. Tables are Markdown and charts matplotlib: st.dataframe and
st.bar_chart need pandas/pyarrow, which this machine's App Control policy blocks."""
import html

import streamlit as st

from plots import FIG
from ui.queries import HYBRID_TUNED, HYBRID_WEIGHTS

APP_NAME = "NameDedup"
# Must match the word list in fn_strip_common_tokens (sql/04_normalize.sql), same order;
# tests/test_ui.py checks it. "muhamad"/"hosain" are the forms after normalization.
COMMON_TOKENS = ["muhammad", "muhamad", "md", "rahman", "hossain", "hosain", "islam",
                 "ahmed", "akter", "khatun"]
FOOTER = "CSE311 DBMS · Team 25"

DESCRIPTIONS = {
    "Custom normalization": "Bangla rules (Md→muhammad, sh→s, …) then trigram similarity "
                            "(GIN index on normalized_name).",
    "Trigram": "pg_trgm similarity on the raw name (GIN index).",
    "Levenshtein": "1 − edit distance / longer length, on the raw name (full scan).",
    "Double Metaphone": "Share of words whose Double Metaphone codes match (full scan).",
    "Soundex": "Share of words whose Soundex codes match (full scan).",
    "Hybrid": (f"{HYBRID_WEIGHTS['dmetaphone']} × Double Metaphone + "
               f"{HYBRID_WEIGHTS['trigram']} × trigram + "
               f"{HYBRID_WEIGHTS['levenshtein']} × Levenshtein, all on normalized names. "
               + ("Best-F1 weights from results/hybrid_weights.json." if HYBRID_TUNED else
                  "Untuned weights: run python src/evaluate.py to pick the best set.")),
}


def markdown_table(headers, aligns, rows):
    """aligns: one Markdown alignment per column, e.g. '---' (left) or '---:' (right)."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(aligns) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    st.markdown("\n".join(lines))


# --------------------------------------------------------------------- sidebar
def sidebar(method_names, dataset_sizes):
    """Render the settings sidebar and return every setting as one dict:

    {"method": str, "threshold": float, "dataset_size": int | None,
     "normalize": bool, "use_gin_index": bool, "ignore_common": bool}

    dataset_sizes: record counts that exist in the database (see queries.dataset_sizes).
    Widget keys are prefixed so they never clash with same-label widgets in the page.
    """
    with st.sidebar:
        st.title(APP_NAME)
        st.subheader("Settings")
        method = st.selectbox("Method", method_names, key="sb_method")
        st.caption(DESCRIPTIONS[method])
        threshold = st.slider("Threshold (minimum score)", 0.30, 0.95, 0.50, 0.05,
                              key="sb_threshold")
        dataset_size = st.selectbox("Dataset size (records)", dataset_sizes,
                                    format_func=lambda n: f"{n:,}", key="sb_dataset_size")
        if not dataset_sizes:
            st.caption("No data loaded. Run: python src/load_data.py")
        normalize = st.checkbox("Apply Bangla name normalization", value=True,
                                key="sb_normalize")
        use_gin_index = st.checkbox("Use GIN trigram index", value=True, key="sb_use_gin")
        ignore_common = st.checkbox(
            "Ignore common tokens", value=False, key="sb_ignore_common",
            help="Adds a second trigram score computed without " + ", ".join(COMMON_TOKENS)
                 + ". The verdict then uses the lower of the two scores.")
        st.divider()
        st.caption(FOOTER)
    return {"method": method, "threshold": threshold, "dataset_size": dataset_size,
            "normalize": normalize, "use_gin_index": use_gin_index,
            "ignore_common": ignore_common}


# ------------------------------------------------------------------ search tab
# person 338: 8 spelling variants in data/names.csv (prefix, vowel, sh_s, word order, ...)
DEFAULT_NAME = "Mohammad Nasir Uddin"


def search_bar():
    """Name input and Search button side by side.

    Returns the name submitted with the last Search click, or None before the first
    click. The name is kept in session_state, so changing a sidebar setting re-runs
    the same search with the new settings.
    """
    col_name, col_button = st.columns([6, 1], vertical_alignment="bottom")
    name = col_name.text_input("Name", value=DEFAULT_NAME, key="search_name")
    if col_button.button("Search", type="primary", width="stretch"):
        st.session_state["submitted_name"] = name
    return st.session_state.get("submitted_name")


def card(column, label, value, mono=False):
    """A bordered card: small label above a bold (or monospace) value."""
    with column.container(border=True):
        st.caption(label)
        st.markdown(f"`{value}`" if mono else f"**{value}**")


def result_cards(normalized, method, elapsed_ms):
    """Three cards in one row: normalized query, method, query time."""
    c1, c2, c3 = st.columns(3)
    card(c1, "Normalized as", normalized or "–", mono=True)
    card(c2, "Method", method)
    card(c3, "Query time", f"{elapsed_ms:.1f} ms")


# Inline styles shared by the HTML tables (results and evaluation).
CELL = "padding:8px 10px;border-bottom:1px solid #E5E7EB;vertical-align:middle;"
HEAD = "padding:8px 10px;border-bottom:2px solid #D1D5DB;font-weight:600;"

# Fixed cut-offs, independent of the sidebar threshold (which only filters rows).
LIKELY_MIN, REVIEW_MIN = 0.85, 0.65
# verdict -> (badge background, badge text): light tint + dark text keeps contrast high
BADGES = {
    "Likely duplicate": ("#DCFCE7", "#166534"),   # green
    "Needs review": ("#FEF3C7", "#92400E"),       # amber
    "Different person": ("#F3F4F6", "#374151"),   # grey
}


def verdict(score):
    """Compare at the 3 decimals shown in the table, so the badge matches the number."""
    s = round(score, 3)
    if s >= LIKELY_MIN:
        return "Likely duplicate"
    if s >= REVIEW_MIN:
        return "Needs review"
    return "Different person"


def badge(label):
    bg, fg = BADGES[label]
    return (f'<span style="background:{bg};color:{fg};padding:2px 10px;border-radius:999px;'
            f'font-size:0.85em;font-weight:600;white-space:nowrap">{label}</span>')


def duplicates_table_html(rows):
    """HTML table of results. Every database value is passed through html.escape.

    rows: see queries.search. When core_score is set (Ignore common tokens), it gets
    its own column and the verdict uses min(score, core_score): stripping alone would
    rate "Md. Rakib Hossain" 1.000 against "Mohammad Rakib Rahman" (different people). Built as one line: Markdown would treat
    indented HTML lines as a code block.
    """
    with_core = any(r[5] is not None for r in rows)
    columns = [("Record", "right"), ("Name in database", "left"), ("Normalized", "left"),
               ("Score", "right")]
    columns += [("Trigram score without common tokens", "right")] if with_core else []
    columns += [("Verdict", "left")]
    num = f"{CELL}text-align:right;font-variant-numeric:tabular-nums"
    header = "".join(f'<th style="{HEAD}text-align:{align}">{title}</th>'
                     for title, align in columns)
    body = []
    for record_id, _person_id, full_name, normalized, score, core in rows:
        norm = (f'<code>{html.escape(normalized)}</code>' if normalized is not None else "–")
        body.append(
            "<tr>"
            f'<td style="{CELL}text-align:right">{record_id}</td>'
            f'<td style="{CELL}white-space:pre-wrap">{html.escape(full_name)}</td>'
            f'<td style="{CELL}">{norm}</td>'
            f'<td style="{num}">{score:.3f}</td>'
            + (f'<td style="{num}">{core:.3f}</td>' if with_core else "")
            + f'<td style="{CELL}">{badge(verdict(min(score, core) if with_core else score))}</td>'
            "</tr>")
    return (f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table>')


def duplicates_table(rows):
    """'Possible duplicates' heading, then the HTML table or a no-match warning."""
    st.subheader("Possible duplicates")
    if not rows:
        st.info("No similar names found above this threshold.")
        return
    st.markdown(duplicates_table_html(rows), unsafe_allow_html=True)
    st.caption(f"Verdict: score ≥ {LIKELY_MIN} likely duplicate, {REVIEW_MIN}–{LIKELY_MIN} "
               "needs review, below that different person. The sidebar threshold only "
               "decides which rows are listed.")


def sql_expander(sql):
    with st.expander("Generated SQL"):
        st.code(sql, language="sql")


# -------------------------------------------------------------- evaluation tab
METHOD_LABELS = {"exact": "Exact", "trigram": "Trigram", "levenshtein": "Levenshtein",
                 "dmetaphone": "Double Metaphone", "soundex": "Soundex"}


def method_label(method):
    """'trigram' -> 'Trigram'; evaluate.py's 'hybrid_40_40_20' -> 'Hybrid 0.40/0.40/0.20'
    (weights for Double Metaphone / trigram / Levenshtein)."""
    if method.startswith("hybrid_"):
        return "Hybrid " + "/".join(f"{int(p) / 100:.2f}" for p in method.split("_")[1:])
    return METHOD_LABELS.get(method, method)
BEST_BG, BEST_FG = BADGES["Likely duplicate"]          # same green as the badge


def best_f1_table_html(metrics):
    """Method | raw (P, R, F1, threshold) | normalized (P, R, F1, threshold).

    metrics: rows of results/metrics.csv (dicts of strings). Uses the is_best rows;
    the highest F1 in the table (ties included) is highlighted.
    """
    best = {(r["method"], r["normalized"] == "True"): r for r in metrics if r["is_best"] == "True"}
    top_f1 = max(round(float(r["f1"]), 3) for r in best.values())
    methods = sorted({m for m, _ in best},
                     key=lambda m: -max(float(best[k]["f1"]) for k in best if k[0] == m))

    def cells(row):
        if row is None:
            return f'<td style="{CELL}text-align:center" colspan="4">–</td>'
        f1 = round(float(row["f1"]), 3)
        f1_style = (f"background:{BEST_BG};color:{BEST_FG};font-weight:700;"
                    if f1 == top_f1 else "")
        num = f"{CELL}text-align:right;font-variant-numeric:tabular-nums;"
        return (f'<td style="{num}">{float(row["precision"]):.3f}</td>'
                f'<td style="{num}">{float(row["recall"]):.3f}</td>'
                f'<td style="{num}{f1_style}">{f1:.3f}</td>'
                f'<td style="{num}">{float(row["threshold"]):.2f}</td>')

    sub = "".join(f'<th style="{HEAD}text-align:right">{h}</th>'
                  for h in ["Precision", "Recall", "F1", "Best threshold"])
    header = (f'<tr><th style="{HEAD}text-align:left" rowspan="2">Method</th>'
              f'<th style="{HEAD}text-align:center" colspan="4">Raw names</th>'
              f'<th style="{HEAD}text-align:center" colspan="4">Normalized names</th></tr>'
              f"<tr>{sub}{sub}</tr>")
    body = "".join(
        f'<tr><td style="{CELL}">{html.escape(method_label(m))}</td>'
        f"{cells(best.get((m, False)))}{cells(best.get((m, True)))}</tr>"
        for m in methods)
    return (f'<table style="width:100%;border-collapse:collapse">'
            f"<thead>{header}</thead><tbody>{body}</tbody></table>")


def best_f1_table(metrics):
    st.subheader("Best F1 per method")
    st.markdown(best_f1_table_html(metrics), unsafe_allow_html=True)
    ts = [float(r["threshold"]) for r in metrics]        # range of the sweep that was run
    st.caption(f"Best threshold = the threshold with the highest F1 in the "
               f"{min(ts):.2f}–{max(ts):.2f} sweep. "
               "Highlighted: best F1 overall.")


# file name -> caption. All four are written by: python src/plots.py
FIGURES = [
    ("f1_by_method.png", "F1 at each method's best threshold, raw vs normalized names."),
    ("pr_curves.png", "Precision-recall curve per method; the dot marks the best-F1 threshold."),
    ("query_time_scaling.png", "Query time vs table size with and without the GIN index "
                               "(log scale)."),
    ("failure_table.png", "Share of true duplicates each method misses, by spelling-variant "
                          "type."),
    ("fp_by_source.png", "False-positive rate per method, by how the non-duplicate pair "
                         "was chosen."),
]


def figure_grid():
    """The four report figures from docs/figures/ in a 2-column grid."""
    st.subheader("Figures")
    for i in range(0, len(FIGURES), 2):
        for column, (filename, caption) in zip(st.columns(2), FIGURES[i:i + 2]):
            path = FIG / filename
            if path.exists():
                column.image(str(path), caption=caption, width="stretch")
            else:
                column.warning(f"docs/figures/{filename} not found. "
                               "Create it with: python src/plots.py")


def sweep_table(metrics):
    """Every row of metrics.csv inside an expander."""
    with st.expander("Full threshold sweep (all rows of metrics.csv)"):
        markdown_table(
            ["method", "normalized", "threshold", "TP", "FP", "FN", "precision", "recall", "F1"],
            ["---", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"],
            [(r["method"], r["normalized"], r["threshold"], r["tp"], r["fp"], r["fn"],
              r["precision"], r["recall"], r["f1"]) for r in metrics],
        )


# ------------------------------------------------------------- performance tab
def size_label(n):
    """1000 -> '1k', 100000 -> '100k', 2691 -> '2,691'."""
    return f"{n // 1000}k" if n % 1000 == 0 else f"{n:,}"


def performance_table_html(bench):
    """Method | per size: no index, GIN (mean ms) | speedup at the largest size.

    bench: rows of results/benchmark.csv (dicts of strings).
    """
    sizes = sorted({int(r["n_records"]) for r in bench})
    methods = list(dict.fromkeys(r["method"] for r in bench))       # CSV order
    mean = {(r["method"], int(r["n_records"]), r["gin_index"] == "True"): float(r["mean_ms"])
            for r in bench}
    largest = sizes[-1]
    num = f"{CELL}text-align:right;font-variant-numeric:tabular-nums;"

    def ms(key):
        return f"{mean[key]:.1f}" if key in mean else "–"

    def speedup(m):
        off, on = mean.get((m, largest, False)), mean.get((m, largest, True))
        return f"{off / on:.1f}×" if off and on else "–"

    header = (f'<tr><th style="{HEAD}text-align:left" rowspan="2">Method</th>'
              + "".join(f'<th style="{HEAD}text-align:center" colspan="2">'
                        f"{size_label(n)} records</th>" for n in sizes)
              + f'<th style="{HEAD}text-align:right" rowspan="2">'
                f"Speedup at {size_label(largest)}</th></tr><tr>"
              + "".join(f'<th style="{HEAD}text-align:right">No index</th>'
                        f'<th style="{HEAD}text-align:right">GIN</th>' for _ in sizes)
              + "</tr>")
    body = "".join(
        f'<tr><td style="{CELL}">{html.escape(method_label(m))}</td>'
        + "".join(f'<td style="{num}">{ms((m, n, False))}</td>'
                  f'<td style="{num}">{ms((m, n, True))}</td>' for n in sizes)
        + f'<td style="{num}font-weight:700">{speedup(m)}</td></tr>'
        for m in methods)
    return (f'<table style="width:100%;border-collapse:collapse">'
            f"<thead>{header}</thead><tbody>{body}</tbody></table>")


def performance_table(bench):
    runs = bench[0]["runs"] if bench else "?"
    # "queries" exists from the 10-name benchmark on; older CSVs used a single name
    per_cell = (f"{bench[0]['queries']} search names × {runs} runs"
                if bench and "queries" in bench[0] else f"{runs} runs")
    largest = max(int(r["n_records"]) for r in bench)
    st.subheader("Query time per method (ms)")
    st.markdown(performance_table_html(bench), unsafe_allow_html=True)
    st.caption(f"Mean of {per_cell} per cell, in milliseconds, from results/benchmark.csv. "
               f"Speedup = no-index time ÷ GIN time at {size_label(largest)} records.")


# ---------------------------------------------------------------------- errors
def db_error(detail):
    """One clear message with the steps to fix a failed database connection."""
    st.error(
        "**Cannot connect to the PostgreSQL database.** Searching is unavailable; the "
        "Evaluation and Performance tabs still work from the saved results.\n\n"
        "To fix it:\n"
        "1. Check `.env` in the project folder has the right `DB_HOST`, `DB_PORT`, `DB_NAME`, "
        "`DB_USER` and `DB_PASSWORD` (copy `.env.example` if it is missing).\n"
        "2. Make sure PostgreSQL is running (Windows: `services.msc` → "
        "`postgresql-x64-18` → Start).\n"
        "3. Make sure the database exists and is set up (README steps 2–4).\n"
        "4. Reload this page.\n\n"
        f"Details: `{detail}`")
