"""Socket discovery and Sway 1.9 version gating (full transport lands in T5)."""

from __future__ import annotations

import os


class SwayUnavailable(Exception):
    """Raised when no usable Sway IPC socket can be discovered."""


def discover_socket_path(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("SWAYSOCK")
    if env:
        return env
    env = os.environ.get("I3SOCK")
    if env:
        return env
    raise SwayUnavailable("no Sway socket found in SWAYSOCK or I3SOCK")


def assert_sway_19(version: object) -> None:
    raise NotImplementedError("version gating lands in T4")


def sway_binary_version() -> object:
    raise NotImplementedError("binary version probe lands in T4")


class SwayIPC:  # pragma: no cover - transport lands in T5
    def __init__(self, socket_path: str | None = None, timeout: float = 3.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
