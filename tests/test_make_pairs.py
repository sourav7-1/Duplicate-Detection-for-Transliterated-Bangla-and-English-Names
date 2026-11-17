import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from make_pairs import build_pairs  # noqa: E402


def test_build_pairs():
    # person 1: records 1,2,3 -> 3 dup pairs; person 2: records 4,5 -> 1; person 3: record 6
    rows = [{"record_id": r, "person_id": p} for r, p in
            [(1, 1), (2, 1), (3, 1), (4, 2), (5, 2), (6, 3)]]
    person = {r["record_id"]: r["person_id"] for r in rows}
    pairs = build_pairs(rows, seed=0)

    assert pairs == build_pairs(rows, seed=0)
    assert {(a, b) for a, b, d in pairs if d} == {(1, 2), (1, 3), (2, 3), (4, 5)}
    negs = [(a, b) for a, b, d in pairs if not d]
    assert len(negs) == 4 and len(set(negs)) == 4
    assert all(a < b and person[a] != person[b] for a, b in negs)
