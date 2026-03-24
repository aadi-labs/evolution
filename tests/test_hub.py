"""Tests for evolution.hub — attempts, notes, and skills."""
from __future__ import annotations

from pathlib import Path

import pytest

from evolution.hub.attempts import Attempt, AttemptsHub
from evolution.hub.notes import Note, NotesHub
from evolution.hub.skills import Skill, SkillsHub


# ── Attempts ─────────────────────────────────────────────────────────────


class TestAttemptsHub:
    def test_record_creates_file(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        a = hub.record("agent-a", 0.85, "first try", "abc123", "good job")
        assert a.id == 1
        assert a.agent == "agent-a"
        assert a.score == 0.85

        files = list((tmp_path / "attempts").glob("*.md"))
        assert len(files) == 1
        assert "001-agent-a-score-0.8500.md" == files[0].name

    def test_record_increments_id(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        a1 = hub.record("agent-a", 0.9, "first", "abc", "ok")
        a2 = hub.record("agent-b", 0.8, "second", "def", "better")
        assert a1.id == 1
        assert a2.id == 2

    def test_record_detects_improvement(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        a1 = hub.record("agent-a", 0.9, "first", "abc", "ok")
        assert a1.improvement is False

        a2 = hub.record("agent-a", 0.8, "second", "def", "better")
        assert a2.improvement is True
        assert a2.previous_best == 0.9

    def test_record_no_improvement_when_worse(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.5, "first", "abc", "ok")
        a2 = hub.record("agent-a", 0.7, "second", "def", "worse")
        assert a2.improvement is False
        assert a2.previous_best == 0.5

    def test_record_with_none_score(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        a = hub.record("agent-a", None, "crashed", "abc", "error")
        assert a.score is None
        assert "none" in list((tmp_path / "attempts").glob("*.md"))[0].name

    def test_record_with_metrics(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        metrics = {"accuracy": 0.95, "latency": 1.2}
        a = hub.record("agent-a", 0.85, "with metrics", "abc", "ok", metrics=metrics)
        assert a.metrics == metrics

        # Verify metrics roundtrip through file
        reloaded = hub.get(a.id)
        assert reloaded is not None
        assert reloaded.metrics["accuracy"] == pytest.approx(0.95)
        assert reloaded.metrics["latency"] == pytest.approx(1.2)

    def test_list_returns_sorted(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.9, "first", "abc", "ok")
        hub.record("agent-b", 0.8, "second", "def", "better")
        hub.record("agent-a", 0.7, "third", "ghi", "best")

        attempts = hub.list()
        assert len(attempts) == 3
        assert [a.id for a in attempts] == [1, 2, 3]

    def test_get_existing(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.9, "first", "abc", "ok")
        hub.record("agent-b", 0.8, "second", "def", "better")

        a = hub.get(2)
        assert a is not None
        assert a.agent == "agent-b"
        assert a.score == pytest.approx(0.8)

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        assert hub.get(999) is None

    def test_leaderboard_lower_is_better(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.9, "first", "abc", "ok")
        hub.record("agent-b", 0.7, "second", "def", "best")
        hub.record("agent-c", 0.8, "third", "ghi", "middle")

        board = hub.leaderboard(direction="lower_is_better")
        scores = [a.score for a in board]
        assert scores == [pytest.approx(0.7), pytest.approx(0.8), pytest.approx(0.9)]

    def test_leaderboard_higher_is_better(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.9, "first", "abc", "ok")
        hub.record("agent-b", 0.7, "second", "def", "worst")
        hub.record("agent-c", 0.8, "third", "ghi", "middle")

        board = hub.leaderboard(direction="higher_is_better")
        scores = [a.score for a in board]
        assert scores == [pytest.approx(0.9), pytest.approx(0.8), pytest.approx(0.7)]

    def test_best_lower_is_better(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.9, "first", "abc", "ok")
        hub.record("agent-b", 0.7, "second", "def", "best")

        b = hub.best(direction="lower_is_better")
        assert b is not None
        assert b.score == pytest.approx(0.7)

    def test_best_empty(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        assert hub.best() is None

    def test_markdown_body_roundtrip(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-a", 0.5, "my description", "sha1", "some feedback")

        a = hub.get(1)
        assert a is not None
        assert a.description == "my description"
        assert a.feedback == "some feedback"

    def test_creates_directory(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        hub = AttemptsHub(deep)
        assert deep.exists()

    def test_next_id_from_existing_files(self, tmp_path: Path) -> None:
        """A new hub instance picks up IDs from existing files."""
        hub1 = AttemptsHub(tmp_path / "attempts")
        hub1.record("agent-a", 0.9, "first", "abc", "ok")
        hub1.record("agent-b", 0.8, "second", "def", "ok")

        hub2 = AttemptsHub(tmp_path / "attempts")
        a3 = hub2.record("agent-c", 0.7, "third", "ghi", "ok")
        assert a3.id == 3


# ── Notes ────────────────────────────────────────────────────────────────


class TestNotesHub:
    def test_add_creates_file(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        n = hub.add("agent-a", "hello world", tags=["test"])
        assert n.agent == "agent-a"
        assert n.text == "hello world"
        assert n.tags == ["test"]

        files = list((tmp_path / "notes").glob("*.md"))
        assert len(files) == 1
        assert "001-agent-a.md" == files[0].name

    def test_add_multiple(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        hub.add("agent-a", "note 1")
        hub.add("agent-b", "note 2")

        files = sorted(f.name for f in (tmp_path / "notes").glob("*.md"))
        assert files == ["001-agent-a.md", "002-agent-b.md"]

    def test_list_all(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        hub.add("agent-a", "note 1", tags=["a"])
        hub.add("agent-b", "note 2", tags=["b"])
        hub.add("agent-a", "note 3")

        notes = hub.list()
        assert len(notes) == 3

    def test_list_filtered_by_agent(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        hub.add("agent-a", "note 1")
        hub.add("agent-b", "note 2")
        hub.add("agent-a", "note 3")

        notes_a = hub.list(agent="agent-a")
        assert len(notes_a) == 2
        assert all(n.agent == "agent-a" for n in notes_a)

        notes_b = hub.list(agent="agent-b")
        assert len(notes_b) == 1
        assert notes_b[0].text == "note 2"

    def test_list_filter_no_match(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        hub.add("agent-a", "hello")
        assert hub.list(agent="agent-x") == []

    def test_roundtrip_text(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        hub.add("agent-a", "multi\nline\ntext", tags=["x", "y"])

        notes = hub.list()
        assert len(notes) == 1
        assert notes[0].text == "multi\nline\ntext"
        assert notes[0].tags == ["x", "y"]

    def test_add_no_tags(self, tmp_path: Path) -> None:
        hub = NotesHub(tmp_path / "notes")
        n = hub.add("agent-a", "no tags")
        assert n.tags == []

    def test_creates_directory(self, tmp_path: Path) -> None:
        deep = tmp_path / "x" / "y"
        hub = NotesHub(deep)
        assert deep.exists()


# ── Skills ───────────────────────────────────────────────────────────────


class TestSkillsHub:
    def test_add_creates_file(self, tmp_path: Path) -> None:
        hub = SkillsHub(tmp_path / "skills")
        s = hub.add("agent-a", "retry-logic", "def retry(): pass", tags=["util"])
        assert s.author == "agent-a"
        assert s.name == "retry-logic"
        assert s.content == "def retry(): pass"
        assert s.tags == ["util"]

        files = list((tmp_path / "skills").glob("*.md"))
        assert len(files) == 1
        assert files[0].name == "retry-logic.md"

    def test_add_overwrites_same_name(self, tmp_path: Path) -> None:
        hub = SkillsHub(tmp_path / "skills")
        hub.add("agent-a", "skill-x", "v1")
        hub.add("agent-b", "skill-x", "v2")

        skills = hub.list()
        assert len(skills) == 1
        assert skills[0].content == "v2"
        assert skills[0].author == "agent-b"

    def test_list(self, tmp_path: Path) -> None:
        hub = SkillsHub(tmp_path / "skills")
        hub.add("agent-a", "alpha", "content a")
        hub.add("agent-b", "beta", "content b")

        skills = hub.list()
        assert len(skills) == 2
        names = [s.name for s in skills]
        assert "alpha" in names
        assert "beta" in names

    def test_roundtrip_content(self, tmp_path: Path) -> None:
        hub = SkillsHub(tmp_path / "skills")
        code = "def foo():\n    return 42\n\nclass Bar:\n    pass"
        hub.add("agent-a", "foo-bar", code, tags=["python"])

        skills = hub.list()
        assert len(skills) == 1
        assert skills[0].content == code
        assert skills[0].tags == ["python"]

    def test_add_no_tags(self, tmp_path: Path) -> None:
        hub = SkillsHub(tmp_path / "skills")
        s = hub.add("agent-a", "simple", "pass")
        assert s.tags == []

    def test_creates_directory(self, tmp_path: Path) -> None:
        deep = tmp_path / "p" / "q"
        hub = SkillsHub(deep)
        assert deep.exists()
