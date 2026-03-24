"""Unix domain socket server for manager <-> agent CLI communication."""

from __future__ import annotations

import json
import os
import socket
from typing import Callable


class ManagerServer:
    """Accepts newline-delimited JSON requests over a Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._sock: socket.socket | None = None
        self._running = False

    # -- public API ----------------------------------------------------------

    def serve_one(self, handler: Callable[[dict], dict]) -> None:
        """Bind, accept exactly one connection, handle it, then return."""
        self._bind()
        try:
            conn, _ = self._sock.accept()
            self._handle_connection(conn, handler)
        finally:
            self._close_socket()

    def serve_forever(self, handler: Callable[[dict], dict]) -> None:
        """Bind and accept connections in a loop until *shutdown* is called."""
        self._running = True
        self._bind()
        self._sock.settimeout(1.0)
        try:
            while self._running:
                try:
                    conn, _ = self._sock.accept()
                except socket.timeout:
                    continue
                self._handle_connection(conn, handler)
        finally:
            self._close_socket()

    def shutdown(self) -> None:
        """Signal the serve loop to stop and clean up resources."""
        self._running = False
        self._close_socket()

    # -- internals -----------------------------------------------------------

    def _bind(self) -> None:
        """Create an AF_UNIX socket, remove stale file, bind, and listen."""
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._socket_path)
        self._sock.listen(5)

    def _handle_connection(
        self,
        conn: socket.socket,
        handler: Callable[[dict], dict],
    ) -> None:
        """Read one JSON request, invoke *handler*, send JSON response."""
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            line = data.split(b"\n", 1)[0]
            if not line:
                return

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = {"error": "malformed JSON"}
                conn.sendall(json.dumps(response).encode() + b"\n")
                return

            response = handler(request)
            conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception:
            # Never let a single connection take down the server.
            pass
        finally:
            conn.close()

    def _close_socket(self) -> None:
        """Close the socket and remove the socket file if they exist."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass


# -- client helper -----------------------------------------------------------


def send_request(socket_path: str, request: dict) -> dict:
    """Send a JSON request to a ManagerServer and return the parsed response.

    Parameters
    ----------
    socket_path:
        Path to the Unix domain socket.
    request:
        Arbitrary dict that will be serialised as JSON.

    Returns
    -------
    dict
        The parsed JSON response from the server.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(socket_path)
        sock.sendall(json.dumps(request).encode() + b"\n")

        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        line = data.split(b"\n", 1)[0]
        return json.loads(line)
    finally:
        sock.close()
