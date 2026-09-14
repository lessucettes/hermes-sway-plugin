"""Direct argv launch and best-effort Sway window correlation."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .errors import SwayPluginError
from . import ipc, tree

ProcessFactory = Callable[..., Any]
Launch = Callable[[], object]
SubscriptionFactory = Callable[[], Any]
AncestorPids = Callable[[int], Iterable[int] | None]

_IDENTITY_FIELDS = frozenset({"app_id", "class", "instance", "title", "shell"})


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


def _reap_process(process: Any) -> None:
    try:
        process.wait()
    except (OSError, subprocess.SubprocessError):
        pass


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
    if callable(getattr(process, "wait", None)):
        threading.Thread(target=_reap_process, args=(process,), daemon=True).start()
    return {"pid": pid, "started": True}


def _validated_identity(expected_identity: object) -> dict[str, str]:
    if expected_identity is None:
        return {}
    if not isinstance(expected_identity, Mapping):
        raise SwayPluginError("invalid_argument", "expected_identity must be an object")
    unknown = set(expected_identity) - _IDENTITY_FIELDS
    if unknown:
        raise SwayPluginError(
            "invalid_argument",
            "expected_identity contains unsupported fields",
            {"fields": sorted(str(field) for field in unknown)},
        )
    identity = dict(expected_identity)
    if any(not isinstance(value, str) or not value or "\x00" in value for value in identity.values()):
        raise SwayPluginError(
            "invalid_argument",
            "expected_identity values must be non-empty NUL-free strings",
        )
    return identity


def _validated_timeout(timeout_seconds: object) -> float:
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds < 0:
        raise SwayPluginError("invalid_argument", "timeout_seconds must be a non-negative number")
    return float(timeout_seconds)


def _valid_pid(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _launched_process(launch: Launch) -> dict[str, Any]:
    """Run an injected launcher and normalize its successful PID result."""

    result = launch()
    pid = result.get("pid") if isinstance(result, Mapping) else getattr(result, "pid", None)
    safe_pid = _valid_pid(pid)
    if safe_pid is None:
        raise SwayPluginError("launch_failed", "launcher returned no valid PID")
    return {"pid": safe_pid, "started": True}


def _proc_ancestor_pids(pid: int) -> tuple[int, ...] | None:
    """Return observable Linux parent PIDs, or ``None`` when proc is unavailable."""

    ancestors: list[int] = []
    seen = {pid}
    current = pid
    try:
        for _ in range(128):
            stat = Path(f"/proc/{current}/stat").read_text(encoding="utf-8")
            # The process name may contain spaces or parentheses.  The fields
            # after its final ')' begin with state then ppid (fields 3 and 4).
            fields = stat.rsplit(")", 1)[1].split()
            parent = int(fields[1])
            if parent <= 0 or parent in seen:
                return tuple(ancestors)
            ancestors.append(parent)
            seen.add(parent)
            current = parent
    except (IndexError, OSError, ValueError):
        return tuple(ancestors) if ancestors else None
    return tuple(ancestors)


def _new_windows(snapshot: tree.Snapshot, baseline_ids: set[int]) -> tuple[tree.WindowSummary, ...]:
    return tuple(
        window
        for window in snapshot.windows(include_scratchpad=True)
        if window.con_id not in baseline_ids
    )


def _evaluate_window(
    window: tree.WindowSummary,
    launched_pid: int,
    expected_identity: Mapping[str, str],
    ancestor_pids: AncestorPids,
) -> tuple[str | None, list[str]]:
    """Classify correlation evidence without claiming a guaranteed relation."""

    reasons: list[str] = []
    identity_values = {
        "app_id": window.app_id,
        "class": window.x11_class,
        "instance": window.x11_instance,
        "title": window.title,
        "shell": window.shell,
    }
    mismatches = [
        field
        for field, expected in expected_identity.items()
        if identity_values[field] != expected
    ]
    if mismatches:
        return None, [f"candidate {window.con_id} does not have the exact expected identity: {', '.join(mismatches)}"]
    if expected_identity:
        reasons.append(f"candidate {window.con_id} has exact expected identity")

    window_pid = _valid_pid(window.pid)
    if window_pid == launched_pid:
        reasons.append("window PID matches launched process PID")
        return "pid_exact", reasons
    if window_pid is not None:
        observed_ancestors = ancestor_pids(window_pid)
        if observed_ancestors is None:
            reasons.append(f"candidate {window.con_id} ancestor PIDs are unavailable")
        elif launched_pid in observed_ancestors:
            reasons.append("launched process PID is an ancestor of the window PID")
            return "descendant", reasons
        else:
            reasons.append(f"candidate {window.con_id} PID is unrelated to the launched PID")
    else:
        reasons.append(f"candidate {window.con_id} has no usable PID")

    # A newly appeared window with an exact caller-supplied identity is useful
    # evidence for single-instance and daemonizing applications, but weaker than
    # a PID relation.
    if expected_identity:
        reasons.append("using new-window identity evidence without a process relation")
        return "identity_only", reasons
    return None, reasons


def _correlation_result(
    launched: Mapping[str, Any],
    candidates: tuple[tree.WindowSummary, ...],
    expected_identity: Mapping[str, str],
    ancestor_pids: AncestorPids,
    *,
    timed_out: bool,
) -> dict[str, Any]:
    ranked: list[tuple[int, str, tree.WindowSummary]] = []
    reasons: list[str] = []
    strength = {"identity_only": 1, "descendant": 2, "pid_exact": 3}
    for candidate in candidates:
        basis, candidate_reasons = _evaluate_window(
            candidate, launched["pid"], expected_identity, ancestor_pids
        )
        reasons.extend(candidate_reasons)
        if basis is not None:
            ranked.append((strength[basis], basis, candidate))

    strongest = max((item[0] for item in ranked), default=0)
    matched = [item for item in ranked if item[0] == strongest]
    match_basis = matched[0][1] if matched else None
    if len(matched) == 1:
        status = "matched"
        reported = [matched[0][2]]
    elif len(matched) > 1:
        status = "ambiguous"
        reported = [item[2] for item in matched]
        reasons.append(f"{len(matched)} new windows meet the strongest observed correlation criteria")
    else:
        status = "timeout"
        reported = list(candidates)
        if timed_out:
            reasons.append("timed out before a new window met the observed correlation criteria")
        else:
            reasons.append("no window subscription was available for further correlation")

    reasons.append("best-effort correlation only; process-to-window association is not guaranteed")
    return {
        **launched,
        "status": status,
        "match_basis": match_basis,
        "candidates": [window.compact() for window in reported],
        "reasons": reasons,
    }


def _observe_tree(client: Any) -> tuple[tree.Snapshot | None, str | None]:
    try:
        return tree.build_snapshot(client.request(ipc.GET_TREE)), None
    except (
        ipc.SwayUnavailable,
        ipc.SwayTimeout,
        ipc.SwayProtocolError,
        ipc.SwayPayloadTooLarge,
        tree.TreeFormatError,
    ) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _observation_failed(launched: Mapping[str, Any], error: str) -> dict[str, Any]:
    return {
        **launched,
        "status": "observation_failed",
        "match_basis": None,
        "candidates": [],
        "reasons": ["process started, but Sway window observation failed"],
        "observation_error": error,
    }


def correlate_launch(
    client: Any,
    launch: Launch,
    *,
    expected_identity: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
    subscription: Any | None = None,
    subscription_factory: SubscriptionFactory | None = None,
    ancestor_pids: AncestorPids = _proc_ancestor_pids,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Launch once and return only evidence about a possible new Sway window.

    A subscription is opened before the baseline tree when possible.  A
    ``window::new`` event merely invalidates the prior tree: the event payload
    is never treated as a process-to-window association.
    """

    identity = _validated_identity(expected_identity)
    timeout = _validated_timeout(timeout_seconds)
    if not callable(launch):
        raise SwayPluginError("invalid_argument", "launch must be callable")
    if not callable(ancestor_pids):
        raise SwayPluginError("invalid_argument", "ancestor_pids must be callable")

    owned_subscription = False
    active_subscription = subscription
    if active_subscription is None and subscription_factory is not None:
        active_subscription = subscription_factory()
        owned_subscription = True
    elif active_subscription is None and callable(getattr(client, "subscribe", None)):
        active_subscription = client.subscribe(["window"])
        owned_subscription = True

    result: dict[str, Any] | None = None
    try:
        baseline = tree.build_snapshot(client.request(ipc.GET_TREE))
        launched = _launched_process(launch)
        baseline_ids = set(baseline.nodes)

        if active_subscription is None:
            current, observation_error = _observe_tree(client)
            if current is None:
                result = _observation_failed(
                    launched, observation_error or "unknown observation failure"
                )
                return result
            result = _correlation_result(
                launched,
                _new_windows(current, baseline_ids),
                identity,
                ancestor_pids,
                timed_out=False,
            )
            return result

        deadline = monotonic() + timeout
        pending_result: dict[str, Any] | None = None
        quiet_deadline: float | None = None
        while True:
            now = monotonic()
            wait_deadline = min(deadline, quiet_deadline) if quiet_deadline is not None else deadline
            remaining = wait_deadline - now
            if remaining <= 0:
                if pending_result is not None and quiet_deadline is not None and quiet_deadline <= deadline:
                    result = pending_result
                    return result
                current, observation_error = _observe_tree(client)
                if current is None:
                    result = _observation_failed(
                        launched, observation_error or "unknown observation failure"
                    )
                    return result
                result = _correlation_result(
                    launched,
                    _new_windows(current, baseline_ids),
                    identity,
                    ancestor_pids,
                    timed_out=True,
                )
                return result
            try:
                _event_type, _event = active_subscription.recv(remaining)
            except (TimeoutError, ipc.SwayTimeout):
                if pending_result is not None:
                    result = pending_result
                    return result
                current, observation_error = _observe_tree(client)
                if current is None:
                    result = _observation_failed(
                        launched, observation_error or "unknown observation failure"
                    )
                    return result
                result = _correlation_result(
                    launched,
                    _new_windows(current, baseline_ids),
                    identity,
                    ancestor_pids,
                    timed_out=True,
                )
                return result
            except (
                ipc.SwayProtocolError,
                ipc.SwayPayloadTooLarge,
                ipc.SwayUnavailable,
                OSError,
            ) as exc:
                result = _observation_failed(launched, f"{type(exc).__name__}: {exc}")
                return result
            if _event_type != ipc.EVENT_WINDOW:
                continue

            current, observation_error = _observe_tree(client)
            if current is None:
                result = _observation_failed(
                    launched, observation_error or "unknown observation failure"
                )
                return result
            candidates = _new_windows(current, baseline_ids)
            result = _correlation_result(
                launched, candidates, identity, ancestor_pids, timed_out=True
            )
            if result["status"] in {"ambiguous", "matched"}:
                pending_result = result
                quiet_deadline = min(deadline, monotonic() + 0.25)
            else:
                pending_result = None
                quiet_deadline = None
    finally:
        if owned_subscription and active_subscription is not None:
            close = getattr(active_subscription, "close", None)
            if callable(close):
                try:
                    close()
                except OSError as exc:
                    if result is not None:
                        result["reasons"].append(
                            f"failed to close owned window subscription: {type(exc).__name__}: {exc}"
                        )


def launch_and_correlate(
    client: Any,
    argv: object,
    cwd: object = None,
    *,
    expected_identity: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
    process_factory: ProcessFactory = subprocess.Popen,
    subscription: Any | None = None,
    subscription_factory: SubscriptionFactory | None = None,
    ancestor_pids: AncestorPids = _proc_ancestor_pids,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Safely launch an argv process while observing only best-effort evidence."""

    return correlate_launch(
        client,
        lambda: launch_process(argv, cwd, process_factory),
        expected_identity=expected_identity,
        timeout_seconds=timeout_seconds,
        subscription=subscription,
        subscription_factory=subscription_factory,
        ancestor_pids=ancestor_pids,
        monotonic=monotonic,
    )


__all__ = [
    "ProcessFactory",
    "launch_process",
    "correlate_launch",
    "launch_and_correlate",
]
