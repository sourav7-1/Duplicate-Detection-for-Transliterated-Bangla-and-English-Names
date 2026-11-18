import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from make_pairs import build_pairs  # noqa: E402

# person 1: 3 records; person 2: 2 records; person 3: hard negative of person 2
# ("Sen" -> "Son" is in CONFUSABLE); persons 4-9: one record each, used as pool fodder.
ROWS = [{"record_id": r, "person_id": p, "full_name": n, "variant_type": t} for r, p, n, t in [
    (1, 1, "Rahim Uddin", "original"), (2, 1, "Md. Rahim Uddin", "prefix"),
    (3, 1, "Raheem Uddin", "vowel"),
    (4, 2, "Prosenjit Kumar Sen", "original"), (5, 2, "Prosenjit Kumar Senn", "typo"),
    (6, 3, "Prosenjit Kumar Son", "hard_negative"),
] + [(r, r, f"Name {r}", "original") for r in range(7, 13)]]


def test_build_pairs():
    # 4 duplicates -> 4 non-duplicates: 2 hard, then round-robin trigram/dmetaphone.
    # (7, 8) is in both pools: drawn once, by whichever pool reaches it first.
    candidates = {"trigram": {(7, 8), (7, 9), (7, 10)}, "dmetaphone": {(7, 8), (8, 9)},
                  "levenshtein": set()}
    pairs, stats = build_pairs(ROWS, candidates, seed=0)
    person = {r["record_id"]: r["person_id"] for r in ROWS}

    assert pairs == build_pairs(ROWS, candidates, seed=0)[0]           # deterministic
    assert {(a, b) for a, b, d, _ in pairs if d} == {(1, 2), (1, 3), (2, 3), (4, 5)}
    negs = [(a, b, s) for a, b, d, s in pairs if not d]
    assert len(negs) == 4 and len({(a, b) for a, b, _ in negs}) == 4  # balanced, no repeats
    assert all(a < b and person[a] != person[b] for a, b, _ in negs)
    assert {(4, 6, "hard_negative"), (5, 6, "hard_negative")} <= set(negs)
    assert Counter(s for *_, s in negs) == {"hard_negative": 2, "trigram": 1, "dmetaphone": 1}
    assert all(s == "duplicate" for *_, d, s in pairs if d)
    assert stats["unmatched_hard_negatives"] == 0


def test_round_robin_shares_and_random_fill():
    # Many duplicates, small pools: every pool is used up, then random pairs fill the rest.
    rows = [{"record_id": r, "person_id": 1 if r <= 6 else r, "full_name": f"N {r}",
             "variant_type": "original"} for r in range(1, 21)]       # 15 duplicate pairs
    candidates = {"trigram": {(7, 8), (7, 9), (7, 10), (7, 11)},
                  "dmetaphone": {(8, 9)}, "levenshtein": {(9, 10), (9, 11)}}
    pairs, stats = build_pairs(rows, candidates, seed=1)
    assert stats["trigram"] == 4 and stats["dmetaphone"] == 1 and stats["levenshtein"] == 2
    assert stats["random"] == 15 - 7
    assert sum(1 for p in pairs if not p[2]) == 15
