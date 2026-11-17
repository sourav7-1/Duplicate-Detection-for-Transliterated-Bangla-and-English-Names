"""RQ3 benchmark: query time per method at 1k / 10k / 100k records, without and with
a GIN trigram index.

Workload: one candidate search, "find the 20 best matches for a name" (the first
"original" name in each dataset, recorded as query_name). Every method
uses the same shape so the index is the only thing that changes between runs:

    SELECT ... FROM bench_name
    WHERE full_name % <query>            -- trigram blocking (the GIN index can serve this)
      AND <method score> >= <threshold>  -- method-specific score on the candidates
    ORDER BY score DESC LIMIT 20

"without index" = the index does not exist (Seq Scan over every row).
"with index"    = index exists and the planner chooses freely; plan_scan records what
                  it picked (on small tables it may still prefer a Seq Scan).

Data: synthetic names from generate_dataset.py (seed 42), loaded into a scratch table
bench_name that is dropped at the end. The evaluation tables are not touched.
Timing: client wall clock around execute + fetch, 1 warm-up run then RUNS timed runs.
JIT is switched off so it doesn't add compile time noise at 100k rows.

Usage: python src/benchmark.py
"""
import csv
import statistics
import time

from psycopg import sql

from generate_dataset import generate
from load_data import ROOT, connect

SIZES = [1_000, 10_000, 100_000]
RUNS = 5
THRESHOLD = 0.5            # best threshold for every fuzzy method in results/metrics.csv
INDEX = "idx_bench_name_trgm"

# method -> (score expression over column full_name and literal q, threshold)
METHODS = {
    "exact":       ("(fn_clean(full_name) = fn_clean({q}))::int", 1),
    "trigram":     ("similarity(full_name, {q})",                 THRESHOLD),
    "levenshtein": ("fn_lev_score(full_name, {q})",               THRESHOLD),
    "dmetaphone":  ("fn_phonetic_score(full_name, {q})",          THRESHOLD),
    "soundex":     ("fn_soundex_score(full_name, {q})",           THRESHOLD),
}

EXPLAIN_DIR = ROOT / "docs" / "explain"
OUT = ROOT / "results" / "benchmark.csv"


def build_query(method, query_name):
    expr, threshold = METHODS[method]
    q = sql.Literal(query_name)
    score = sql.SQL(expr).format(q=q)
    return sql.SQL("""SELECT record_id, full_name, {score} AS score
FROM bench_name
WHERE full_name % {q} AND {score} >= {t}
ORDER BY score DESC, record_id
LIMIT 20""").format(score=score, q=q, t=sql.Literal(threshold))


def load_bench_table(cur, n):
    persons = n // 5 + 10                       # ~5.6 records per person, so enough rows
    rows = generate(size=persons, seed=42)[:n]
    assert len(rows) == n, f"generated only {len(rows)} records for {n}"
    cur.execute("DROP TABLE IF EXISTS bench_name")
    cur.execute("CREATE TABLE bench_name (record_id INTEGER PRIMARY KEY, "
                "full_name VARCHAR(150) NOT NULL)")
    with cur.copy("COPY bench_name (record_id, full_name) FROM STDIN") as copy:
        for i, r in enumerate(rows, 1):
            copy.write_row((i, r["full_name"]))
    cur.execute("VACUUM ANALYZE bench_name")
    # search for a name that exists, so every method (including exact) has matches
    return next(r["full_name"] for r in rows if r["variant_type"] == "original")


def time_query(cur, query):
    cur.execute(query)                          # warm-up (caches, catalog lookups)
    rows_returned = len(cur.fetchall())
    times = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        cur.execute(query)
        cur.fetchall()
        times.append((time.perf_counter() - t0) * 1000)
    return times, rows_returned


def explain(cur, query, path):
    cur.execute(sql.SQL("EXPLAIN (ANALYZE, BUFFERS) ") + query)
    plan = "\n".join(r[0] for r in cur.fetchall())
    path.write_text(f"-- {path.stem}\n{query.as_string(cur)}\n\n{plan}\n", encoding="utf-8")
    scan = next((line.strip().split(" on ")[0].lstrip("-> ").strip()
                 for line in plan.splitlines() if " on bench_name" in line
                 or f" on {INDEX}" in line), "?")
    return scan


def main():
    EXPLAIN_DIR.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(exist_ok=True)
    results = []

    with connect() as conn:
        conn.autocommit = True                  # DDL + VACUUM need it; queries are read-only
        cur = conn.cursor()
        cur.execute("SET pg_trgm.similarity_threshold = 0.3")
        cur.execute("SET jit = off")

        for n in SIZES:
            t0 = time.perf_counter()
            query_name = load_bench_table(cur, n)
            print(f"\n== {n:,} records (loaded in {time.perf_counter() - t0:.1f} s), "
                  f"query: {query_name!r}")
            cur.execute("SELECT pg_relation_size('bench_name')")
            table_bytes = cur.fetchone()[0]

            for gin in (False, True):
                index_bytes = build_ms = 0
                if gin:
                    t0 = time.perf_counter()
                    cur.execute(f"CREATE INDEX {INDEX} ON bench_name "
                                "USING gin (full_name gin_trgm_ops)")
                    build_ms = (time.perf_counter() - t0) * 1000
                    cur.execute("ANALYZE bench_name")
                    cur.execute("SELECT pg_relation_size(%s)", (INDEX,))
                    index_bytes = cur.fetchone()[0]

                for method in METHODS:
                    query = build_query(method, query_name)
                    times, n_rows = time_query(cur, query)
                    tag = f"{method}_{n}_{'gin' if gin else 'noindex'}"
                    scan = explain(cur, query, EXPLAIN_DIR / f"{tag}.txt")
                    row = {
                        "method": method, "n_records": n, "query_name": query_name,
                        "gin_index": gin, "runs": RUNS,
                        "mean_ms": round(statistics.mean(times), 3),
                        "std_ms": round(statistics.stdev(times), 3),
                        "min_ms": round(min(times), 3),
                        "rows_returned": n_rows, "plan_scan": scan,
                        "index_size_bytes": index_bytes, "table_size_bytes": table_bytes,
                        "index_build_ms": round(build_ms, 1),
                    }
                    results.append(row)
                    print(f"  {method:<11} gin={gin!s:<5} {row['mean_ms']:>9.2f} +/- "
                          f"{row['std_ms']:>7.2f} ms  rows={n_rows:<3} {scan}")

        cur.execute("DROP TABLE IF EXISTS bench_name")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)

    print(f"\nwrote {len(results)} rows -> {OUT}")
    print(f"EXPLAIN plans -> {EXPLAIN_DIR}")
    print(f"\n{'method':<12}{'records':>9}{'no index ms':>13}{'GIN ms':>10}{'speedup':>9}"
          f"{'index MB':>10}")
    by_key = {(r["method"], r["n_records"], r["gin_index"]): r for r in results}
    for n in SIZES:
        for m in METHODS:
            off, on = by_key[(m, n, False)], by_key[(m, n, True)]
            print(f"{m:<12}{n:>9,}{off['mean_ms']:>13.2f}{on['mean_ms']:>10.2f}"
                  f"{off['mean_ms'] / on['mean_ms']:>8.1f}x{on['index_size_bytes'] / 2**20:>10.2f}")


if __name__ == "__main__":
    main()
