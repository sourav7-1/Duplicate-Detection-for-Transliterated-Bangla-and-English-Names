"""Build labelled record pairs from data/names.csv -> data/gold_pairs.csv.

All duplicate pairs (same person_id) are kept, plus an equal number of random
non-duplicate pairs. record_id_a < record_id_b in every pair.

Usage: python src/make_pairs.py [--seed 42]
"""
import argparse
import csv
import random
from collections import defaultdict
from itertools import combinations
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def build_pairs(rows, seed=42):
    """rows: iterable of dicts with record_id, person_id. Returns [(a, b, is_dup), ...]."""
    by_person = defaultdict(list)
    for r in rows:
        by_person[int(r["person_id"])].append(int(r["record_id"]))

    dups = [(a, b) for ids in by_person.values() for a, b in combinations(sorted(ids), 2)]

    person_of = {rid: pid for pid, ids in by_person.items() for rid in ids}
    ids = sorted(person_of)
    n = len(ids)
    max_negs = n * (n - 1) // 2 - len(dups)
    if len(dups) > max_negs:
        raise ValueError(f"only {max_negs} non-duplicate pairs exist, need {len(dups)}")

    rng = random.Random(seed)
    negs = set()
    while len(negs) < len(dups):
        a, b = sorted(rng.sample(ids, 2))
        if person_of[a] != person_of[b]:
            negs.add((a, b))

    pairs = [(a, b, 1) for a, b in dups] + [(a, b, 0) for a, b in negs]
    pairs.sort()
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--names", type=Path, default=DATA / "names.csv")
    ap.add_argument("--out", type=Path, default=DATA / "gold_pairs.csv")
    args = ap.parse_args()

    with open(args.names, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    pairs = build_pairs(rows, args.seed)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["record_id_a", "record_id_b", "is_duplicate"])
        w.writerows(pairs)

    n_dup = sum(p[2] for p in pairs)
    print(f"total records:       {len(rows)}")
    print(f"persons:             {len({r['person_id'] for r in rows})}")
    print(f"duplicate pairs:     {n_dup}")
    print(f"non-duplicate pairs: {len(pairs) - n_dup}")
    print(f"wrote {len(pairs)} pairs -> {args.out}")


if __name__ == "__main__":
    main()
