from pathlib import Path
from evolution.hub.hypotheses import HypothesisHub


class TestHypothesisHub:
    def test_add_and_list(self, tmp_path: Path):
        hub = HypothesisHub(tmp_path)
        h = hub.add(agent="agent-1", hypothesis="BM25 > 0.5 hurts TR", metric="tr_score")
        assert h.id == "H-1"
        assert h.status == "open"
        assert h.hypothesis == "BM25 > 0.5 hurts TR"
        all_h = hub.list()
        assert len(all_h) == 1

    def test_sequential_ids(self, tmp_path: Path):
        hub = HypothesisHub(tmp_path)
        h1 = hub.add(agent="a", hypothesis="h1", metric="s")
        h2 = hub.add(agent="b", hypothesis="h2", metric="s")
        assert h1.id == "H-1"
        assert h2.id == "H-2"

    def test_resolve_validated(self, tmp_path: Path):
        hub = HypothesisHub(tmp_path)
        hub.add(agent="agent-1", hypothesis="test", metric="score")
        hub.resolve("H-1", status="validated", resolved_by="agent-2", evidence="Attempt #5 confirmed")
        h = hub.get("H-1")
        assert h.status == "validated"
        assert h.resolved_by == "agent-2"
        assert h.evidence == "Attempt #5 confirmed"

    def test_resolve_invalidated(self, tmp_path: Path):
        hub = HypothesisHub(tmp_path)
        hub.add(agent="agent-1", hypothesis="test", metric="score")
        hub.resolve("H-1", status="invalidated", resolved_by="agent-3", evidence="No change")
        h = hub.get("H-1")
        assert h.status == "invalidated"

    def test_list_filter_by_status(self, tmp_path: Path):
        hub = HypothesisHub(tmp_path)
        hub.add(agent="a", hypothesis="h1", metric="s")
        hub.add(agent="b", hypothesis="h2", metric="s")
        hub.resolve("H-1", status="validated", resolved_by="a", evidence="yes")
        open_h = hub.list(status="open")
        assert len(open_h) == 1
        assert open_h[0].id == "H-2"

    def test_get_nonexistent(self, tmp_path: Path):
        hub = HypothesisHub(tmp_path)
        assert hub.get("H-99") is None
