"""Implementation of the ``evolution run`` command."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path

from evolution.manager.config import load_config
from evolution.manager.manager import ADAPTERS, Manager

logger = logging.getLogger(__name__)


def cmd_run(args) -> None:
    """Start an Evolution session from the given CLI arguments.

    Steps:
    1. Load and validate the config file.
    2. Create the Manager and call ``setup()``.
    3. Start the socket server in a daemon thread.
    4. Spawn all agents via their runtime adapters.
    5. Enter the manager loop (check stop conditions, agent health, heartbeats).
    6. Handle Ctrl-C for graceful shutdown.
    """
    config = load_config(args.config)
    repo_root = Path(".").resolve()
    manager = Manager(config, repo_root)
    manager.setup()

    print(f"Evolution session '{config.session.name}' started")
    print(f"Socket: {manager.socket_path}")
    print(f"Agents: {', '.join(manager.agents.keys())}")

    # Start socket server in a background daemon thread
    server_thread = threading.Thread(
        target=manager.server.serve_forever,
        args=(manager.handle_request,),
        daemon=True,
    )
    server_thread.start()

    # Spawn all agents via their adapters
    for name, runtime in manager.agents.items():
        adapter_cls = ADAPTERS.get(runtime.agent_config.runtime)
        if adapter_cls and runtime.worktree_path:
            adapter = adapter_cls()
            try:
                process = adapter.spawn(runtime.worktree_path, runtime.agent_config)
                runtime.process = process
                print(f"  Spawned agent '{name}' (pid {process.pid})")
            except Exception as exc:
                logger.error("Failed to spawn agent %s: %s", name, exc)
                print(f"  Failed to spawn agent '{name}': {exc}", file=sys.stderr)

    # Install signal handler for graceful shutdown
    stop_event = threading.Event()

    def _signal_handler(signum, frame):
        print("\nShutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Manager loop
    try:
        while not stop_event.is_set():
            # Check stop conditions
            reason = manager.check_stop_conditions()
            if reason:
                print(f"Stopping: {reason}")
                break

            # Check agent health — restart only if explicitly enabled
            for name, runtime in list(manager.agents.items()):
                if runtime.is_dead():
                    restart_cfg = runtime.agent_config.restart
                    if restart_cfg.enabled and runtime.restart_count < restart_cfg.max_restarts:
                        adapter_cls = ADAPTERS.get(runtime.agent_config.runtime)
                        if adapter_cls and runtime.worktree_path:
                            adapter = adapter_cls()
                            try:
                                process = adapter.spawn(
                                    runtime.worktree_path, runtime.agent_config
                                )
                                runtime.process = process
                                runtime.restart_count += 1
                                logger.info(
                                    "Restarted agent %s (attempt %d/%d)",
                                    name,
                                    runtime.restart_count,
                                    restart_cfg.max_restarts,
                                )
                            except Exception as exc:
                                logger.error("Failed to restart agent %s: %s", name, exc)

                # Check heartbeats
                if runtime.heartbeat.should_fire():
                    runtime.heartbeat.reset()
                    logger.info("Heartbeat fired for agent %s", name)

            # Persist state
            manager.save_state()

            # Sleep between iterations
            stop_event.wait(timeout=5)

    finally:
        # Shutdown server
        manager.server.shutdown()

        # Terminate all agent processes
        for name, runtime in manager.agents.items():
            if runtime.process is not None:
                try:
                    runtime.process.terminate()
                    runtime.process.wait(timeout=5)
                except Exception:
                    try:
                        runtime.process.kill()
                    except Exception:
                        pass

        manager.save_state()
        print("Evolution session stopped.")
