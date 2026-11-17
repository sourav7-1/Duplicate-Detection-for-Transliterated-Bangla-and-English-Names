import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from generate_dataset import generate, name_key  # noqa: E402


def test_generate_dataset():
    rows = generate(size=200, seed=1)
    assert rows == generate(size=200, seed=1)          # reproducible
    assert rows != generate(size=200, seed=2)

    variants = Counter(r["person_id"] for r in rows
                       if r["variant_type"] not in ("original", "hard_negative"))
    assert len(variants) == 200
    assert all(3 <= n <= 8 for n in variants.values())
    assert sum(r["variant_type"] == "hard_negative" for r in rows) == 40   # 20%
    assert [r["record_id"] for r in rows] == list(range(1, len(rows) + 1))

    # clean labels: a normalized name never belongs to two different persons
    owners = {}
    for r in rows:
        assert owners.setdefault(name_key(r["full_name"]), r["person_id"]) == r["person_id"]
