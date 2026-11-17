import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate import best_row, compute_metrics  # noqa: E402


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
