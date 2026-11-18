import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate import (HYBRID_BY_NAME, METHODS, best_hybrid, best_row,  # noqa: E402
                      compute_metrics, hybrid_name, source_breakdown)


def test_compute_metrics():
    scored = [(0.9, True), (0.7, True), (0.4, True), (0.8, False), (0.2, False)]
    m = compute_metrics(scored, 0.7)    # 0.7 counts as a match (>= threshold)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == m["recall"] == m["f1"] == 2 / 3

    none = compute_metrics(scored, 0.95)   # nothing predicted: no division by zero
    assert none["precision"] == none["f1"] == 0.0


def test_best_row_prefers_stricter_threshold_on_tie():
    rows = [{"threshold": 0.6, "f1": 0.8}, {"threshold": 0.7, "f1": 0.8},
            {"threshold": 0.9, "f1": 0.5}]
    assert best_row(rows)["threshold"] == 0.7


def test_hybrid_methods_registered():
    assert list(HYBRID_BY_NAME) == ["hybrid_40_40_20", "hybrid_50_30_20", "hybrid_34_33_33"]
    assert hybrid_name((0.34, 0.33, 0.33)) == "hybrid_34_33_33"
    expr = METHODS["hybrid_50_30_20"][0].format(a="a.x", b="b.x")
    assert expr == ("0.5 * fn_phonetic_score(a.x, b.x) + 0.3 * fn_trigram_score(a.x, b.x)"
                    " + 0.2 * fn_lev_score(a.x, b.x)")
    assert all(abs(sum(w) - 1) < 1e-9 for w in HYBRID_BY_NAME.values())


def test_best_hybrid_ignores_other_methods():
    rows = [{"method": "dmetaphone", "f1": 0.99}, {"method": "hybrid_40_40_20", "f1": 0.90},
            {"method": "hybrid_50_30_20", "f1": 0.93}, {"method": "hybrid_34_33_33", "f1": 0.93}]
    assert best_hybrid(rows)["method"] == "hybrid_50_30_20"    # first set wins a tie
    assert best_hybrid([{"method": "trigram", "f1": 1.0}]) is None


def test_source_breakdown():
    scored = [(0.9, "duplicate"), (0.7, "duplicate"), (0.4, "duplicate"),
              (0.8, "trigram"), (0.2, "trigram"), (0.7, "hard_negative")]
    assert source_breakdown(scored, 0.7) == {"duplicate": (3, 2), "trigram": (2, 1),
                                             "hard_negative": (1, 1)}
