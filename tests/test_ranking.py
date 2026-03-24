from __future__ import annotations

import pytest

from evolution.grader.ranking import (
    all_must_improve,
    min_rank,
    normalize_score,
    pareto_dominates,
    pareto_rank,
    weighted_sum,
)


# ---------------------------------------------------------------------------
# Tests — normalize_score
# ---------------------------------------------------------------------------


class TestNormalizeScore:
    def test_higher_is_better(self):
        # 75 in [50, 100] -> 0.5
        assert normalize_score(75, worst=50, best=100, direction="higher_is_better") == pytest.approx(0.5)

    def test_lower_is_better(self):
        # 0.38 in [0.40, 0.35] -> 0.4
        assert normalize_score(0.38, worst=0.40, best=0.35, direction="lower_is_better") == pytest.approx(0.4)

    def test_edge_case_same_values(self):
        assert normalize_score(42, worst=42, best=42, direction="higher_is_better") == 1.0
        assert normalize_score(42, worst=42, best=42, direction="lower_is_better") == 1.0


# ---------------------------------------------------------------------------
# Tests — weighted_sum
# ---------------------------------------------------------------------------


class TestWeightedSum:
    def test_basic_calculation(self):
        scores = {"accuracy": 0.8, "speed": 0.6}
        weights = {"accuracy": 0.7, "speed": 0.3}
        # 0.8*0.7 + 0.6*0.3 = 0.56 + 0.18 = 0.74
        assert weighted_sum(scores, weights) == pytest.approx(0.74)


# ---------------------------------------------------------------------------
# Tests — pareto_dominates
# ---------------------------------------------------------------------------


class TestParetoDominates:
    def test_a_dominates_b(self):
        directions = {"accuracy": "higher_is_better", "loss": "lower_is_better"}
        a = {"accuracy": 0.9, "loss": 0.1}
        b = {"accuracy": 0.7, "loss": 0.3}
        assert pareto_dominates(a, b, directions) is True
        assert pareto_dominates(b, a, directions) is False

    def test_no_dominance_when_tradeoff(self):
        directions = {"accuracy": "higher_is_better", "loss": "lower_is_better"}
        a = {"accuracy": 0.9, "loss": 0.3}
        b = {"accuracy": 0.7, "loss": 0.1}
        assert pareto_dominates(a, b, directions) is False
        assert pareto_dominates(b, a, directions) is False


# ---------------------------------------------------------------------------
# Tests — pareto_rank
# ---------------------------------------------------------------------------


class TestParetoRank:
    def test_frontier_identification(self):
        directions = {"accuracy": "higher_is_better", "loss": "lower_is_better"}
        attempts = [
            {"accuracy": 0.9, "loss": 0.3},  # frontier (trade-off with idx 1)
            {"accuracy": 0.7, "loss": 0.1},  # frontier (trade-off with idx 0)
            {"accuracy": 0.6, "loss": 0.4},  # dominated by both 0 and 1
        ]
        ranks = pareto_rank(attempts, directions)
        assert ranks[0] == 0  # frontier
        assert ranks[1] == 0  # frontier
        assert ranks[2] == 2  # dominated by 2 attempts


# ---------------------------------------------------------------------------
# Tests — min_rank
# ---------------------------------------------------------------------------


class TestMinRank:
    def test_worst_per_metric_rank(self):
        directions = {"accuracy": "higher_is_better", "speed": "higher_is_better"}
        attempts = [
            {"accuracy": 0.9, "speed": 0.3},  # acc rank 0, speed rank 2 -> worst 2
            {"accuracy": 0.7, "speed": 0.8},  # acc rank 1, speed rank 0 -> worst 1
            {"accuracy": 0.5, "speed": 0.5},  # acc rank 2, speed rank 1 -> worst 2
        ]
        ranks = min_rank(attempts, directions)
        assert ranks == [2, 1, 2]


# ---------------------------------------------------------------------------
# Tests — all_must_improve
# ---------------------------------------------------------------------------


class TestAllMustImprove:
    def test_accepts_when_all_improve(self):
        directions = {"accuracy": "higher_is_better", "loss": "lower_is_better"}
        current = {"accuracy": 0.7, "loss": 0.3}
        new = {"accuracy": 0.8, "loss": 0.2}
        assert all_must_improve(new, current, directions) is True

    def test_rejects_when_any_regresses(self):
        directions = {"accuracy": "higher_is_better", "loss": "lower_is_better"}
        current = {"accuracy": 0.7, "loss": 0.3}
        new = {"accuracy": 0.8, "loss": 0.4}  # loss got worse
        assert all_must_improve(new, current, directions) is False
