"""Post-session report formatting and CSV export."""
from __future__ import annotations

import csv
from collections import defaultdict

from evolution.hub.attempts import AttemptsHub


def format_report(hub: AttemptsHub, direction: str = "lower_is_better") -> str:
    """Format a human-readable session report.

    Returns a multi-line string with header, totals, per-agent breakdown,
    and a top-10 leaderboard.
    """
    attempts = hub.list()
    best = hub.best(direction)
    leaderboard = hub.leaderboard(direction)

    lines: list[str] = []

    # Header
    lines.append("=" * 60)
    lines.append("EVOLUTION SESSION REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Summary
    lines.append(f"Total attempts: {len(attempts)}")

    if best is not None:
        lines.append(f"Best score: {best.score} (agent: {best.agent})")
    else:
        lines.append("Best score: N/A (no scored attempts)")

    lines.append("")

    # Per-agent breakdown
    if attempts:
        lines.append("--- Per-Agent Breakdown ---")
        agent_attempts: dict[str, list[float]] = defaultdict(list)
        agent_counts: dict[str, int] = defaultdict(int)
        for a in attempts:
            agent_counts[a.agent] += 1
            if a.score is not None:
                agent_attempts[a.agent].append(a.score)

        is_lower_better = direction == "lower_is_better"
        for agent in sorted(agent_counts):
            count = agent_counts[agent]
            scores = agent_attempts[agent]
            if scores:
                best_score = min(scores) if is_lower_better else max(scores)
                lines.append(f"  {agent}: {count} attempts, best score: {best_score}")
            else:
                lines.append(f"  {agent}: {count} attempts, best score: N/A")

        lines.append("")

    # Top 10 leaderboard
    if leaderboard:
        lines.append("--- Top 10 Leaderboard ---")
        for rank, entry in enumerate(leaderboard[:10], start=1):
            lines.append(f"  {rank}. {entry.agent} — {entry.score} (attempt #{entry.id})")
        lines.append("")

    return "\n".join(lines)


def export_csv(hub: AttemptsHub, output_path: str) -> None:
    """Write all attempts to a CSV file.

    Columns: id, agent, score, timestamp, commit
    """
    attempts = hub.list()
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "agent", "score", "timestamp", "commit"])
        for a in attempts:
            writer.writerow([a.id, a.agent, a.score, a.timestamp, a.commit])
