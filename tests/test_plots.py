import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plots import (METHODS, NEG_SOURCES, hybrid_method, method_tick,  # noqa: E402
                   plot_f1_bars, plot_fp_by_source, plot_pr_curves)

HYB = "hybrid_40_40_20"


def _metric(method, norm, f1):
    return {"method": method, "normalized": str(norm), "is_best": "True", "f1": str(f1)}


def test_hybrid_helpers(tmp_path):
    assert method_tick(HYB) == "hybrid\n0.40/0.40/0.20"
    assert method_tick("soundex") == "soundex"
    f = tmp_path / "w.json"
    f.write_text('{"method": "hybrid_50_30_20", "weights": {}}')
    assert hybrid_method(f) == "hybrid_50_30_20"
    assert hybrid_method(tmp_path / "missing.json") is None


def test_f1_bars_add_hybrid_normalized_only():
    metrics = [_metric(m, n, 0.8) for m in METHODS for n in (False, True)]
    metrics.append(_metric(HYB, True, 0.95))
    ax = plot_f1_bars(metrics, HYB).axes[0]
    assert len(ax.patches) == 2 * len(METHODS) + 1           # Hybrid: one bar, no raw bar
    assert ax.get_xticklabels()[-1].get_text() == "hybrid\n0.40/0.40/0.20"
    # Without a winner (evaluate.py not run), the chart is unchanged.
    assert len(plot_f1_bars(metrics, None).axes[0].patches) == 2 * len(METHODS)


def test_pr_curves_add_hybrid_panel():
    rng = np.random.default_rng(0)
    def d():
        score = rng.random(40)
        dup = score + rng.normal(0, 0.2, 40) > 0.5
        return {"score": score, "dup": dup, "pred": score >= 0.5}
    pairs = {(m, n): d() for m in METHODS for n in (False, True)}
    pairs[(HYB, True)] = d()
    fig = plot_pr_curves(pairs, HYB)
    assert len(fig.axes) == len(METHODS) + 1
    assert fig.axes[-1].get_title(loc="left") == "hybrid 0.40/0.40/0.20"
    assert len(fig.axes[-1].lines) == 2                       # normalized curve + its dot


def test_fp_by_source_grouped_bars():
    rows = [{"method": m, "normalized": "True", "source": s, "rate": "0.25"}
            for m in METHODS + [HYB] for s in NEG_SOURCES + ["duplicate"]]
    rows += [{"method": "trigram", "normalized": "False", "source": "random", "rate": "0.9"}]
    ax = plot_fp_by_source(rows, HYB).axes[0]
    assert len(ax.patches) == (len(METHODS) + 1) * len(NEG_SOURCES)  # no "duplicate" group
    assert [t.get_text() for t in ax.get_xticklabels()] == [
        "hard negative", "trigram", "dmetaphone", "levenshtein", "random"]
    assert {p.get_height() for p in ax.patches} == {25.0}     # raw rows are ignored
    assert len(ax.get_legend().get_texts()) == len(METHODS) + 1
