"""Endpoint tests for web_api.py with FastAPI's TestClient.

Database endpoints need the database from .env (load_data.py + sql/04 applied) and are
skipped if it is unreachable. /api/metrics and /api/benchmark read results/*.csv.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import web_api  # noqa: E402
from ui.db import connection_error  # noqa: E402

client = TestClient(web_api.app)
needs_db = pytest.mark.skipif(connection_error() is not None, reason="database not available")


@needs_db
def test_stats():
    s = client.get("/api/stats").json()
    assert s["records"] > 0 and s["gold_pairs"] > 0
    assert 0 < s["best_method"]["f1"] <= 1
    assert s["speedup"]["n_records"] == 100_000
    assert set(s["speedup"]["by_method"]) == {"exact", "trigram", "levenshtein",
                                              "dmetaphone", "soundex"}


@needs_db
def test_search():
    r = client.get("/api/search", params={"name": "Mohammad Nasir Uddin"})
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "Custom normalization" and body["normalize"] is False
    assert 0 < len(body["matches"]) <= 10
    scores = [m["score"] for m in body["matches"]]
    assert scores == sorted(scores, reverse=True) and min(scores) >= 0.5
    assert body["matches"][0]["score"] == 1.0
    assert "fn_normalize_bn_name" in body["sql"]


@needs_db
def test_search_normalize_switches_raw_methods_to_normalized_names():
    params = {"name": "Md. Hasan Islam", "method": "Levenshtein"}
    raw = client.get("/api/search", params=params).json()
    norm = client.get("/api/search", params={**params, "normalize": "true"}).json()
    assert "fn_lev_score(full_name" in raw["sql"]
    assert "fn_lev_score(normalized_name" in norm["sql"]
    assert len(norm["matches"]) >= len(raw["matches"])   # prefix variants now match


@needs_db
def test_search_verdicts_and_matching_words():
    body = client.get("/api/search", params={"name": "Mohammad Rakib Rahman"}).json()
    by_name = {m["full_name"]: m for m in body["matches"]}
    munir = by_name["Md. Munir Rahman"]
    assert munir["verdict"] == "Needs review"                    # same rule as Streamlit
    bold = [p["text"] for p in munir["name_parts"] if p["match"]]
    assert bold == ["Md", "Rahman"]                              # Md ~ Mohammad; not Munir
    assert "".join(p["text"] for p in munir["name_parts"]) == "Md. Munir Rahman"
    glued = by_name.get("Md.Monir Rahman")
    if glued:                                                    # "Md.Monir": split at "."
        assert [p["text"] for p in glued["name_parts"] if p["match"]] == ["Md", "Rahman"]
    assert all(m["verdict"] == "Likely duplicate" for m in body["matches"] if m["score"] >= 0.85)


def test_search_rejects_bad_input():
    assert client.get("/api/search").status_code == 422                    # name missing
    assert client.get("/api/search", params={"name": "   "}).status_code == 400
    assert client.get("/api/search", params={"name": "x" * 151}).status_code == 400
    r = client.get("/api/search", params={"name": "Rahim", "method": "Nope"})
    assert r.status_code == 400 and "unknown method" in r.json()["detail"]
    r = client.get("/api/search", params={"name": "Rahim", "threshold": 2})
    assert r.status_code == 422


@needs_db
def test_compare():
    body = client.get("/api/compare", params={"name": "Asshok Dey"}).json()
    assert [m["method"] for m in body["methods"]] == web_api.queries.METHOD_NAMES
    assert body["normalized"] == "asok dey"
    for m in body["methods"]:
        assert len(m["matches"]) <= 5
        assert all(x["score"] >= 0.3 for x in m["matches"])
    # one row per candidate, a score and verdict from every method
    cands = {c["full_name"]: c for c in body["candidates"]}
    tops = {x["record_id"] for m in body["methods"] for x in m["matches"]}
    assert {c["record_id"] for c in body["candidates"]} == tops
    ashok = cands["Ashok Dey"]
    assert set(ashok["scores"]) == set(body["method_names"]) == set(ashok["verdicts"])
    assert ashok["scores"]["Double Metaphone"] == 0.5               # demo notes, name 4
    assert ashok["verdicts"]["Double Metaphone"] == "Different person"
    assert ashok["verdicts"]["Custom normalization"] == "Likely duplicate"


@needs_db
def test_normalize_steps_match_sql_function():
    name = "Md. Rakib Rahmman"
    body = client.get("/api/normalize-steps", params={"name": name}).json()
    with web_api.queries.get_conn().cursor() as cur:
        cur.execute("SELECT fn_normalize_bn_name(%s)", (name,))
        assert body["normalized"] == cur.fetchone()[0] == "muhamad rakib rahman"
    steps = body["steps"]
    assert steps[0]["rule"] == "lower-case" and steps[0]["before"] == name
    assert all(a["after"] == b["before"] for a, b in zip(steps, steps[1:]))  # a chain
    assert steps[-1]["after"] == body["normalized"]
    groups = {s["rule_group"] for s in steps}
    assert {"punctuation", "prefix", "double_consonant"} <= groups


def test_metrics():
    body = client.get("/api/metrics").json()
    f1 = [r["f1"] for r in body["best"]]
    assert f1 == sorted(f1, reverse=True)
    assert any(r["method"].startswith("hybrid_") for r in body["best"])
    assert {"hard_negative", "random", "duplicate"} <= {r["source"] for r in body["by_source"]}
    assert all(0 <= r["rate"] <= 1 for r in body["by_source"])
    assert set(body["hybrid_weights"]) == {"dmetaphone", "trigram", "levenshtein"}


def test_benchmark():
    body = client.get("/api/benchmark").json()
    assert body["largest"] == 100_000
    assert len(body["rows"]) == 30                       # 5 methods x 3 sizes x index on/off
    assert isinstance(body["rows"][0]["mean_ms"], float)
    assert isinstance(body["rows"][0]["gin_index"], bool)
    assert all(v > 1 for v in body["speedup"].values())


def test_missing_results_file_is_404(monkeypatch):
    monkeypatch.setattr(web_api.queries, "load_benchmark", lambda: None)
    r = client.get("/api/benchmark")
    assert r.status_code == 404 and "benchmark.py" in r.json()["detail"]


def test_db_down_is_503(monkeypatch):
    monkeypatch.setattr(web_api, "connection_error", lambda: "connection refused")
    r = client.get("/api/stats")
    assert r.status_code == 503 and "connection refused" in r.json()["detail"]


def test_static_site_served_at_root():
    r = client.get("/")
    assert r.status_code == 200 and "<nav" in r.text and "NameDedup" in r.text
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/api/does-not-exist").status_code == 404


def test_report_pdf_served_from_docs(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "ROOT", tmp_path)
    assert client.head("/report.pdf").status_code == 404            # not added yet
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.pdf").write_bytes(b"%PDF-1.4 test")
    r = client.get("/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert client.head("/report.pdf").status_code == 200            # the page checks with HEAD
