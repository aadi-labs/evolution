"""Tests for evolution.cli.report — format_report and export_csv."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from evolution.hub.attempts import AttemptsHub
from evolution.cli.report import export_csv, format_report


# ── Helpers ──────────────────────────────────────────────────────────────


def _populated_hub(tmp_path: Path) -> AttemptsHub:
    """Create a hub with several attempts from multiple agents."""
    hub = AttemptsHub(tmp_path / "attempts")
    hub.record("agent-a", 0.9, "first try", "aaa111", "not great")
    hub.record("agent-b", 0.7, "good try", "bbb222", "nice")
    hub.record("agent-a", 0.6, "better try", "ccc333", "improved")
    hub.record("agent-c", 0.8, "decent", "ddd444", "ok")
    hub.record("agent-b", 0.5, "best yet", "eee555", "excellent")
    return hub


# ── format_report ────────────────────────────────────────────────────────


class TestFormatReport:
    def test_includes_header(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub)
        assert "EVOLUTION SESSION REPORT" in report

    def test_includes_total_count(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub)
        assert "Total attempts: 5" in report

    def test_includes_best_score(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub, direction="lower_is_better")
        assert "Best score: 0.5" in report

    def test_includes_agent_names(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub)
        assert "agent-a" in report
        assert "agent-b" in report
        assert "agent-c" in report

    def test_per_agent_counts(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub)
        assert "agent-a: 2 attempts" in report
        assert "agent-b: 2 attempts" in report
        assert "agent-c: 1 attempts" in report

    def test_leaderboard_present(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub)
        assert "Top 10 Leaderboard" in report
        # First place should be agent-b with 0.5 (lower is better)
        assert "1." in report

    def test_handles_empty_hub(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        report = format_report(hub)
        assert "EVOLUTION SESSION REPORT" in report
        assert "Total attempts: 0" in report
        assert "N/A" in report

    def test_higher_is_better_direction(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        report = format_report(hub, direction="higher_is_better")
        assert "Best score: 0.9" in report

    def test_handles_none_scores(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-x", None, "crashed", "fff666", "error")
        hub.record("agent-x", 0.5, "recovered", "ggg777", "ok")
        report = format_report(hub)
        assert "Total attempts: 2" in report
        assert "agent-x: 2 attempts" in report


# ── export_csv ───────────────────────────────────────────────────────────


class TestExportCsv:
    def test_creates_file(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        csv_path = str(tmp_path / "report.csv")
        export_csv(hub, csv_path)
        assert Path(csv_path).exists()

    def test_correct_columns(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        csv_path = str(tmp_path / "report.csv")
        export_csv(hub, csv_path)

        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["id", "agent", "score", "timestamp", "commit"]

    def test_contains_all_attempts(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        csv_path = str(tmp_path / "report.csv")
        export_csv(hub, csv_path)

        with open(csv_path) as f:
            reader = csv.reader(f)
            rows = list(reader)
        # header + 5 data rows
        assert len(rows) == 6

    def test_data_matches_attempts(self, tmp_path: Path) -> None:
        hub = _populated_hub(tmp_path)
        csv_path = str(tmp_path / "report.csv")
        export_csv(hub, csv_path)

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Verify first row
        assert rows[0]["id"] == "1"
        assert rows[0]["agent"] == "agent-a"
        assert rows[0]["score"] == "0.9"
        assert rows[0]["commit"] == "aaa111"

        # Verify last row
        assert rows[4]["id"] == "5"
        assert rows[4]["agent"] == "agent-b"
        assert rows[4]["score"] == "0.5"
        assert rows[4]["commit"] == "eee555"

    def test_empty_hub_produces_header_only(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        csv_path = str(tmp_path / "report.csv")
        export_csv(hub, csv_path)

        with open(csv_path) as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0] == ["id", "agent", "score", "timestamp", "commit"]

    def test_none_score_in_csv(self, tmp_path: Path) -> None:
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record("agent-x", None, "crashed", "abc", "error")
        csv_path = str(tmp_path / "report.csv")
        export_csv(hub, csv_path)

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["score"] == ""  # csv writes None as empty string
