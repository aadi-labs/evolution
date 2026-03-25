import time
from evolution.manager.eval_queue import EvalQueue


class TestEvalQueueSubmit:
    def test_submit_returns_position(self):
        q = EvalQueue(max_queued=8, fairness="fifo", rate_limit_seconds=0)
        result = q.submit("agent-1", "first change")
        assert result["status"] == "queued"
        assert result["position"] == 1

    def test_submit_backpressure(self):
        q = EvalQueue(max_queued=2, fairness="fifo", rate_limit_seconds=0)
        q.submit("agent-1", "a")
        q.submit("agent-2", "b")
        result = q.submit("agent-3", "c")
        assert result["status"] == "rejected"
        assert "full" in result["reason"]

    def test_submit_rate_limit(self):
        q = EvalQueue(max_queued=8, fairness="fifo", rate_limit_seconds=300)
        q.submit("agent-1", "a")
        q.get()  # drain so it's not backpressure
        result = q.submit("agent-1", "b")
        assert result["status"] == "rejected"
        assert "Rate limited" in result["reason"]

    def test_rate_limit_different_agent_ok(self):
        q = EvalQueue(max_queued=8, fairness="fifo", rate_limit_seconds=300)
        q.submit("agent-1", "a")
        result = q.submit("agent-2", "b")
        assert result["status"] == "queued"


class TestEvalQueueFairness:
    def test_fifo_ordering(self):
        q = EvalQueue(max_queued=8, fairness="fifo", rate_limit_seconds=0)
        q.submit("agent-1", "a")
        q.submit("agent-1", "b")
        q.submit("agent-2", "c")
        assert q.get()["agent"] == "agent-1"
        assert q.get()["agent"] == "agent-1"
        assert q.get()["agent"] == "agent-2"

    def test_round_robin_ordering(self):
        q = EvalQueue(max_queued=8, fairness="round_robin", rate_limit_seconds=0)
        q.submit("agent-1", "a")
        q.submit("agent-1", "b")
        q.submit("agent-2", "c")
        first = q.get()
        second = q.get()
        assert first["agent"] == "agent-1"
        assert second["agent"] == "agent-2"

    def test_priority_boost(self):
        q = EvalQueue(max_queued=8, fairness="priority", rate_limit_seconds=0)
        q.submit("agent-1", "a")
        q.submit("agent-2", "b")
        q.mark_improving("agent-2")
        first = q.get()
        assert first["agent"] == "agent-2"


class TestEvalQueueEmpty:
    def test_get_empty_returns_none(self):
        q = EvalQueue(max_queued=8, fairness="fifo", rate_limit_seconds=0)
        assert q.get() is None

    def test_pending_count(self):
        q = EvalQueue(max_queued=8, fairness="fifo", rate_limit_seconds=0)
        assert q.pending_count == 0
        q.submit("agent-1", "a")
        assert q.pending_count == 1
        q.get()
        assert q.pending_count == 0
