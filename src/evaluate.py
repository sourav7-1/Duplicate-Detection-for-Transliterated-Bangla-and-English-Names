"""Score every gold pair with every method (raw and normalized), sweep thresholds,
and report precision / recall / F1.

Outputs:
  results/metrics.csv  one row per (method, normalized, threshold), is_best marks the
                       best-F1 threshold of each (method, normalized)
  experiment_run       one row per (method, normalized, threshold) with its metrics
  match_result         per-pair scores, stored only for the best-threshold run of each
                       (method, normalized); other thresholds only change the 0/1 cutoff

Runs are appended (experiment log); filter by started_at to get the latest.
Needs: load_data.py, sql/02-04 applied (normalized_name filled).

Usage: python src/evaluate.py
"""
import csv
import time
from pathlib import Path

from load_data import ROOT, connect

THRESHOLDS = [round(0.50 + 0.05 * i, 2) for i in range(10)]   # 0.50 .. 0.95
EPS = 1e-9   # scores are rounded to 4 decimals; guards float edge cases like 0.7

# method_name -> (SQL score expression with {a}/{b} placeholders, sql_function label)
METHODS = {
    "exact":       ("(fn_clean({a}) = fn_clean({b}))::int", "fn_clean(a) = fn_clean(b)"),
    "trigram":     ("fn_trigram_score({a}, {b})",           "fn_trigram_score"),
    "levenshtein": ("fn_lev_score({a}, {b})",               "fn_lev_score"),
    "dmetaphone":  ("fn_phonetic_score({a}, {b})",          "fn_phonetic_score"),
    "soundex":     ("fn_soundex_score({a}, {b})",           "fn_soundex_score"),
}


def compute_metrics(scored, threshold):
    """scored: [(score, is_duplicate)]. Predict duplicate when score >= threshold."""
    tp = fp = fn = tn = 0
    for score, is_dup in scored:
        pred = score >= threshold - EPS
        if pred and is_dup:
            tp += 1
        elif pred:
            fp += 1
        elif is_dup:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}


def best_row(rows):
    """Highest F1; ties go to the higher (stricter) threshold."""
    return max(rows, key=lambda r: (r["f1"], r["threshold"]))


def main():
    with open(ROOT / "data" / "gold_pairs.csv", newline="", encoding="utf-8") as f:
        n_csv = sum(1 for _ in csv.DictReader(f))

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM gold_pair")
        if cur.fetchone()[0] != n_csv:
            raise SystemExit("gold_pair table differs from gold_pairs.csv: run src/load_data.py")
        cur.execute("SELECT count(*), count(*) FILTER (WHERE normalized_name IS NULL) "
                    "FROM name_record")
        dataset_size, missing = cur.fetchone()
        if missing:
            raise SystemExit(f"{missing} records lack normalized_name: run sql/04_normalize.sql")

        metrics_rows = []
        for method, (expr, sql_function) in METHODS.items():
            cur.execute("""
                INSERT INTO match_method (method_name, sql_function) VALUES (%s, %s)
                ON CONFLICT (method_name) DO UPDATE SET sql_function = EXCLUDED.sql_function
                RETURNING method_id
            """, (method, sql_function))
            method_id = cur.fetchone()[0]

            for normalized in (False, True):
                col = "normalized_name" if normalized else "full_name"
                score_sql = expr.format(a=f"a.{col}", b=f"b.{col}")
                t0 = time.perf_counter()
                cur.execute(f"""
                    SELECT g.record_id_a, g.record_id_b, g.is_duplicate,
                           round(({score_sql})::numeric, 4)::float8
                    FROM gold_pair g
                    JOIN name_record a ON a.record_id = g.record_id_a
                    JOIN name_record b ON b.record_id = g.record_id_b
                """)
                pairs = cur.fetchall()
                duration_ms = (time.perf_counter() - t0) * 1000
                scored = [(score, is_dup) for _, _, is_dup, score in pairs]

                sweep = []
                for t in THRESHOLDS:
                    m = compute_metrics(scored, t)
                    cur.execute("""
                        INSERT INTO experiment_run
                            (method_id, threshold, use_normalization, use_gin_index,
                             dataset_size, duration_ms, precision_score, recall_score, f1_score)
                        VALUES (%s, %s, %s, false, %s, %s, %s, %s, %s)
                        RETURNING run_id
                    """, (method_id, t, normalized, dataset_size, round(duration_ms, 3),
                          round(m["precision"], 4), round(m["recall"], 4), round(m["f1"], 4)))
                    sweep.append({"method": method, "normalized": normalized, "threshold": t,
                                  **m, "run_id": cur.fetchone()[0], "is_best": False})

                best = best_row(sweep)
                best["is_best"] = True
                with cur.copy("COPY match_result (run_id, record_id_a, record_id_b, score, "
                              "predicted_duplicate) FROM STDIN") as copy:
                    for a, b, _, score in pairs:
                        copy.write_row((best["run_id"], a, b, score,
                                        score >= best["threshold"] - EPS))
                metrics_rows += sweep
                print(f"  scored {method:<11} normalized={normalized!s:<5} "
                      f"{len(pairs)} pairs in {duration_ms:7.0f} ms")

    out = ROOT / "results" / "metrics.csv"
    out.parent.mkdir(exist_ok=True)
    fields = ["method", "normalized", "threshold", "tp", "fp", "fn", "tn",
              "precision", "recall", "f1", "is_best", "run_id"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in metrics_rows:
            w.writerow({**r, **{k: f"{r[k]:.4f}" for k in ("precision", "recall", "f1")}})

    print(f"\nwrote {len(metrics_rows)} rows -> {out}\n")
    print(f"{'method':<12}{'normalized':<12}{'best_t':>7}{'precision':>11}{'recall':>8}{'f1':>8}")
    for r in sorted((r for r in metrics_rows if r["is_best"]), key=lambda r: -r["f1"]):
        print(f"{r['method']:<12}{str(r['normalized']):<12}{r['threshold']:>7.2f}"
              f"{r['precision']:>11.4f}{r['recall']:>8.4f}{r['f1']:>8.4f}")


if __name__ == "__main__":
    main()
