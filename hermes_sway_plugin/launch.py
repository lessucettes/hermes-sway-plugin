"""Direct argv launch and best-effort Sway window correlation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .errors import SwayPluginError

ProcessFactory = Callable[..., Any]


def _validated_argv(argv: object) -> list[str]:
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64:
        raise SwayPluginError("invalid_argument", "argv must contain 1 to 64 strings")
    if any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise SwayPluginError("invalid_argument", "every argv element must be a non-empty NUL-free string")
    return list(argv)


def _validated_cwd(cwd: object) -> str | None:
    if cwd is None:
        return None
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise SwayPluginError("invalid_argument", "cwd must be an absolute path")
    if not Path(cwd).is_dir():
        raise SwayPluginError("invalid_argument", "cwd does not exist or is not a directory", {"cwd": cwd})
    return cwd


def launch_process(
    argv: object,
    cwd: object = None,
    process_factory: ProcessFactory = subprocess.Popen,
) -> dict[str, Any]:
    """Start an argv process without a shell and report only process success.

    Window correlation is deliberately separate: process start cannot establish
    a reliable process-to-window association in Sway IPC.
    """
    safe_argv = _validated_argv(argv)
    safe_cwd = _validated_cwd(cwd)
    try:
        process = process_factory(
            safe_argv,
            cwd=safe_cwd,
            shell=False,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SwayPluginError("launch_failed", f"failed to start {safe_argv[0]!r}: {exc}") from exc
    pid = getattr(process, "pid", None)
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise SwayPluginError("launch_failed", "process factory returned no valid PID")
    return {"pid": pid, "started": True}


__all__ = ["launch_process", "ProcessFactory"]
