import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark import N_QUERIES, pick_query_names  # noqa: E402
from generate_dataset import generate  # noqa: E402


def test_pick_query_names_fixed_and_present():
    rows = generate(size=210, seed=42)[:1000]          # the 1k benchmark dataset
    names = pick_query_names(rows)
    assert len(names) == N_QUERIES == len(set(names))  # 10 distinct names
    assert set(names) <= {r["full_name"] for r in rows}  # all present in the dataset
    assert names == pick_query_names(list(reversed(rows)))  # fixed seed, order-independent
    assert pick_query_names(rows[:3], k=10) == pick_query_names(rows[:3], k=10)
    assert len(pick_query_names(rows[:3], k=10)) == 3  # small dataset: as many as exist
