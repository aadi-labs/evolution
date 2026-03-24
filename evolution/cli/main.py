"""CLI entry-point for the Evolution multi-agent research platform."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _detect_agent_name() -> str | None:
    """Detect the current agent name from cwd.

    If the cwd contains ``.evolution/worktrees/``, the next path component
    is assumed to be the agent name.
    """
    cwd = os.getcwd()
    marker = os.sep + ".evolution" + os.sep + "worktrees" + os.sep
    idx = cwd.find(marker)
    if idx == -1:
        return None
    rest = cwd[idx + len(marker):]
    # Agent name is the first path component after the marker
    return rest.split(os.sep)[0] if rest else None


def _resolve_socket_path() -> str:
    """Find the manager socket by locating the git repo root.

    1. Run ``git rev-parse --show-toplevel`` to find the repo root.
    2. Build the path ``<repo_root>/.evolution/manager.sock``.
    3. If the resulting path exceeds 100 characters, hash it and use a
       ``/tmp/evolution-<hash>.sock`` fallback (matching Manager behaviour).
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Error: not inside a git repository", file=sys.stderr)
        sys.exit(1)

    repo_root = result.stdout.strip()
    socket_path = os.path.join(repo_root, ".evolution", "manager.sock")

    if len(socket_path) > 100:
        short_hash = hashlib.md5(socket_path.encode()).hexdigest()[:12]
        socket_path = f"/tmp/evolution-{short_hash}.sock"

    return socket_path


