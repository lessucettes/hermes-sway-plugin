"""Socket discovery, framing, and subscriptions for Sway 1.9 IPC."""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import subprocess
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MAGIC = b"i3-ipc"
HEADER = struct.Struct("=6sII")
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
RUN_COMMAND = 0
GET_WORKSPACES = 1
SUBSCRIBE = 2
GET_OUTPUTS = 3
GET_TREE = 4
GET_MARKS = 5
GET_VERSION = 7
GET_CONFIG = 9
EVENT_BIT = 1 << 31
EVENT_WORKSPACE = EVENT_BIT | 0
EVENT_WINDOW = EVENT_BIT | 3

SWAY_19_MAJOR = 1
SWAY_19_MINOR = 9
DEFAULT_TIMEOUT = 3.0
DISCOVERY_TIMEOUT = 3.0


class SwayUnavailable(Exception):
    """No reachable Sway IPC socket."""


class SwayProtocolError(Exception):
    """A frame violated the i3-ipc protocol or could not be decoded."""


class SwayPayloadTooLarge(Exception):
    """A reply declared a payload above the supported cap."""


class SwayTimeout(Exception):
    """A socket read or an event wait exceeded its deadline."""


def _run_quiet(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        shell=False,
        text=True,
        capture_output=True,
        timeout=DISCOVERY_TIMEOUT,
        check=False,
    )


def _valid_socket_path(candidate: object) -> Optional[str]:
    if not isinstance(candidate, str):
        return None
    candidate = candidate.strip()
    if not candidate:
        return None
    return candidate


def discover_socket_path(explicit: Optional[str] = None) -> str:
    """Resolve the Sway IPC socket without globbing.

    Order: explicit argument -> ``SWAYSOCK`` -> ``sway --get-socketpath`` ->
    ``I3SOCK``. Globbing for sockets is unsafe when several sessions run.
    """
    resolved = _valid_socket_path(explicit)
    if resolved:
        return resolved

    for variable in ("SWAYSOCK", "SWAYSOCK_WLR"):
        resolved = _valid_socket_path(os.environ.get(variable))
        if resolved:
            return resolved

    try:
        probe = _run_quiet(["sway", "--get-socketpath"])
    except (OSError, subprocess.SubprocessError):
        probe = None
    if probe is not None and probe.returncode == 0:
        resolved = _valid_socket_path(probe.stdout)
        if resolved:
            return resolved

    resolved = _valid_socket_path(os.environ.get("I3SOCK"))
    if resolved:
        return resolved

    raise SwayUnavailable(
        "no Sway IPC socket found (checked the explicit path, SWAYSOCK, "
        "`sway --get-socketpath`, and I3SOCK)"
    )


def socket_is_live(path: str, timeout: float = 1.0) -> bool:
    """True when *path* accepts a Unix stream connection."""
    if not path or not os.path.exists(path):
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(timeout)
    try:
        probe.connect(path)
    except OSError:
        return False
    finally:
        probe.close()
    return True


def assert_sway_19(version: object) -> dict:
    """Return the parsed version dict, or raise on anything that is not Sway 1.9."""
    from .errors import SwayPluginError

    if not isinstance(version, dict):
        raise SwayProtocolError("Sway version reply is not an object")
    human = version.get("human_readable")
    major = version.get("major")
    minor = version.get("minor")
    if not isinstance(major, int) or not isinstance(minor, int):
        raise SwayProtocolError("Sway version reply is missing integer major/minor")
    if (major, minor) != (SWAY_19_MAJOR, SWAY_19_MINOR):
        raise SwayPluginError(
            "unsupported_sway_version",
            f"sway {major}.{minor} is not supported; this plugin targets Sway 1.9 only",
            {"major": major, "minor": minor, "human_readable": human},
        )
    return version


