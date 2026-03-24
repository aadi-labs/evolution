from __future__ import annotations


def normalize_score(
    value: float, worst: float, best: float, direction: str
) -> float:
    """Normalize a score to 0-1 range where 1.0 = best.

    Parameters
    ----------
    value:
        The raw metric value.
    worst:
        The worst possible (or observed) value.
    best:
        The best possible (or observed) value.
    direction:
        ``"higher_is_better"`` or ``"lower_is_better"``.

    Returns
    -------
    float
        Normalized score in [0, 1].
    """
    if best == worst:
        return 1.0
    if direction == "higher_is_better":
        return (value - worst) / (best - worst)
    # lower_is_better
    return (worst - value) / (worst - best)


def weighted_sum(
    normalized_scores: dict[str, float], weights: dict[str, float]
) -> float:
    """Return the weighted sum of normalized metric scores."""
    return sum(normalized_scores[m] * weights[m] for m in normalized_scores)


def pareto_dominates(
    a: dict[str, float], b: dict[str, float], directions: dict[str, str]
) -> bool:
    """Return True if *a* strictly dominates *b* on **all** metrics."""
    for m, d in directions.items():
        if d == "higher_is_better":
            if a[m] <= b[m]:
                return False
        else:  # lower_is_better
            if a[m] >= b[m]:
                return False
    return True


def pareto_rank(
    attempts: list[dict[str, float]], directions: dict[str, str]
) -> list[int]:
    """Compute the Pareto rank of each attempt.

    Rank 0 = Pareto frontier (not dominated by anyone).
    Rank *k* = dominated by exactly *k* other attempts.
    """
    n = len(attempts)
    ranks = [0] * n
    for i in range(n):
        for j in range(n):
            if i != j and pareto_dominates(attempts[j], attempts[i], directions):
                ranks[i] += 1
    return ranks


def min_rank(
    attempts: list[dict[str, float]], directions: dict[str, str]
) -> list[int]:
    """For each attempt return the worst (highest) per-metric rank.

    Each metric is ranked independently (0 = best), then the maximum
    rank across metrics is reported for every attempt.
    """
    metrics = list(directions.keys())
    n = len(attempts)

    per_metric_ranks: dict[str, list[int]] = {}
    for m in metrics:
        values = [a[m] for a in attempts]
        reverse = directions[m] == "higher_is_better"
        sorted_vals = sorted(set(values), reverse=reverse)
        val_rank = {v: r for r, v in enumerate(sorted_vals)}
        per_metric_ranks[m] = [val_rank[v] for v in values]

    return [max(per_metric_ranks[m][i] for m in metrics) for i in range(n)]


def all_must_improve(
    new_scores: dict[str, float],
    current_best: dict[str, float],
    directions: dict[str, str],
) -> bool:
    """Return True only if *new_scores* improves **every** metric vs *current_best*."""
    for m, d in directions.items():
        if d == "higher_is_better":
            if new_scores[m] <= current_best[m]:
                return False
        else:  # lower_is_better
            if new_scores[m] >= current_best[m]:
                return False
    return True
