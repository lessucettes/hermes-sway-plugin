"""Stable JSON result envelopes for every sway tool."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

MAX_ERROR_TEXT = 2000

READ_ONLY = "read_only"
RUNTIME = "runtime"
PERSISTENT = "persistent"


class SwayPluginError(Exception):
    """A typed, model-facing failure with a stable ``code``."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.recoverable = recoverable


def _clip(text: object) -> str:
    rendered = text if isinstance(text, str) else str(text)
    if len(rendered) <= MAX_ERROR_TEXT:
        return rendered
    return rendered[: MAX_ERROR_TEXT - 3] + "..."


def dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def ok(scope: str, data: Mapping[str, Any], warnings: Iterable[str] = ()) -> str:
    return dumps(
        {
            "ok": True,
            "scope": scope,
            "data": dict(data),
            "warnings": [str(warning) for warning in warnings],
        }
    )


def error(exc: BaseException) -> str:
    if isinstance(exc, SwayPluginError):
        return dumps(
            {
                "ok": False,
                "error": {
                    "code": exc.code,
                    "message": _clip(exc.message),
                    "details": exc.details,
                },
                "recoverable": exc.recoverable,
            }
        )
    logger.exception("Unhandled sway plugin failure")
    return dumps(
        {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": _clip(f"{type(exc).__name__}: {exc}"),
                "details": {},
            },
            "recoverable": False,
        }
    )