def _send_and_print(socket_path: str, request: dict) -> None:
    """Send a request to the manager and pretty-print the response."""
    from evolution.manager.server import send_request

    try:
        response = send_request(socket_path, request)
    except (ConnectionRefusedError, FileNotFoundError):
        print("Error: cannot connect to evolution manager — is it running?", file=sys.stderr)
        sys.exit(1)

    if "error" in response:
        print(f"Error: {response['error']}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(response, indent=2))


def build_parser() -> argparse.ArgumentParser:
    """Construct the full argparse parser for the ``evolution`` CLI."""
    parser = argparse.ArgumentParser(
        prog="evolution",
        description="Evolution multi-agent research platform",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- init --------------------------------------------------------------
    p_init = subparsers.add_parser("init", help="Bootstrap Evolution in a repo")
    p_init.add_argument("repo", nargs="?", default=".", help="Path to the repository (default: current dir)")
    p_init.add_argument("--eval", required=True, help="Eval command (e.g. 'pytest tests/' or './run_eval.sh')")
    p_init.add_argument("--name", default=None, help="Session name (default: repo directory name)")
    p_init.add_argument("--direction", default="higher_is_better",
                        choices=["higher_is_better", "lower_is_better"],
                        help="Score direction (default: higher_is_better)")
    p_init.add_argument("--agents", default="claude-code",
                        help="Comma-separated runtimes (default: claude-code)")

    # -- run ---------------------------------------------------------------
    p_run = subparsers.add_parser("run", help="Start an evolution session")
    p_run.add_argument("--config", default="evolution.yaml", help="Config file path")
    p_run.add_argument("--resume", action="store_true", help="Resume a previous session")

    # -- eval --------------------------------------------------------------
    p_eval = subparsers.add_parser("eval", help="Submit work for evaluation")
    p_eval.add_argument("-m", required=True, help="Description of the submission")

    # -- note (with sub-subcommands) ---------------------------------------
    p_note = subparsers.add_parser("note", help="Manage notes")
    note_sub = p_note.add_subparsers(dest="note_command")

    p_note_add = note_sub.add_parser("add", help="Add a note")
    p_note_add.add_argument("text", help="Note text")
    p_note_add.add_argument("--tags", default="", help="Comma-separated tags")

    # -- notes (list) ------------------------------------------------------
    p_notes = subparsers.add_parser("notes", help="View notes")
    notes_sub = p_notes.add_subparsers(dest="notes_command")

    p_notes_list = notes_sub.add_parser("list", help="List notes")
    p_notes_list.add_argument("--agent", default=None, help="Filter by agent name")

    # -- skill (add) -------------------------------------------------------
    p_skill = subparsers.add_parser("skill", help="Manage skills")
    skill_sub = p_skill.add_subparsers(dest="skill_command")

    p_skill_add = skill_sub.add_parser("add", help="Publish a skill")
    p_skill_add.add_argument("file", help="Path to the skill file")

    # -- skills (list) -----------------------------------------------------
    p_skills = subparsers.add_parser("skills", help="View skills")
    skills_sub = p_skills.add_subparsers(dest="skills_command")

    skills_sub.add_parser("list", help="List all skills")

    # -- status ------------------------------------------------------------
    p_status = subparsers.add_parser("status", help="Show system status")
    p_status.add_argument("--agent", default=None, help="Filter by agent name")

    # -- attempts ----------------------------------------------------------
    p_attempts = subparsers.add_parser("attempts", help="View attempts")
    attempts_sub = p_attempts.add_subparsers(dest="attempts_command")

    attempts_sub.add_parser("list", help="Show leaderboard")

    p_attempts_show = attempts_sub.add_parser("show", help="Show attempt detail")
    p_attempts_show.add_argument("id", type=int, help="Attempt ID")

    # -- msg ---------------------------------------------------------------
    p_msg = subparsers.add_parser("msg", help="Send a message")
    p_msg.add_argument("target", nargs="?", default=None, help="Target agent name")
    p_msg.add_argument("message", nargs="?", default=None, help="Message text")
    p_msg.add_argument("--all", action="store_true", dest="all_agents", help="Send to all agents")
    p_msg.add_argument("--role", default=None, help="Send to agents with this role")

    # -- pause / resume / kill ---------------------------------------------
    p_pause = subparsers.add_parser("pause", help="Pause an agent")
    p_pause.add_argument("agent", help="Agent name")

    p_resume = subparsers.add_parser("resume", help="Resume an agent")
    p_resume.add_argument("agent", help="Agent name")

    p_kill = subparsers.add_parser("kill", help="Kill an agent")
    p_kill.add_argument("agent", help="Agent name")

    # -- spawn -------------------------------------------------------------
    p_spawn = subparsers.add_parser("spawn", help="Spawn a new agent")
    p_spawn.add_argument("--clone", default=None, help="Clone from existing agent")
    p_spawn.add_argument("--role", default=None, help="Role for the new agent")
    p_spawn.add_argument("--runtime", default="claude-code", help="Runtime to use")

    # -- stop --------------------------------------------------------------
    subparsers.add_parser("stop", help="Stop the evolution session")

    # -- report / export / timeline ----------------------------------------
    subparsers.add_parser("report", help="Generate a session report")

    p_export = subparsers.add_parser("export", help="Export session data")
    p_export.add_argument("--format", default="json", dest="fmt", help="Export format")

    subparsers.add_parser("timeline", help="Show session timeline")

    # -- benchmark ---------------------------------------------------------
    p_benchmark = subparsers.add_parser("benchmark", help="Run benchmarks")
    p_benchmark.add_argument("--all", action="store_true", dest="run_all", help="Run all benchmarks")
    p_benchmark.add_argument("--compare", default=None, help="Compare against a named run")

    return parser


def main() -> None:
    """Parse arguments, resolve socket, and dispatch commands."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # -- init: bootstrap evolution in a repo --------------------------------
    if args.command == "init":
        from evolution.cli.init import cmd_init

        cmd_init(args)
        return

    # -- run is special: starts the manager locally -----------------------
    if args.command == "run":
        from evolution.cli.run import cmd_run

        cmd_run(args)
        return

    # -- all other commands talk to a running manager via socket ----------
    socket_path = _resolve_socket_path()

    if args.command == "eval":
        agent = _detect_agent_name()
        request = {"type": "eval", "agent": agent or "", "description": args.m}
        _send_and_print(socket_path, request)

    elif args.command == "note":
        if getattr(args, "note_command", None) == "add":
            agent = _detect_agent_name()
            tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
            request = {"type": "note", "agent": agent or "", "text": args.text, "tags": tags}
            _send_and_print(socket_path, request)
        else:
            parser.parse_args(["note", "--help"])

    elif args.command == "notes":
        if getattr(args, "notes_command", None) == "list":
            request: dict = {"type": "notes_list"}
            if args.agent:
                request["agent"] = args.agent
            _send_and_print(socket_path, request)
        else:
            parser.parse_args(["notes", "--help"])

    elif args.command == "skill":
        if getattr(args, "skill_command", None) == "add":
            agent = _detect_agent_name()
            file_path = Path(args.file)
            if not file_path.exists():
                print(f"Error: file not found: {args.file}", file=sys.stderr)
                sys.exit(1)
            content = file_path.read_text()
            request = {
                "type": "skill",
                "author": agent or "",
                "name": file_path.stem,
                "content": content,
                "tags": [],
            }
            _send_and_print(socket_path, request)
        else:
            parser.parse_args(["skill", "--help"])

    elif args.command == "skills":
        if getattr(args, "skills_command", None) == "list":
            _send_and_print(socket_path, {"type": "skills_list"})
        else:
            parser.parse_args(["skills", "--help"])

    elif args.command == "status":
        request = {"type": "status"}
        if args.agent:
            request["agent"] = args.agent
        _send_and_print(socket_path, request)

    elif args.command == "attempts":
        if getattr(args, "attempts_command", None) == "list":
            _send_and_print(socket_path, {"type": "attempts_list"})
        elif getattr(args, "attempts_command", None) == "show":
            _send_and_print(socket_path, {"type": "attempts_show", "id": args.id})
        else:
            parser.parse_args(["attempts", "--help"])

    elif args.command == "msg":
        if args.all_agents:
            target = "all"
            # When --all, message is the first positional (target slot)
            message = args.target
            if args.message:
                message = (message + " " + args.message) if message else args.message
        elif args.role:
            target = args.role
            message = args.target
            if args.message:
                message = (message + " " + args.message) if message else args.message
        else:
            target = args.target or ""
            message = args.message or ""

        agent = _detect_agent_name()
        request = {
            "type": "msg",
            "from": agent or "manager",
            "target": target,
            "message": message or "",
        }
        _send_and_print(socket_path, request)

    elif args.command == "pause":
        _send_and_print(socket_path, {"type": "pause", "agent": args.agent})

    elif args.command == "resume":
        _send_and_print(socket_path, {"type": "resume", "agent": args.agent})

    elif args.command == "kill":
        _send_and_print(socket_path, {"type": "kill", "agent": args.agent})

    elif args.command == "spawn":
        request = {"type": "spawn", "name": f"agent-{os.getpid()}"}
        if args.clone:
            request["clone_from"] = args.clone
        if args.role:
            request["role"] = args.role
        request["runtime"] = args.runtime
        _send_and_print(socket_path, request)

    elif args.command == "stop":
        _send_and_print(socket_path, {"type": "stop"})

    elif args.command == "report":
        _send_and_print(socket_path, {"type": "status"})

    elif args.command == "export":
        request = {"type": "attempts_list"}
        _send_and_print(socket_path, request)

    elif args.command == "timeline":
        _send_and_print(socket_path, {"type": "attempts_list"})

    elif args.command == "benchmark":
        request: dict = {"type": "status"}
        _send_and_print(socket_path, request)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
