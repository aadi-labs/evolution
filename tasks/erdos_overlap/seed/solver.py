"""Naive baseline for the Erdos Minimum Overlap Problem.

The Erdos Minimum Overlap problem asks: given a function f: {1,...,2n} -> {0,1}
with exactly n ones, minimise the overlap constant
    C5 = max_{1 <= t <= n}  (1/n) * |{ i : f(i)=1 and f(i+t)=1 }|

This baseline uses a random but deterministic placement (seeded PRNG) to
produce a starting point.  Agents are expected to iterate toward the known
optimum of ~0.3808.
"""

import random


def compute_c5(n: int = 120) -> float:
    """Compute the overlap constant C5 using a seeded-random placement.

    Args:
        n: Half-length of the sequence (total length is 2n).

    Returns:
        The overlap constant C5 for the random placement.
    """
    length = 2 * n
    rng = random.Random(42)

    # Random placement: choose exactly n positions out of 2n
    positions = list(range(length))
    rng.shuffle(positions)
    ones_set = frozenset(positions[:n])

    max_overlap = 0.0
    for t in range(1, n + 1):
        count = sum(1 for pos in ones_set if (pos + t) in ones_set)
        overlap = count / n
        if overlap > max_overlap:
            max_overlap = overlap

    return round(max_overlap, 5)
