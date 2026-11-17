"""Make the report figures -> docs/figures/*.png

  f1_by_method.png        F1 at each method's best threshold, raw vs normalized (RQ1, RQ2)
  pr_curves.png           precision-recall curve per method, raw vs normalized
  query_time_scaling.png  records vs query time, GIN index off / on (RQ3)
  failure_table.png       miss rate per variant type and method (+ results/failure_table.csv)

Inputs: results/metrics.csv, results/benchmark.csv, and per-pair scores from the
latest evaluate.py runs in the database (match_result).
Uses only csv + numpy + matplotlib (pandas is blocked by this machine's App Control policy).

Usage: python src/plots.py
"""
import csv
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from load_data import ROOT, connect  # noqa: E402

FIG = ROOT / "docs" / "figures"
RESULTS = ROOT / "results"
METHODS = ["exact", "trigram", "levenshtein", "dmetaphone", "soundex"]
SETTINGS = [(False, "raw"), (True, "norm")]

# Reference palette (validated: categorical slots 1-2 pass all checks on #fcfcfb).
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
C1, C2 = "#2a78d6", "#eb6834"          # slot 1 blue, slot 2 orange
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK_2, "axes.edgecolor": BASELINE,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "lines.linewidth": 2,
})


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(fig, name):
    fig.savefig(FIG / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  {FIG / name}")


# ------------------------------------------------------------------ (1) F1 bars
def plot_f1_bars(metrics):
    best = {(r["method"], r["normalized"] == "True"): float(r["f1"])
            for r in metrics if r["is_best"] == "True"}
    x = np.arange(len(METHODS))
    w = 0.38
    fig, ax = plt.subplots(figsize=(8, 4))
    for offset, norm, color, label in [(-w / 2, False, C1, "Raw names"),
                                       (w / 2, True, C2, "Normalized names")]:
        vals = [best[(m, norm)] for m in METHODS]
        bars = ax.bar(x + offset, vals, w, color=color, label=label,
                      edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.bar_label(bars, labels=[f"{v:.3f}" for v in vals], padding=2,
                     fontsize=8, color=INK_2)
    ax.set_xticks(x, METHODS)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("F1 at best threshold")
    ax.grid(axis="x", visible=False)
    ax.set_title("F1 per method, raw vs normalized names", loc="left")
    ax.legend(loc="upper left", ncols=2)
    save(fig, "f1_by_method.png")


# ----------------------------------------------------------- (2) PR curves
def load_pair_scores():
    """{(method, normalized): dict of numpy arrays} from the latest stored run of each."""
    query = """
        WITH latest AS (
            SELECT DISTINCT ON (m.method_name, r.use_normalization)
                   r.run_id, m.method_name, r.use_normalization
            FROM experiment_run r
            JOIN match_method m USING (method_id)
            WHERE EXISTS (SELECT 1 FROM match_result x WHERE x.run_id = r.run_id)
            ORDER BY m.method_name, r.use_normalization, r.run_id DESC
        )
        SELECT l.method_name, l.use_normalization, mr.score::float8,
               mr.predicted_duplicate, g.is_duplicate, a.variant_type, b.variant_type
        FROM latest l
        JOIN match_result mr USING (run_id)
        JOIN gold_pair g ON g.record_id_a = mr.record_id_a AND g.record_id_b = mr.record_id_b
        JOIN name_record a ON a.record_id = mr.record_id_a
        JOIN name_record b ON b.record_id = mr.record_id_b
    """
    groups = defaultdict(list)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query)
        for method, norm, *rest in cur:
            groups[(method, norm)].append(rest)
    out = {}
    for key, rows in groups.items():
        score, pred, dup, type_a, type_b = zip(*rows)
        out[key] = {"score": np.array(score), "pred": np.array(pred, bool),
                    "dup": np.array(dup, bool), "type_a": np.array(type_a),
                    "type_b": np.array(type_b)}
    return out


def pr_curve(scores, labels):
    """Precision/recall at every distinct score used as the threshold."""
    order = np.argsort(-scores, kind="stable")
    s, y = scores[order], labels[order].astype(int)
    tp, fp = np.cumsum(y), np.cumsum(1 - y)
    last = np.r_[np.diff(s) != 0, True]          # keep the last index of each score tie
    return tp[last] / y.sum(), tp[last] / (tp[last] + fp[last])


def plot_pr_curves(pairs):
    fig, axes = plt.subplots(1, len(METHODS), figsize=(15, 3.6), sharey=True)
    for ax, method in zip(axes, METHODS):
        for norm, color, label in [(False, C1, "Raw"), (True, C2, "Normalized")]:
            d = pairs[(method, norm)]
            recall, precision = pr_curve(d["score"], d["dup"])
            ax.plot(recall, precision, color=color, label=label, zorder=3,
                    drawstyle="steps-post")
            tp = (d["pred"] & d["dup"]).sum()           # best-threshold operating point
            ax.plot(tp / d["dup"].sum(), tp / max(d["pred"].sum(), 1), "o", color=color,
                    markersize=8, markeredgecolor=INK, markeredgewidth=1, zorder=4)
        ax.set_title(method, loc="left")
        ax.set_xlim(0, 1.02)
        ax.set_ylim(0.45, 1.02)
        ax.set_xlabel("Recall")
    axes[0].set_ylabel("Precision")
    axes[0].legend(loc="lower left")
    fig.suptitle("Precision-recall per method (dot = best-F1 threshold)",
                 x=0.005, ha="left", fontweight="bold", fontsize=12)
    fig.tight_layout()
    save(fig, "pr_curves.png")


# ------------------------------------------------------- (3) query-time scaling
def plot_scaling(bench):
    fig, axes = plt.subplots(1, len(METHODS), figsize=(15, 3.6), sharey=True)
    for ax, method in zip(axes, METHODS):
        for gin, color, label in [("False", C1, "No index (Seq Scan)"),
                                  ("True", C2, "GIN trigram index")]:
            d = sorted((r for r in bench if r["method"] == method and r["gin_index"] == gin),
                       key=lambda r: int(r["n_records"]))
            ax.errorbar([int(r["n_records"]) for r in d], [float(r["mean_ms"]) for r in d],
                        yerr=[float(r["std_ms"]) for r in d], color=color, label=label,
                        marker="o", markersize=8, markeredgecolor=SURFACE,
                        markeredgewidth=2, capsize=3, zorder=3)
        biggest = max(int(r["n_records"]) for r in bench)
        ms = {r["gin_index"]: float(r["mean_ms"]) for r in bench
              if r["method"] == method and int(r["n_records"]) == biggest}
        ax.annotate(f"{ms['False'] / ms['True']:.1f}x faster at {biggest // 1000}k",
                    xy=(0.98, 0.04), xycoords="axes fraction", ha="right",
                    fontsize=9, color=INK_2)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks([1_000, 10_000, 100_000], ["1k", "10k", "100k"])
        ax.minorticks_off()
        ax.set_title(method, loc="left")
        ax.set_xlabel("Records")
    axes[0].set_ylabel("Query time, ms (mean ± std, log)")
    axes[0].legend(loc="upper left")
    fig.suptitle("Query time vs table size, with and without the GIN index",
                 x=0.005, ha="left", fontweight="bold", fontsize=12)
    fig.tight_layout()
    save(fig, "query_time_scaling.png")


# -------------------------------------------------------------- (4) failures
def failure_table(pairs):
    """Miss rate (false negatives / true duplicate pairs) per variant type.

    Only original-vs-variant pairs are used, so each pair tests exactly one rule.
    Returns (variant_types sorted worst-first, columns, rates[types x cols], counts).
    """
    columns = [(m, norm, tag) for m in METHODS for norm, tag in SETTINGS]
    missed, total = defaultdict(int), defaultdict(int)
    for m, norm, tag in columns:
        d = pairs[(m, norm)]
        one_orig = d["dup"] & ((d["type_a"] == "original") ^ (d["type_b"] == "original"))
        vtype = np.where(d["type_a"] == "original", d["type_b"], d["type_a"])[one_orig]
        miss = ~d["pred"][one_orig]
        for t, x in zip(vtype, miss):
            total[(t, tag, m)] += 1
            missed[(t, tag, m)] += int(x)
    types = sorted({t for t, _, _ in total})
    rates = np.array([[missed[(t, tag, m)] / total[(t, tag, m)] for m, _, tag in columns]
                      for t in types])
    counts = {t: total[(t, "raw", METHODS[0])] for t in types}
    order = np.argsort(-rates.mean(axis=1), kind="stable")
    return [types[i] for i in order], columns, rates[order], counts


def plot_failure_table(types, columns, rates, counts):
    with open(RESULTS / "failure_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["variant_type", "pairs"] + [f"{m}_{tag}" for m, _, tag in columns])
        for t, row in zip(types, rates):
            w.writerow([t, counts[t]] + [f"{v:.4f}" for v in row])
    print(f"  {RESULTS / 'failure_table.csv'}")

    vals = rates * 100
    cmap = LinearSegmentedColormap.from_list("seq_blue", SEQ)
    fig, ax = plt.subplots(figsize=(11, 0.42 * len(types) + 1.6))
    ax.imshow(vals, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for i in range(vals.shape[0]):
        for j in range(vals.shape[1]):
            v = vals[i, j]
            ax.text(j, i, f"{v:.0f}%", ha="center", va="center", fontsize=8.5,
                    color="#ffffff" if v >= 50 else INK)
    ax.set_xticks(range(len(columns)), [f"{m}\n{tag}" for m, _, tag in columns], fontsize=8.5)
    ax.set_yticks(range(len(types)), [f"{t}  (n={counts[t]})" for t in types], fontsize=9)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks(np.arange(-0.5, vals.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, vals.shape[0], 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.set_title("Missed duplicates by variant type (% of original-vs-variant pairs not "
                 "matched at each method's best threshold)", loc="left", pad=36)
    save(fig, "failure_table.png")


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    pairs = load_pair_scores()
    plot_f1_bars(read_csv(RESULTS / "metrics.csv"))
    plot_pr_curves(pairs)
    plot_scaling(read_csv(RESULTS / "benchmark.csv"))
    plot_failure_table(*failure_table(pairs))


if __name__ == "__main__":
    main()
