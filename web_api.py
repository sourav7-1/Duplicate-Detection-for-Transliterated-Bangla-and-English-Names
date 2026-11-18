"""JSON API + static website for the duplicate-name finder.

Run: python -m uvicorn web_api:app --reload
Reuses the Streamlit app's data layer (src/ui/queries.py, src/ui/db.py), so the API and
the Streamlit app always run the same SQL. Pages in web/ are served at /.

Endpoints (all GET, all JSON):
  /api/stats                 record count, gold pairs, best method + F1, speedup at 100k
  /api/search                ?name=&method=&normalize=&threshold=  top 10 matches, each
                             with a verdict and name_parts (words flagged as matching)
  /api/compare               ?name=  each method's top matches, plus "candidates": the
                             union of them, every one scored (and given a verdict) by
                             every method
  /api/normalize-steps       ?name=  each normalization rule that changed the name
  /api/metrics               best row per method + per-source false-positive rates
  /api/benchmark             rows of results/benchmark.csv
Errors: 400 for bad input, 404 when a results file is missing, 503 when the database is
unreachable; the body is {"detail": "..."}.
"""
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from ui import queries  # noqa: E402
from ui.components import verdict  # noqa: E402  (same 0.85 / 0.65 rule as Streamlit)
from ui.db import connection_error  # noqa: E402

app = FastAPI(title="NameDedup API", version="1.0")


# ---------------------------------------------------------------------- helpers
def num(value):
    """CSV string -> int / float / bool where it looks like one, else the string."""
    if value in ("True", "False"):
        return value == "True"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def typed(rows):
    return [{k: num(v) for k, v in r.items()} for r in rows]


def require_db():
    problem = connection_error()
    if problem:
        raise HTTPException(503, f"database unavailable: {problem}")


def require_file(rows, script):
    if rows is None:
        raise HTTPException(404, f"results not found; run: python src/{script}")
    return rows


def clean_name(name):
    name = name.strip()
    if not name:
        raise HTTPException(400, "name must not be empty")
    if len(name) > 150:                       # name_record.full_name is VARCHAR(150)
        raise HTTPException(400, "name is longer than 150 characters")
    return name


def check_method(method):
    if method not in queries.METHODS:
        raise HTTPException(400, f"unknown method {method!r}; use one of {queries.METHOD_NAMES}")
    return method


def match(row):
    record_id, person_id, full_name, normalized, score, _core = row
    return {"record_id": record_id, "person_id": person_id, "full_name": full_name,
            "normalized_name": normalized, "score": round(score, 4),
            "verdict": verdict(score)}


# words and the separators between them ("Md.Monir" -> "Md", ".", "Monir"), kept in order
SPLIT = re.compile(r"(\s+|[.,-]+)")


def name_parts(full_name, query_words, normalized):
    """Split full_name into words and the gaps between them; a word is a match when any
    of its normalized words is a word of the normalized query ("Md." ~ "Mohammad")."""
    parts = []
    for text in SPLIT.split(full_name):
        if text:
            words = (normalized.get(text) or "").split()
            parts.append({"text": text, "match": any(w in query_words for w in words)})
    return parts


def with_name_parts(matches, nq):
    words = [w for m in matches for w in SPLIT.split(m["full_name"]) if w]
    normalized = queries.normalize_words(words)
    query_words = set((nq or "").split())
    for m in matches:
        m["name_parts"] = name_parts(m["full_name"], query_words, normalized)
    return matches


def best_rows(metrics):
    """is_best rows of metrics.csv, highest F1 first."""
    return sorted((r for r in typed(metrics) if r["is_best"]), key=lambda r: -r["f1"])


def speedups(bench):
    """{method: no-index mean / GIN mean} at the largest benchmarked size."""
    rows = typed(bench)
    largest = max(r["n_records"] for r in rows)
    mean = {(r["method"], r["gin_index"]): r["mean_ms"] for r in rows
            if r["n_records"] == largest}
    return largest, {m: round(mean[(m, False)] / mean[(m, True)], 1)
                     for m, gin in mean if gin and (m, False) in mean}


