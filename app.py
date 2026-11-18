"""Streamlit demo: search for possible duplicate names in PostgreSQL.

Run: python -m streamlit run app.py
Layout only. DB connection: src/ui/db.py, SQL: src/ui/queries.py,
UI pieces: src/ui/components.py.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from ui import components, queries  # noqa: E402
from ui.db import connection_error  # noqa: E402

st.set_page_config(page_title="NameDedup", page_icon="🔎", layout="wide")
st.title("Duplicate Name Finder")
st.caption("Type a name in English or Banglish spelling. The app searches the PostgreSQL "
           "database for records that may be the same person.")

db_problem = connection_error()             # None when the database answers
if db_problem:
    components.db_error(db_problem)          # the one and only connection message

tab_search, tab_eval, tab_perf = st.tabs(["Find duplicates", "Evaluation results",
                                          "Performance"])
settings = components.sidebar(queries.METHOD_NAMES,
                              [] if db_problem else queries.dataset_sizes())

with tab_search:
    name = components.search_bar()
    if name is not None and not db_problem:  # Search clicked and database reachable
        if not name.strip():
            st.info("Type a name to search for possible duplicates.")
        else:
            try:
                nq, rows, elapsed_ms, sql = queries.search(
                    name, settings["method"], settings["threshold"], settings["ignore_common"])
            except Exception as e:  # connection dropped mid-search, SQL function missing, ...
                st.error(f"Query failed: {e}")
            else:
                components.result_cards(nq, settings["method"], elapsed_ms)
                components.duplicates_table(rows)
                components.sql_expander(sql)

with tab_eval:
    metrics = queries.load_metrics()
    if metrics is None:
        st.warning("results/metrics.csv not found. Run: python src/evaluate.py")
    else:
        components.best_f1_table(metrics)
        components.figure_grid()
        components.sweep_table(metrics)

with tab_perf:
    bench = queries.load_benchmark()
    if not bench:
        st.warning("results/benchmark.csv not found. Run: python src/benchmark.py")
    else:
        components.performance_table(bench)
