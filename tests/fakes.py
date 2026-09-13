"""Test doubles for the Sway IPC protocol.

``FakeSway`` speaks the real i3-ipc framing over a Unix socket so producer code
is exercised without a compositor. Scripted replies are per message type.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from typing import Any, Callable, Iterable, Optional

from hermes_sway_plugin import ipc


class FakeSway:
    """A scripted Sway 1.9 IPC endpoint bound to a real Unix socket."""

    def __init__(
        self,
        socket_path: str,
        replies: Optional[dict[int, Any]] = None,
        commands: Optional[list[dict]] = None,
        corrupt: Optional[Callable[[int], bytes]] = None,
        events: Optional[list[tuple[int, dict]]] = None,
        subscribe_reply: Optional[dict] = None,
        reply_type: Optional[int] = None,
        send_all: bool = True,
    ) -> None:
        self.socket_path = socket_path
        self.replies = dict(replies or {})
        self.commands = list(commands or [])
        self.corrupt = corrupt
        self.events = list(events or [])
        self.subscribe_reply = subscribe_reply if subscribe_reply is not None else {"success": True}
        self.reply_type = reply_type
        self.send_all = send_all
        self.requests: list[tuple[int, str]] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(socket_path)
        self._server.listen(8)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _read_frame(self, conn: socket.socket) -> Optional[tuple[int, bytes]]:
        header = b""
        while len(header) < ipc.HEADER.size:
            chunk = conn.recv(ipc.HEADER.size - len(header))
            if not chunk:
                return None
            header += chunk
        _, length, message_type = ipc.HEADER.unpack(header)
        payload = b""
        while len(payload) < length:
            chunk = conn.recv(length - len(payload))
            if not chunk:
                return None
            payload += chunk
        return message_type, payload

    def _handle(self, conn: socket.socket) -> None:
        try:
            frame = self._read_frame(conn)
            if frame is None:
                return
            message_type, raw = frame
            try:
                self.requests.append((message_type, raw.decode("utf-8")))
            except UnicodeDecodeError:
                self.requests.append((message_type, ""))
            if message_type == ipc.SUBSCRIBE:
                body = json.dumps(self.subscribe_reply).encode()
                conn.sendall(ipc.HEADER.pack(ipc.MAGIC, len(body), ipc.SUBSCRIBE) + body)
                for event_type, event_body in self.events:
                    encoded = json.dumps(event_body).encode()
                    conn.sendall(
                        ipc.HEADER.pack(ipc.MAGIC, len(encoded), event_type) + encoded
                    )
                # Keep the connection open until the client closes it.
                while conn.recv(4096):
                    pass
                return
            reply = self.replies.get(message_type)
            if reply is None and message_type == ipc.RUN_COMMAND:
                reply = self.commands
            body = json.dumps(reply).encode()
            response_type = message_type if self.reply_type is None else self.reply_type
            frame_bytes = ipc.HEADER.pack(ipc.MAGIC, len(body), response_type) + body
            if self.corrupt is not None:
                frame_bytes = self.corrupt(message_type)
            if self.send_all:
                conn.sendall(frame_bytes)
            else:
                for index in range(0, len(frame_bytes), 3):
                    conn.sendall(frame_bytes[index : index + 3])
        finally:
            conn.close()

    def close(self) -> None:
        try:
            self._server.close()
        except OSError:
            pass


def version_payload(minor: int = 9, config_path: str = "/home/user/.config/sway/config") -> dict:
    return {
        "human_readable": f"1.{minor}",
        "variant": "sway",
        "major": 1,
        "minor": minor,
        "patch": 0,
        "loaded_config_file_name": config_path,
    }


def command_reply(success: bool = True, error: Optional[str] = None) -> list[dict]:
    entry: dict[str, Any] = {"success": success}
    if error is not None:
        entry["error"] = error
    return [entry]
