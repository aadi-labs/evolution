"""``evolution init`` — bootstrap Evolution in any repository."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path


def cmd_init(args) -> None:
    """Generate evolution.yaml and optionally a grader wrapper in the current repo."""
    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"Error: {repo} is not a git repository")
        raise SystemExit(1)

    eval_cmd = args.eval
    name = args.name or repo.name
    direction = args.direction
    agents = args.agents or "claude-code"

    # Build grader script
    grader_path = repo / "evolution_grader.py"
    grader_path.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        \"\"\"Evolution grader — runs eval command and parses score from output.\"\"\"
        import subprocess
        import sys
        import re

        result = subprocess.run(
            {eval_cmd!r},
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
        )

        output = result.stdout + result.stderr

        # Try to find a numeric score in the output
        # Looks for patterns like "score: 0.85", "MCRMSE: 0.34", "85.2%", or just a standalone number
        patterns = [
            r"(?:score|accuracy|mcrmse|loss|metric|result)[:\\s=]+([\\d.]+)",
            r"(\\d+\\.\\d+)%",
            r"(\\d+)\\s+passed",
            r"^([\\d.]+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
            if match:
                print(match.group(1))
                sys.exit(0)

        # Fallback: use exit code (0 = 1.0, nonzero = 0.0)
        print("1.0" if result.returncode == 0 else "0.0")
    """))
    os.chmod(str(grader_path), 0o755)

    # Parse agent runtimes
    agent_runtimes = [a.strip() for a in agents.split(",")]

    agents_dict = {}
    for i, runtime in enumerate(agent_runtimes):
        agent_name = f"{runtime.replace('-', '_')}_agent_{i+1}"
        agent_entry = {"role": "researcher", "runtime": runtime}
        if runtime == "claude-code":
            agent_entry["skills"] = ["superpowers"]
        agents_dict[agent_name] = agent_entry

    dir_hint = "lower numbers are better" if direction == "lower_is_better" else "higher numbers are better"
    config_dict = {
        "session": {"name": name},
        "task": {
            "name": name,
            "path": ".",
            "description": f"Improve {name} against eval: {eval_cmd}",
            "grader": {"type": "script", "script": "./evolution_grader.py"},
            "metric": {"name": "score", "direction": direction},
            "seed": ".",
            "milestones": {"baseline": None, "target": None},
            "stop": {"max_time": "6h", "stagnation": "30m"},
        },
        "roles": {
            "researcher": {
                "prompt": (
                    f"You are a research agent working on improving this codebase.\n"
                    f"Your eval command: {eval_cmd}\n"
                    f"Direction: {direction} ({dir_hint})\n\n"
                    f"Approach:\n"
                    f"1. Read the codebase to understand the current implementation\n"
                    f"2. Run the eval to see the current score\n"
                    f"3. Make targeted changes to improve the score\n"
                    f"4. Submit with: evolution eval -m \"description\"\n"
                    f"5. Share insights with: evolution note add \"your finding\"\n"
                ),
                "heartbeat": {"on_attempts": 3, "on_time": "10m", "strategy": "first"},
            },
        },
        "agents": agents_dict,
        "superagent": {
            "enabled": True,
            "runtime": "claude-code",
            "remote_control": True,
            "prompt": f"You are the superagent for the {name} evolution session.\nEval command: {eval_cmd}\n",
        },
    }

    import yaml

    config_path = repo / "evolution.yaml"
    config_path.write_text(yaml.dump(config_dict, default_flow_style=False, sort_keys=False))

    print(f"Initialized Evolution in {repo}")
    print(f"  Config:  {config_path}")
    print(f"  Grader:  {grader_path}")
    print(f"  Eval:    {eval_cmd}")
    print(f"  Agents:  {', '.join(agent_runtimes)}")
    print()
    print("Next steps:")
    print("  1. Review evolution.yaml and evolution_grader.py")
    print("  2. Set milestones if you have baseline scores")
    print("  3. Run: evolution run")