# -------------------------------------------------------------------- endpoints
@app.get("/api/stats")
def stats():
    require_db()
    out = queries.counts()
    metrics = queries.load_metrics()
    best = best_rows(metrics)[0] if metrics else None
    out["best_method"] = (None if best is None else
                          {"method": best["method"], "normalized": best["normalized"],
                           "f1": round(best["f1"], 4), "threshold": best["threshold"]})
    bench = queries.load_benchmark()
    if bench:
        largest, speedup = speedups(bench)
        out["speedup"] = {"n_records": largest, "by_method": speedup}
    else:
        out["speedup"] = None
    out["hybrid_weights"] = queries.HYBRID_WEIGHTS
    return out


@app.get("/api/search")
def search(name: str = Query(..., description="name to look up"),
           method: str = "Custom normalization",
           normalize: bool = False,
           threshold: float = Query(0.5, ge=0.0, le=1.0)):
    name, method = clean_name(name), check_method(method)
    require_db()
    nq, rows, elapsed_ms, sql = queries.search(name, method, threshold, normalize=normalize)
    return {"name": name, "normalized": nq, "method": method, "normalize": normalize,
            "threshold": threshold, "elapsed_ms": round(elapsed_ms, 2),
            "matches": with_name_parts([match(r) for r in rows], nq), "sql": sql}


@app.get("/api/compare")
def compare(name: str = Query(...), threshold: float = Query(0.3, ge=0.0, le=1.0),
            limit: int = Query(5, ge=1, le=10)):
    name = clean_name(name)
    require_db()
    methods, nq, info = [], None, {}
    for method in queries.METHOD_NAMES:
        nq, rows, elapsed_ms, _ = queries.search(name, method, threshold, limit=limit)
        methods.append({"method": method, "elapsed_ms": round(elapsed_ms, 2),
                        "matches": [match(r) for r in rows]})
        for r in rows:
            info[r[0]] = {"record_id": r[0], "person_id": r[1], "full_name": r[2],
                          "normalized_name": r[3]}
    # One row per candidate (any method's top matches), scored by every method.
    scores = queries.score_all(name, nq, info)
    candidates = [{**info[rid],
                   "scores": {m: round(s, 4) for m, s in scores[rid].items()},
                   "verdicts": {m: verdict(s) for m, s in scores[rid].items()}}
                  for rid in info]
    candidates.sort(key=lambda c: (-max(c["scores"].values()), c["record_id"]))
    return {"name": name, "normalized": nq, "threshold": threshold,
            "method_names": queries.METHOD_NAMES, "methods": methods,
            "candidates": candidates}


@app.get("/api/normalize-steps")
def normalize_steps(name: str = Query(...)):
    name = clean_name(name)
    require_db()
    steps, result = queries.normalize_steps(name)
    return {"name": name, "normalized": result, "steps": steps}


@app.get("/api/metrics")
def metrics():
    rows = require_file(queries.load_metrics(), "evaluate.py")
    by_source = queries.load_metrics_by_source() or []
    best = best_rows(rows)
    keep = {(r["method"], r["normalized"]) for r in best}
    fp = [r for r in typed(by_source) if (r["method"], r["normalized"]) in keep]
    return {"best": [{k: r[k] for k in ("method", "normalized", "threshold", "precision",
                                        "recall", "f1", "tp", "fp", "fn", "tn")}
                     for r in best],
            "by_source": [{k: r[k] for k in ("method", "normalized", "threshold", "source",
                                             "pairs", "predicted_duplicate", "rate")}
                          for r in fp],
            "hybrid_weights": queries.HYBRID_WEIGHTS}


@app.get("/api/benchmark")
def benchmark():
    rows = require_file(queries.load_benchmark(), "benchmark.py")
    largest, speedup = speedups(rows)
    return {"rows": typed(rows), "largest": largest, "speedup": speedup}


# Last, so /api/* wins over files; html=True serves web/index.html at /.
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
