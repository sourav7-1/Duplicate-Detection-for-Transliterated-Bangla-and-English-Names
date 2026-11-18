"""Score every gold pair with every method (raw and normalized), sweep thresholds,
and report precision / recall / F1.

Outputs:
  results/metrics.csv  one row per (method, normalized, threshold), is_best marks the
                       best-F1 threshold of each (method, normalized)
  experiment_run       one row per (method, normalized, threshold) with its metrics
  match_result         per-pair scores, stored only for the best-threshold run of each
                       (method, normalized); other thresholds only change the 0/1 cutoff
  results/metrics_by_source.csv
                       at each best threshold: per gold_pair.source, how many pairs were
                       predicted duplicate (recall for "duplicate", false-positive rate
                       for every non-duplicate source)
  results/hybrid_weights.json
                       the Hybrid weight set with the best F1; the app's Hybrid uses it

Hybrid = w_dm * Double Metaphone + w_tri * trigram + w_lev * Levenshtein, normalized names
only; every set in HYBRID_WEIGHT_SETS is evaluated as its own method (hybrid_40_40_20, ...).

Runs are appended (experiment log); filter by started_at to get the latest.
Needs: load_data.py, sql/02-04 applied (normalized_name filled).

Usage: python src/evaluate.py
"""
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

from load_data import ROOT, connect

THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(14)]   # 0.30 .. 0.95
EPS = 1e-9   # scores are rounded to 4 decimals; guards float edge cases like 0.7

# method_name -> (SQL score expression with {a}/{b} placeholders, sql_function label)
METHODS = {
    "exact":       ("(fn_clean({a}) = fn_clean({b}))::int", "fn_clean(a) = fn_clean(b)"),
    "trigram":     ("fn_trigram_score({a}, {b})",           "fn_trigram_score"),
    "levenshtein": ("fn_lev_score({a}, {b})",               "fn_lev_score"),
    "dmetaphone":  ("fn_phonetic_score({a}, {b})",          "fn_phonetic_score"),
    "soundex":     ("fn_soundex_score({a}, {b})",           "fn_soundex_score"),
}

# (Double Metaphone, trigram, Levenshtein) weights to try
HYBRID_WEIGHT_SETS = [(0.4, 0.4, 0.2), (0.5, 0.3, 0.2), (0.34, 0.33, 0.33)]
HYBRID_KEYS = ("dmetaphone", "trigram", "levenshtein")   # key order in hybrid_weights.json


def hybrid_name(weights):
    """(0.4, 0.4, 0.2) -> 'hybrid_40_40_20'."""
    return "hybrid_" + "_".join(f"{round(w * 100):02d}" for w in weights)


HYBRID_BY_NAME = {hybrid_name(w): w for w in HYBRID_WEIGHT_SETS}
for _name, (_dm, _tri, _lev) in HYBRID_BY_NAME.items():
    METHODS[_name] = (
        f"{_dm} * fn_phonetic_score({{a}}, {{b}}) + {_tri} * fn_trigram_score({{a}}, {{b}})"
        f" + {_lev} * fn_lev_score({{a}}, {{b}})",
        f"hybrid dm {_dm} / tri {_tri} / lev {_lev}")


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


def source_breakdown(scored_with_source, threshold):
    """[(score, source)] -> {source: (pairs, predicted duplicate)} at this threshold."""
    out = defaultdict(lambda: [0, 0])
    for score, source in scored_with_source:
        out[source][0] += 1
        out[source][1] += score >= threshold - EPS
    return {s: tuple(v) for s, v in out.items()}


def best_hybrid(best_rows):
    """The is_best row of the Hybrid weight set with the highest F1 (first set on ties)."""
    rows = [r for r in best_rows if r["method"] in HYBRID_BY_NAME]
    return max(rows, key=lambda r: r["f1"]) if rows else None


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

        metrics_rows, source_rows = [], []
        for method, (expr, sql_function) in METHODS.items():
            cur.execute("""
                INSERT INTO match_method (method_name, sql_function) VALUES (%s, %s)
                ON CONFLICT (method_name) DO UPDATE SET sql_function = EXCLUDED.sql_function
                RETURNING method_id
            """, (method, sql_function))
            method_id = cur.fetchone()[0]

            for normalized in ((True,) if method in HYBRID_BY_NAME else (False, True)):
                col = "normalized_name" if normalized else "full_name"
                score_sql = expr.format(a=f"a.{col}", b=f"b.{col}")
                t0 = time.perf_counter()
                cur.execute(f"""
                    SELECT g.record_id_a, g.record_id_b, g.is_duplicate,
                           round(({score_sql})::numeric, 4)::float8, g.source
                    FROM gold_pair g
                    JOIN name_record a ON a.record_id = g.record_id_a
                    JOIN name_record b ON b.record_id = g.record_id_b
                """)
                pairs = cur.fetchall()
                duration_ms = (time.perf_counter() - t0) * 1000
                scored = [(score, is_dup) for _, _, is_dup, score, _ in pairs]

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
                    for a, b, _, score, _ in pairs:
                        copy.write_row((best["run_id"], a, b, score,
                                        score >= best["threshold"] - EPS))
                metrics_rows += sweep
                by_source = source_breakdown([(p[3], p[4]) for p in pairs], best["threshold"])
                source_rows += [{"method": method, "normalized": normalized,
                                 "threshold": best["threshold"], "source": src,
                                 "pairs": n, "predicted_duplicate": k,
                                 "rate": f"{k / n:.4f}"}
                                for src, (n, k) in sorted(by_source.items())]
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

    out_src = ROOT / "results" / "metrics_by_source.csv"
    with open(out_src, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(source_rows[0]))
        w.writeheader()
        w.writerows(source_rows)

    hybrid = best_hybrid([r for r in metrics_rows if r["is_best"]])
    out_hybrid = ROOT / "results" / "hybrid_weights.json"
    out_hybrid.write_text(json.dumps({
        "method": hybrid["method"],
        "weights": dict(zip(HYBRID_KEYS, HYBRID_BY_NAME[hybrid["method"]])),
        "threshold": hybrid["threshold"], "f1": round(hybrid["f1"], 4)}, indent=2) + "\n",
        encoding="utf-8")

    print(f"\nwrote {len(metrics_rows)} rows -> {out}")
    print(f"wrote {len(source_rows)} rows -> {out_src}")
    print(f"best Hybrid: {hybrid['method']} (F1 {hybrid['f1']:.4f}) -> {out_hybrid}\n")
    print(f"{'method':<16}{'normalized':<12}{'best_t':>7}{'precision':>11}{'recall':>8}{'f1':>8}")
    for r in sorted((r for r in metrics_rows if r["is_best"]), key=lambda r: -r["f1"]):
        print(f"{r['method']:<16}{str(r['normalized']):<12}{r['threshold']:>7.2f}"
              f"{r['precision']:>11.4f}{r['recall']:>8.4f}{r['f1']:>8.4f}")

    sources = sorted({r["source"] for r in source_rows})
    print("\nshare predicted duplicate at the best threshold "
          "(duplicate = recall, others = false-positive rate)")
    print(f"{'method':<16}{'norm':<6}" + "".join(f"{s[:13]:>14}" for s in sources))
    rates = defaultdict(dict)
    for r in source_rows:
        rates[(r["method"], r["normalized"])][r["source"]] = r["rate"]
    for (m, norm), by in rates.items():
        print(f"{m:<16}{'yes' if norm else 'no':<6}"
              + "".join(f"{by.get(s, '-'):>14}" for s in sources))


if __name__ == "__main__":
    main()
