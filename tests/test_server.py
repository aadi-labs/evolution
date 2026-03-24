"""Tests for evolution.manager.server — Unix domain socket transport."""

import json
import os
import socket
import tempfile
import threading
import time

import pytest

from evolution.manager.server import ManagerServer, send_request


def _tmp_socket_path() -> str:
    """Return a unique path for a temporary Unix socket."""
    fd, path = tempfile.mkstemp(suffix=".sock")
    os.close(fd)
    os.unlink(path)  # socket will be created by the server
    return path


def _echo_handler(request: dict) -> dict:
    """Trivial handler that echoes the request back."""
    return {"echo": request}


# ---------- serve_one: accept one connection and echo ----------


def test_serve_one_echoes_request():
    path = _tmp_socket_path()
    server = ManagerServer(path)

    def run_server():
        server.serve_one(_echo_handler)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.1)

    # Client sends a request
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        payload = json.dumps({"cmd": "status"}).encode() + b"\n"
        sock.sendall(payload)

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        response = json.loads(data.split(b"\n", 1)[0])
        assert response == {"echo": {"cmd": "status"}}
    finally:
        sock.close()

    t.join(timeout=2)


# ---------- send_request round-trip ----------


def test_send_request_round_trip():
    path = _tmp_socket_path()
    server = ManagerServer(path)

    def run_server():
        server.serve_one(_echo_handler)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.1)

    result = send_request(path, {"action": "eval", "value": 42})
    assert result == {"echo": {"action": "eval", "value": 42}}

    t.join(timeout=2)


# ---------- shutdown cleans up socket file ----------


def test_shutdown_cleans_up_socket_file():
    path = _tmp_socket_path()
    server = ManagerServer(path)

    def run_server():
        server.serve_forever(_echo_handler)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.1)

    # Socket file should exist while the server is running.
    assert os.path.exists(path)

    server.shutdown()
    t.join(timeout=3)

    # After shutdown the socket file must be removed.
    assert not os.path.exists(path)


# ---------- malformed JSON ----------


def test_malformed_json_does_not_crash_server():
    path = _tmp_socket_path()
    server = ManagerServer(path)

    def run_server():
        server.serve_forever(_echo_handler)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.1)

    # Send garbage that is not valid JSON.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        sock.sendall(b"NOT-JSON!!!\n")

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        response = json.loads(data.split(b"\n", 1)[0])
        assert response == {"error": "malformed JSON"}
    finally:
        sock.close()

    # Server should still be alive — send a valid request.
    time.sleep(0.1)
    result = send_request(path, {"ping": True})
    assert result == {"echo": {"ping": True}}

    server.shutdown()
    t.join(timeout=3)
