"""Tests for evolution.cli.main — argument parsing only."""

from __future__ import annotations

import pytest

from evolution.cli.main import build_parser


@pytest.fixture
def parser():
    return build_parser()


# =========================================================================
# run
# =========================================================================


class TestRunCommand:
    def test_run_defaults(self, parser):
        args = parser.parse_args(["run"])
        assert args.command == "run"
        assert args.config == "evolution.yaml"
        assert args.resume is False

    def test_run_with_config(self, parser):
        args = parser.parse_args(["run", "--config", "custom.yaml"])
        assert args.config == "custom.yaml"

    def test_run_with_resume(self, parser):
        args = parser.parse_args(["run", "--resume"])
        assert args.resume is True

    def test_run_with_config_and_resume(self, parser):
        args = parser.parse_args(["run", "--config", "my.yaml", "--resume"])
        assert args.config == "my.yaml"
        assert args.resume is True


# =========================================================================
# eval
# =========================================================================


class TestEvalCommand:
    def test_eval_with_message(self, parser):
        args = parser.parse_args(["eval", "-m", "my submission"])
        assert args.command == "eval"
        assert args.m == "my submission"

    def test_eval_requires_m(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["eval"])


# =========================================================================
# note add
# =========================================================================


class TestNoteCommand:
    def test_note_add(self, parser):
        args = parser.parse_args(["note", "add", "some insight"])
        assert args.command == "note"
        assert args.note_command == "add"
        assert args.text == "some insight"
        assert args.tags == ""

    def test_note_add_with_tags(self, parser):
        args = parser.parse_args(["note", "add", "found a bug", "--tags", "bug,important"])
        assert args.text == "found a bug"
        assert args.tags == "bug,important"


# =========================================================================
# notes list
# =========================================================================


class TestNotesCommand:
    def test_notes_list(self, parser):
        args = parser.parse_args(["notes", "list"])
        assert args.command == "notes"
        assert args.notes_command == "list"
        assert args.agent is None

    def test_notes_list_with_agent(self, parser):
        args = parser.parse_args(["notes", "list", "--agent", "alpha"])
        assert args.agent == "alpha"


# =========================================================================
# skill / skills
# =========================================================================


class TestSkillCommand:
    def test_skill_add(self, parser):
        args = parser.parse_args(["skill", "add", "my_skill.py"])
        assert args.command == "skill"
        assert args.skill_command == "add"
        assert args.file == "my_skill.py"

    def test_skills_list(self, parser):
        args = parser.parse_args(["skills", "list"])
        assert args.command == "skills"
        assert args.skills_command == "list"


# =========================================================================
# status
# =========================================================================


class TestStatusCommand:
    def test_status_no_args(self, parser):
        args = parser.parse_args(["status"])
        assert args.command == "status"
        assert args.agent is None

    def test_status_with_agent(self, parser):
        args = parser.parse_args(["status", "--agent", "alpha"])
        assert args.agent == "alpha"


# =========================================================================
# attempts
# =========================================================================


class TestAttemptsCommand:
    def test_attempts_list(self, parser):
        args = parser.parse_args(["attempts", "list"])
        assert args.command == "attempts"
        assert args.attempts_command == "list"

    def test_attempts_show(self, parser):
        args = parser.parse_args(["attempts", "show", "42"])
        assert args.command == "attempts"
        assert args.attempts_command == "show"
        assert args.id == 42

    def test_attempts_show_requires_id(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["attempts", "show"])


# =========================================================================
# msg
# =========================================================================


class TestMsgCommand:
    def test_msg_target_and_message(self, parser):
        args = parser.parse_args(["msg", "alpha", "try approach X"])
        assert args.command == "msg"
        assert args.target == "alpha"
        assert args.message == "try approach X"
        assert args.all_agents is False
        assert args.role is None

    def test_msg_all(self, parser):
        args = parser.parse_args(["msg", "--all", "attention everyone"])
        assert args.command == "msg"
        assert args.all_agents is True
        # With --all, "attention everyone" lands in target (first positional)
        assert args.target == "attention everyone"

    def test_msg_with_role(self, parser):
        args = parser.parse_args(["msg", "--role", "explorer", "try something new"])
        assert args.command == "msg"
        assert args.role == "explorer"
        assert args.target == "try something new"


# =========================================================================
# pause / resume / kill
# =========================================================================


class TestAgentLifecycleCommands:
    def test_pause(self, parser):
        args = parser.parse_args(["pause", "alpha"])
        assert args.command == "pause"
        assert args.agent == "alpha"

    def test_resume(self, parser):
        args = parser.parse_args(["resume", "alpha"])
        assert args.command == "resume"
        assert args.agent == "alpha"

    def test_kill(self, parser):
        args = parser.parse_args(["kill", "alpha"])
        assert args.command == "kill"
        assert args.agent == "alpha"


# =========================================================================
# spawn
# =========================================================================


class TestSpawnCommand:
    def test_spawn_defaults(self, parser):
        args = parser.parse_args(["spawn"])
        assert args.command == "spawn"
        assert args.clone is None
        assert args.role is None
        assert args.runtime == "claude-code"

    def test_spawn_with_clone(self, parser):
        args = parser.parse_args(["spawn", "--clone", "alpha"])
        assert args.clone == "alpha"

    def test_spawn_with_role_and_runtime(self, parser):
        args = parser.parse_args(["spawn", "--role", "explorer", "--runtime", "codex"])
        assert args.role == "explorer"
        assert args.runtime == "codex"


# =========================================================================
# stop
# =========================================================================


class TestStopCommand:
    def test_stop(self, parser):
        args = parser.parse_args(["stop"])
        assert args.command == "stop"


# =========================================================================
# report / export / timeline
# =========================================================================


class TestReportCommands:
    def test_report(self, parser):
        args = parser.parse_args(["report"])
        assert args.command == "report"

    def test_export_defaults(self, parser):
        args = parser.parse_args(["export"])
        assert args.command == "export"
        assert args.fmt == "json"

    def test_export_with_format(self, parser):
        args = parser.parse_args(["export", "--format", "csv"])
        assert args.fmt == "csv"

    def test_timeline(self, parser):
        args = parser.parse_args(["timeline"])
        assert args.command == "timeline"


# =========================================================================
# benchmark
# =========================================================================


class TestBenchmarkCommand:
    def test_benchmark_defaults(self, parser):
        args = parser.parse_args(["benchmark"])
        assert args.command == "benchmark"
        assert args.run_all is False
        assert args.compare is None

    def test_benchmark_all(self, parser):
        args = parser.parse_args(["benchmark", "--all"])
        assert args.run_all is True

    def test_benchmark_compare(self, parser):
        args = parser.parse_args(["benchmark", "--compare", "baseline-run"])
        assert args.compare == "baseline-run"


# =========================================================================
# No command
# =========================================================================


class TestNoCommand:
    def test_no_command_returns_none(self, parser):
        args = parser.parse_args([])
        assert args.command is None
