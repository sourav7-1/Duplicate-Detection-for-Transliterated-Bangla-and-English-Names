import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ui.components import (best_f1_table_html, duplicates_table_html,  # noqa: E402
                           performance_table_html, verdict)


@pytest.mark.parametrize("score, threshold, expected", [
    (0.80, 0.50, "Likely duplicate"),
    (0.65, 0.50, "Likely duplicate"),     # exactly threshold + 0.15
    (0.6499, 0.50, "Likely duplicate"),   # shown as 0.650, so it must agree
    (0.649, 0.50, "Needs review"),
    (0.50, 0.50, "Needs review"),         # exactly threshold
    (0.499, 0.50, "Different person"),
    (0.95, 0.85, "Needs review"),         # float edge: 0.85 + 0.15 = 1.0
    (1.00, 0.85, "Likely duplicate"),
])
def test_verdict(score, threshold, expected):
    assert verdict(score, threshold) == expected


def test_table_escapes_names():
    rows = [(7, 1, "<script>alert(1)</script>", "<b>x</b> & \"q\"", 0.9),
            (8, 2, "D'Costa <img src=x onerror=alert(1)>", None, 0.55)]
    out = duplicates_table_html(rows, 0.5)
    for raw in ("<script>", "<b>x</b>", "<img"):
        assert raw not in out                         # no markup from the database survives
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &quot;q&quot;" in out
    assert "D&#x27;Costa &lt;img" in out
    assert "0.900" in out and "Likely duplicate" in out
    assert "0.550" in out and "Needs review" in out
    assert "<td" in out and "–" in out                # missing normalized name shown as a dash


def _row(method, normalized, f1, precision="0.9", recall="0.8", threshold="0.5"):
    return {"method": method, "normalized": str(normalized), "is_best": "True",
            "f1": f1, "precision": precision, "recall": recall, "threshold": threshold}


def test_best_f1_table_side_by_side_and_highlight():
    metrics = [_row("trigram", False, "0.9094"), _row("trigram", True, "0.9310"),
               _row("dmetaphone", False, "0.9452"), _row("dmetaphone", True, "0.9495"),
               _row("exact", False, "0.1289"),                     # no normalized row
               {**_row("exact", True, "0.99"), "is_best": "False"}]  # not a best row: ignored
    out = best_f1_table_html(metrics)
    assert "Raw names" in out and "Normalized names" in out
    # sorted by best F1: Double Metaphone, Trigram, Exact
    assert out.index("Double Metaphone") < out.index("Trigram") < out.index("Exact")
    assert out.count("font-weight:700") == 1                         # one highlighted cell
    assert 'font-weight:700;">0.950</td>' in out                     # ...and it is 0.950
    assert 'colspan="4">–' in out                                     # missing normalized row


def test_performance_table():
    bench = [{"method": m, "n_records": str(n), "gin_index": str(g), "mean_ms": str(ms),
              "runs": "5"}
             for m, n, g, ms in [("trigram", 1000, False, 2.0), ("trigram", 1000, True, 2.0),
                                 ("trigram", 100000, False, 400.0),
                                 ("trigram", 100000, True, 32.0),
                                 ("soundex", 100000, False, 480.0)]]   # soundex: no GIN row
    out = performance_table_html(bench)
    assert "1k records" in out and "100k records" in out and "Speedup at 100k" in out
    assert "12.5×" in out                    # 400 / 32
    assert ">400.0<" in out and ">32.0<" in out
    assert out.count("–") >= 2               # soundex: missing GIN cell and speedup