def sway_binary_version(timeout: float = DISCOVERY_TIMEOUT) -> dict:
    """Ask the local ``sway`` binary for its version without starting a session."""
    try:
        probe = subprocess.run(
            ["sway", "--version"],
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise SwayUnavailable("the `sway` binary is not installed")
    except subprocess.SubprocessError as exc:
        raise SwayUnavailable(f"`sway --version` failed: {exc}")

    if probe.returncode != 0:
        raise SwayUnavailable(
            f"`sway --version` exited {probe.returncode}: {probe.stderr.strip()[:200]}"
        )
    text = f"{probe.stdout} {probe.stderr}".strip()
    numbers: list[int] = []
    for token in text.replace("-", " ").split():
        if token and token[0].isdigit() and token.split(".")[0].isdigit():
            head = token.split(".")[0]
            try:
                numbers.append(int(head))
            except ValueError:
                continue
            if len(numbers) >= 2:
                break
    if not numbers:
        raise SwayUnavailable(f"cannot parse a version out of `sway --version`: {text[:200]}")
    minor = numbers[1] if len(numbers) > 1 else 0
    return {
        "human_readable": text.split()[-1] if text else "",
        "variant": "sway",
        "major": numbers[0],
        "minor": minor,
    }


def recv_exact(sock: socket.socket, size: int) -> bytes:
    """Read exactly *size* bytes, looping over short reads and raising on EOF."""
    if size < 0:
        raise SwayProtocolError("negative read size")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        try:
            chunk = sock.recv(remaining)
        except socket.timeout as exc:
            raise SwayTimeout(f"timed out while reading {remaining} byte(s)") from exc
        if not chunk:
            raise SwayProtocolError("connection closed before the frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    if not chunks:
        return b""
    return b"".join(chunks)


def send_frame(sock: socket.socket, message_type: int, payload: bytes) -> None:
    try:
        sock.sendall(HEADER.pack(MAGIC, len(payload), message_type) + payload)
    except socket.timeout as exc:
        raise SwayTimeout("timed out while writing the frame") from exc
    except OSError as exc:
        raise SwayProtocolError(f"cannot write the frame: {exc}") from exc


def read_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Read one complete frame, validating magic, cap, and encoded length."""
    header = recv_exact(sock, HEADER.size)
    magic, length, message_type = HEADER.unpack(header)
    if magic != MAGIC:
        raise SwayProtocolError(f"bad frame magic {magic!r}; expected {MAGIC!r}")
    if length > MAX_PAYLOAD_BYTES:
        raise SwayPayloadTooLarge(
            f"declared payload of {length} bytes exceeds the {MAX_PAYLOAD_BYTES} byte cap"
        )
    payload = recv_exact(sock, length) if length else b""
    return message_type, payload


def decode_json(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SwayProtocolError(f"payload is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SwayProtocolError(f"payload is not valid JSON: {exc}") from exc


def encode_payload(payload: object | str) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload).encode("utf-8")


def _connect(socket_path: str, timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(socket_path)
    except socket.timeout as exc:
        sock.close()
        raise SwayTimeout(f"timed out connecting to {socket_path}") from exc
    except OSError as exc:
        sock.close()
        raise SwayUnavailable(f"cannot connect to the Sway socket {socket_path}: {exc}") from exc
    return sock


class SwayIPC:
    """Short-lived request connection to a Sway 1.9 session.

    Every :meth:`request` opens and closes its own socket; v1 deliberately never
    reuses a request connection, so no request-level serialization is needed.
    """

    def __init__(self, socket_path: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT):
        self._explicit_socket_path = socket_path
        self.timeout = timeout

    def socket_path(self) -> str:
        return discover_socket_path(self._explicit_socket_path)

    def request(self, message_type: int, payload: object | str = "") -> object:
        body = encode_payload(payload)
        if len(body) > MAX_PAYLOAD_BYTES:
            raise SwayPayloadTooLarge(
                f"request payload of {len(body)} bytes exceeds the {MAX_PAYLOAD_BYTES} byte cap"
            )
        sock = _connect(self.socket_path(), self.timeout)
        try:
            send_frame(sock, message_type, body)
            reply_type, reply_body = read_frame(sock)
        finally:
            sock.close()
        if reply_type != message_type:
            raise SwayProtocolError(
                f"reply type {reply_type} does not match the requested type {message_type}"
            )
        return decode_json(reply_body)

    def command(self, command: str) -> list[dict]:
        if not isinstance(command, str) or not command.strip():
            raise SwayProtocolError("empty Sway command")
        reply = self.request(RUN_COMMAND, command)
        if not isinstance(reply, list):
            raise SwayProtocolError("RUN_COMMAND reply is not a JSON array")
        for entry in reply:
            if not isinstance(entry, dict):
                raise SwayProtocolError("RUN_COMMAND reply contains a non-object entry")
        return reply

    def subscribe(self, events: list[str]) -> "SwaySubscription":
        return SwaySubscription(self, events)


class SwaySubscription:
    """A dedicated event connection; Sway 1.9 has no unsubscribe request."""

    def __init__(self, ipc: SwayIPC, events: list[str]):
        if not events:
            raise SwayProtocolError("at least one event name is required")
        self._ipc = ipc
        self.events = list(events)
        self._sock: Optional[socket.socket] = None
        self._connect()

    def _connect(self) -> None:
        sock = _connect(self._ipc.socket_path(), self._ipc.timeout)
        try:
            send_frame(sock, SUBSCRIBE, encode_payload(self.events))
            reply_type, reply_body = read_frame(sock)
            if reply_type != SUBSCRIBE:
                raise SwayProtocolError(
                    f"SUBSCRIBE reply type {reply_type} is not {SUBSCRIBE}"
                )
            reply = decode_json(reply_body)
        except BaseException:
            sock.close()
            raise
        if not isinstance(reply, dict) or reply.get("success") is not True:
            sock.close()
            raise SwayProtocolError(f"SUBSCRIBE was rejected: {reply!r}")
        self._sock = sock

    def recv(self, timeout: Optional[float] = None) -> tuple[int, dict]:
        if self._sock is None:
            raise SwayProtocolError("subscription is closed")
        if timeout is not None:
            self._sock.settimeout(max(timeout, 0.0))
        message_type, payload = read_frame(self._sock)
        if not message_type & EVENT_BIT:
            raise SwayProtocolError(
                f"subscription received a non-event frame of type {message_type}"
            )
        body = decode_json(payload)
        if not isinstance(body, dict):
            raise SwayProtocolError("event payload is not a JSON object")
        return message_type, body

    def wait_for(
        self,
        predicate: Callable[[int, dict], bool],
        timeout: float,
    ) -> tuple[int, dict]:
        """Wait until *predicate* matches, using a monotonic deadline."""
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SwayTimeout(f"no matching event within {timeout:.2f}s")
            message_type, body = self.recv(timeout=remaining)
            if predicate(message_type, body):
                return message_type, body

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "SwaySubscription":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
