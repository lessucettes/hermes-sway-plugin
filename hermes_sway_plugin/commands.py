"""Typed Sway 1.9 command builders and command-reply validation."""

from __future__ import annotations

import re
from typing import Any

from .errors import MAX_ERROR_TEXT, SwayPluginError

_MARK_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def quote(value: object) -> str:
    """Quote one scalar for Sway's command parser without accepting newlines."""
    if not isinstance(value, str):
        raise SwayPluginError("invalid_argument", "Sway command scalar must be a string")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SwayPluginError("invalid_argument", "Sway command scalar cannot contain NUL or line breaks")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def criterion_for_con_id(con_id: object) -> str:
    """Create the only runtime criterion used after client-side resolution."""
    if not isinstance(con_id, int) or isinstance(con_id, bool) or con_id <= 0:
        raise SwayPluginError("invalid_argument", "con_id must be a positive integer")
    return f"[con_id={con_id}]"


def mark_name(value: object) -> str:
    if not isinstance(value, str) or not _MARK_RE.fullmatch(value):
        raise SwayPluginError(
            "invalid_argument",
            "mark must match ^[A-Za-z0-9_.:-]{1,64}$",
            {"argument": "mark"},
        )
    return value


def command_or_raise(command: str, reply: object) -> list[dict]:
    """Accept only a nonempty successful Sway ``RUN_COMMAND`` result array."""
    if not isinstance(reply, list) or not reply:
        raise SwayPluginError("ipc_protocol_error", "RUN_COMMAND reply must be a non-empty array")
    checked: list[dict] = []
    for index, result in enumerate(reply):
        if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
            raise SwayPluginError(
                "ipc_protocol_error",
                "RUN_COMMAND reply contains an invalid result object",
                {"index": index},
            )
        checked.append(result)
        if result["success"] is False:
            raw_error = result.get("error")
            message = raw_error if isinstance(raw_error, str) else "Sway rejected the command"
            raise SwayPluginError(
                "command_rejected",
                "Sway rejected a typed command",
                {
                    "command": command,
                    "index": index,
                    "sway_error": message[:MAX_ERROR_TEXT],
                },
            )
    return checked


__all__ = ["quote", "criterion_for_con_id", "mark_name", "command_or_raise"]
