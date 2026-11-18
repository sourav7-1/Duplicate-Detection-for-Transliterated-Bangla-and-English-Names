import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ui.components import (COMMON_TOKENS, best_f1_table_html,  # noqa: E402
                           duplicates_table_html, performance_table_html, verdict)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("score, expected", [
    (1.00, "Likely duplicate"),
    (0.85, "Likely duplicate"),     # boundary
    (0.8499, "Likely duplicate"),   # shown as 0.850, so it must agree
    (0.849, "Needs review"),
    (0.667, "Needs review"),        # "Md. Munir Rahman" vs "Mohammad Rakib Rahman"
    (0.65, "Needs review"),         # boundary
    (0.649, "Different person"),
    (0.0, "Different person"),
])
def test_verdict(score, expected):
    assert verdict(score) == expected


def test_table_escapes_names():
    rows = [(7, 1, "<script>alert(1)</script>", "<b>x</b> & \"q\"", 0.9, None),
            (8, 2, "D'Costa <img src=x onerror=alert(1)>", None, 0.70, None)]
    out = duplicates_table_html(rows)
    for raw in ("<script>", "<b>x</b>", "<img"):
        assert raw not in out                         # no markup from the database survives
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &quot;q&quot;" in out
    assert "D&#x27;Costa &lt;img" in out
    assert "0.900" in out and "Likely duplicate" in out
    assert "0.700" in out and "Needs review" in out
    assert "<td" in out and "–" in out                # missing normalized name shown as a dash
    assert "without common tokens" not in out         # no extra column when the option is off


def test_table_core_score_verdict_uses_lower_score():
    rows = [(77, 77, "Md. Rakib Rahman", "muhammad rakib rahman", 1.0, 1.0),
            (37, 37, "Md. Munir Rahman", "muhammad munir rahman", 0.667, 0.0),
            (46, 46, "Md. Rakib Hossain", "muhammad rakib hossain", 0.536, 1.0)]
    out = duplicates_table_html(rows)
    assert "Trigram score without common tokens" in out
    assert "0.667" in out and "0.000" in out
    assert out.count("Likely duplicate") == 1         # only the real Rakib Rahman
    assert out.count("Different person") == 2         # Munir and Rakib Hossain
    assert "Needs review" not in out


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


def test_common_tokens_match_sql():
    # The word alternation inside fn_strip_common_tokens, e.g. '\m(muhammad|md|...)\M'
    sql = (ROOT / "sql" / "04_normalize.sql").read_text(encoding="utf-8")
    body = sql[sql.index("FUNCTION fn_strip_common_tokens"):]
    words = re.search(r"\\m\(([a-z|]+)\)\\M", body).group(1).split("|")
    assert words == COMMON_TOKENS


def test_method_label():
    from ui.components import method_label
    assert method_label("dmetaphone") == "Double Metaphone"
    assert method_label("hybrid_40_40_20") == "Hybrid 0.40/0.40/0.20"
    assert method_label("hybrid_34_33_33") == "Hybrid 0.34/0.33/0.33"


def test_load_hybrid_weights(tmp_path):
    from ui.queries import load_hybrid_weights
    good = tmp_path / "w.json"
    good.write_text('{"method": "hybrid_50_30_20", "weights": {"dmetaphone": 0.5, '
                    '"trigram": 0.3, "levenshtein": 0.2}, "threshold": 0.6, "f1": 0.9}')
    assert load_hybrid_weights(good) == {"dmetaphone": 0.5, "trigram": 0.3, "levenshtein": 0.2}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_hybrid_weights(bad) is None                    # app falls back, no crash
    assert load_hybrid_weights(tmp_path / "missing.json") is None
