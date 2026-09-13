"""Hermes tool handlers: argument validation and JSON-string results."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import PERSISTENT, READ_ONLY, RUNTIME, SwayPluginError, error, ok
from . import ipc, launch, persistent, tree
from .runtime import RuntimeService

ConfigGetter = Callable[..., Any]
IPCFactory = Callable[..., Any]

_INSPECT_VIEWS = {"summary", "windows", "workspaces", "outputs", "tree", "marks"}


def _settings(get_config: ConfigGetter) -> Mapping[str, Any]:
    """Read the plugin's own settings namespace once per call."""
    return {
        "ipc_timeout_seconds": get_config("ipc_timeout_seconds", 3.0),
        "reload_timeout_seconds": get_config("reload_timeout_seconds", 5.0),
        "launch_timeout_seconds": get_config("launch_timeout_seconds", 10.0),
        "config_dir": get_config("config_dir", ""),
        "backup_keep": get_config("backup_keep", 10),
    }


def _require(args: Mapping[str, Any], key: str) -> Any:
    if key not in args or args[key] in (None, ""):
        raise SwayPluginError("invalid_argument", f"missing required argument: {key}", {"argument": key})
    return args[key]


def _bounded_int(value: object, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise SwayPluginError(
            "invalid_argument",
            f"{name} must be an integer from {minimum} to {maximum}",
            {"argument": name},
        )
    return value


def _boolean(value: object, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SwayPluginError("invalid_argument", f"{name} must be a boolean", {"argument": name})
    return value


def _bounded_number(value: object, name: str, default: float, minimum: float, maximum: float) -> float:
    if value is None:
        return default
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise SwayPluginError(
            "invalid_argument",
            f"{name} must be a number from {minimum} to {maximum}",
            {"argument": name},
        )
    return float(value)


def _compact_version(version: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: version[key]
        for key in ("human_readable", "variant", "major", "minor", "patch")
        if key in version
    }


def _matches_window(window: tree.WindowSummary, criteria: Mapping[str, Any]) -> bool:
    exact = {
        "workspace": window.workspace,
        "output": window.output,
        "app_id": window.app_id,
        "class": window.x11_class,
        "instance": window.x11_instance,
        "mark": None,
        "shell": window.shell,
        "floating": window.floating,
        "focused": window.focused,
    }
    for key, actual in exact.items():
        if key not in criteria:
            continue
        expected = criteria[key]
        if key == "mark":
            if not isinstance(expected, str) or expected not in window.marks:
                return False
        elif actual != expected:
            return False
    title_contains = criteria.get("title_contains")
    if title_contains is not None:
        if not isinstance(title_contains, str) or title_contains.casefold() not in (window.title or "").casefold():
            return False
    return True


def _inspect_data(
    client: Any,
    view: str,
    criteria: Mapping[str, Any],
    max_results: int,
    include_geometry: bool,
) -> dict[str, Any]:
    version = ipc.assert_sway_19(client.request(ipc.GET_VERSION))
    snapshot = tree.build_snapshot(client.request(ipc.GET_TREE))
    outputs = tree.parse_outputs(client.request(ipc.GET_OUTPUTS))
    workspace_records = snapshot.workspaces(
        include_scratchpad=bool(criteria.get("include_scratchpad", False))
    )
    marks = tree.parse_marks(client.request(ipc.GET_MARKS))
    windows = [
        window
        for window in snapshot.windows(
            include_scratchpad=bool(criteria.get("include_scratchpad", False))
        )
        if _matches_window(window, criteria)
    ]
    focused = snapshot.focused_window()
    common = {
        "version": _compact_version(version),
        "focused": {
            "window": focused.compact(include_geometry=include_geometry) if focused else None,
            "workspace": snapshot.focused_workspace,
            "output": snapshot.focused_output,
        },
    }

    if view == "summary":
        return {
            **common,
            "counts": {
                "windows": len(snapshot.windows()),
                "workspaces": len(snapshot.workspaces()),
                "outputs": len(outputs),
                "marks": len(marks),
            },
        }
    if view == "tree":
        return {**common, "tree": tree.compact_tree(snapshot)}
    if view == "marks":
        selected = list(marks)
    elif view == "windows":
        selected = [window.compact(include_geometry=include_geometry) for window in windows]
    elif view == "workspaces":
        selected = [workspace.compact(include_geometry=include_geometry) for workspace in workspace_records]
    else:
        selected = [output.compact(include_geometry=include_geometry) for output in outputs]

    matched_count = len(selected)
    returned = selected[:max_results]
    return {
        **common,
        "items": returned,
        "matched_count": matched_count,
        "returned_count": len(returned),
        "truncated": matched_count > len(returned),
    }


def sway_inspect(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    **kwargs: Any,
) -> str:
    """Return a bounded compact desktop snapshot from a live Sway 1.9 session."""
    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    view = _require(args, "view")
    if not isinstance(view, str) or view not in _INSPECT_VIEWS:
        raise SwayPluginError("invalid_argument", f"view must be one of {sorted(_INSPECT_VIEWS)}")
    criteria = args.get("filter", {})
    if not isinstance(criteria, Mapping):
        raise SwayPluginError("invalid_argument", "filter must be an object", {"argument": "filter"})
    max_results = _bounded_int(args.get("max_results"), "max_results", 50, 1, 200)
    include_geometry = _boolean(args.get("include_geometry"), "include_geometry", True)
    timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    client = ipc_factory(timeout=float(timeout))
    return ok(READ_ONLY, _inspect_data(client, view, criteria, max_results, include_geometry))


def sway_window(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    **kwargs: Any,
) -> str:
    """Run one verified, typed window mutation against the live Sway session."""
    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    target = _require(args, "target")
    action = _require(args, "action")
    if not isinstance(action, str):
        raise SwayPluginError("invalid_argument", "action must be a string")
    timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    result = RuntimeService(ipc_factory(timeout=float(timeout))).window(
        target, action, **{key: value for key, value in args.items() if key not in {"target", "action"}}
    )
    return ok(RUNTIME, result, result.get("warnings", ()))


def sway_workspace(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    **kwargs: Any,
) -> str:
    """Run one verified, typed workspace mutation against the live Sway session."""
    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    action = _require(args, "action")
    workspace = _require(args, "workspace")
    if not isinstance(action, str):
        raise SwayPluginError("invalid_argument", "action must be a string")
    timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    result = RuntimeService(ipc_factory(timeout=float(timeout))).workspace(
        action, workspace, **{key: value for key, value in args.items() if key not in {"action", "workspace"}}
    )
    return ok(RUNTIME, result, result.get("warnings", ()))


def sway_launch(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    process_factory: launch.ProcessFactory = subprocess.Popen,
    **kwargs: Any,
) -> str:
    """Launch one argv process and report only best-effort window evidence."""
    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    argv = _require(args, "argv")
    wait_for_window = _boolean(args.get("wait_for_window"), "wait_for_window", True)
    if not wait_for_window:
        launched = launch.launch_process(argv, args.get("cwd"), process_factory)
        return ok(
            RUNTIME,
            {**launched, "correlation": {"status": "not_requested"}},
            ("window correlation was not requested",),
        )
    timeout = _bounded_number(
        args.get("timeout_seconds"), "timeout_seconds", float(settings.get("launch_timeout_seconds", 10.0)), 0.5, 30.0
    )
    ipc_timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(ipc_timeout, (int, float)) or isinstance(ipc_timeout, bool) or ipc_timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    client = ipc_factory(timeout=float(ipc_timeout))
    ipc.assert_sway_19(client.request(ipc.GET_VERSION))
    correlation = launch.launch_and_correlate(
        client,
        argv,
        args.get("cwd"),
        expected_identity=args.get("expected_identity"),
        timeout_seconds=timeout,
        process_factory=process_factory,
    )
    launched = {key: correlation[key] for key in ("pid", "started")}
    return ok(RUNTIME, {**launched, "correlation": correlation})


def _rule_from_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """Build only the renderer's typed rule representation from model arguments."""

    kind = _require(args, "kind")
    if kind not in {"window", "workspace_output"}:
        raise SwayPluginError("invalid_argument", "kind must be window or workspace_output")
    if kind == "window":
        intended = _require(args, "intended_cardinality")
        if intended not in {"one", "many"}:
            raise SwayPluginError("invalid_argument", "intended_cardinality must be one or many")
        return {
            "kind": kind,
            "match": _require(args, "match"),
            "destination": args.get("destination", {}),
            "effects": args.get("effects", {}),
            "intended_cardinality": intended,
        }
    return {
        "kind": kind,
        "workspace": _require(args, "workspace"),
        "outputs": _require(args, "outputs"),
    }


def _active_config_has_include(client: Any, include: Path) -> bool:
    """Require the live configuration to contain this exact absolute include line."""

    reply = client.request(ipc.GET_CONFIG)
    text = reply.get("config") if isinstance(reply, Mapping) else reply
    if not isinstance(text, str):
        raise ipc.SwayProtocolError("GET_CONFIG reply does not contain configuration text")
    exact = "include " + str(include)
    return any(line.strip() == exact for line in text.splitlines())


def _audit_live_rule_cardinality(
    rule: Mapping[str, Any],
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    ipc_factory: IPCFactory,
) -> dict[str, Any] | None:
    """Audit against a live tree when available, before any file write occurs."""

    if rule.get("kind") != "window":
        return None
    timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    try:
        client = ipc_factory(timeout=float(timeout))
        snapshot = tree.build_snapshot(client.request(ipc.GET_TREE))
    except (ipc.SwayUnavailable, ipc.SwayTimeout, ipc.SwayProtocolError, tree.TreeFormatError):
        return None
    windows = [
        {
            "app_id": window.app_id,
            "class": window.x11_class,
            "instance": window.x11_instance,
            "title": window.title,
            "window_role": window.window_role,
            "window_type": window.window_type,
            "shell": window.shell,
        }
        for window in snapshot.windows()
    ]
    audit = persistent.audit_cardinality(
        rule["match"],
        rule["intended_cardinality"],
        windows,
        require_verified=not _boolean(args.get("allow_unverified_cardinality"), "allow_unverified_cardinality", False),
    )
    return {
        "intended": audit.intended,
        "match_count": audit.match_count,
        "matched_indices": list(audit.matched_indices),
        "verified": audit.verified,
    }


def _apply_persistent_reload(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    paths: persistent.ManagedRulePaths | persistent.ManagedStartupPaths,
    *,
    ipc_factory: IPCFactory,
    reload_fn: Callable[..., persistent.ReloadResult],
) -> tuple[list[str], dict[str, Any]]:
    """Reload only when the running Sway config explicitly owns this include."""

    if not _boolean(args.get("reload"), "reload", True):
        return [], {"reloaded": False}
    timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    try:
        client = ipc_factory(timeout=float(timeout))
        if not _active_config_has_include(client, paths.include):
            return ["include_not_configured"], {"reloaded": False}
    except (ipc.SwayUnavailable, ipc.SwayTimeout, ipc.SwayProtocolError):
        return ["reload_not_attempted"], {"reloaded": False}
    reload_timeout = settings.get("reload_timeout_seconds", 5.0)
    if not isinstance(reload_timeout, (int, float)) or isinstance(reload_timeout, bool) or reload_timeout <= 0:
        raise SwayPluginError("invalid_argument", "reload_timeout_seconds must be a positive number")
    result = reload_fn(client, lambda: None, timeout=float(reload_timeout))
    return [], {"reloaded": result.reloaded, "rolled_back": result.rolled_back}


def sway_rule(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    subprocess_run: Callable[..., Any] = subprocess.run,
    atomic_replace_fn: Callable[..., persistent.AtomicWrite] | None = None,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    reload_fn: Callable[..., persistent.ReloadResult] = persistent.reload_with_rollback,
    **kwargs: Any,
) -> str:
    """Manage one deterministic, plugin-owned persistent rule document."""

    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    action = _require(args, "action")
    if action not in {"list", "get", "preview", "add", "update", "remove"}:
        raise SwayPluginError("invalid_argument", "unsupported sway_rule action", {"action": action})
    if action == "preview":
        rule = persistent.normalize_managed_rule(_rule_from_args(args))
        audit_data = None
        return ok(
            PERSISTENT,
            {"action": "preview", "rule": rule, "rendered": persistent.render_rule(rule)},
            ("applies_to_new_windows_only",),
        )

    store = persistent.ManagedRuleStore(settings.get("config_dir", ""))
    if action == "list":
        return ok(PERSISTENT, {"action": action, "rules": store.list(), "include": str(store.paths.include)})
    if action == "get":
        return ok(PERSISTENT, {"action": action, "rule": store.get(_require(args, "rule_id"))})

    backup_keep = settings.get("backup_keep", 10)
    write_kwargs = {
        "subprocess_run": subprocess_run,
        "atomic_replace_fn": atomic_replace_fn,
        "backup_count": backup_keep,
    }
    if action == "add":
        requested = {**_rule_from_args(args), "rule_id": args.get("rule_id")}
        audit_data = _audit_live_rule_cardinality(requested, args, settings, ipc_factory=ipc_factory)
        if not _boolean(args.get("allow_external_conflicts"), "allow_external_conflicts", False):
            conflicts = store._conflicts(requested)
            if conflicts:
                raise SwayPluginError(
                    "external_conflict",
                    f"refusing to write conflicting external rule statements: {conflicts[0].text[:200]}",
                    {"kind": conflicts[0].kind, "source": str(conflicts[0].source), "line": conflicts[0].line},
                )
        result = store.add(requested, **write_kwargs)
    elif action == "update":
        requested = _rule_from_args(args)
        audit_data = _audit_live_rule_cardinality(requested, args, settings, ipc_factory=ipc_factory)
        if not _boolean(args.get("allow_external_conflicts"), "allow_external_conflicts", False):
            conflicts = store._conflicts(requested)
            if conflicts:
                raise SwayPluginError(
                    "external_conflict",
                    f"refusing to write conflicting external rule statements: {conflicts[0].text[:200]}",
                    {"kind": conflicts[0].kind, "source": str(conflicts[0].source), "line": conflicts[0].line},
                )
        result = store.update(_require(args, "rule_id"), requested, **write_kwargs)
    else:
        audit_data = None
        result = store.remove(_require(args, "rule_id"), **write_kwargs)
    reload_warnings, reload_data = _apply_persistent_reload(
        args,
        settings,
        store.paths,
        ipc_factory=ipc_factory,
        reload_fn=reload_fn,
    )
    return ok(
        PERSISTENT,
        {
            "action": action,
            "rule": result,
            "include": str(store.paths.include),
            **reload_data,
            **({"cardinality_audit": audit_data} if audit_data is not None else {}),
        },
        ("applies_to_new_windows_only", *reload_warnings),
    )


def sway_layout(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    **kwargs: Any,
) -> str:
    """Run one verified, bounded layout mutation against the live Sway session."""
    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    action = _require(args, "action")
    target = _require(args, "target")
    if not isinstance(action, str):
        raise SwayPluginError("invalid_argument", "action must be a string")
    if action == "swap" and args.get("other_target") in (None, ""):
        raise SwayPluginError("invalid_argument", "swap requires other_target", {"argument": "other_target"})
    timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    arguments = {
        key: value
        for key, value in args.items()
        if key not in {"action", "target"} and value is not None
    }
    result = RuntimeService(ipc_factory(timeout=float(timeout))).layout(action, target, **arguments)
    return ok(RUNTIME, result, result.get("warnings", ()))


def _startup_from_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """Build the typed startup entry representation from model arguments."""

    entry_id = args.get("entry_id", args.get("startup_id"))
    run_on = args.get("run_on", "sway_start_only")
    if run_on not in persistent._STARTUP_RUN_ON:
        raise SwayPluginError("invalid_argument", "run_on must be sway_start_only or sway_start_and_every_reload")
    if run_on == "sway_start_and_every_reload" and not _boolean(
        args.get("acknowledge_reload_relaunch"), "acknowledge_reload_relaunch", False
    ):
        raise SwayPluginError(
            "reload_relaunch_not_acknowledged",
            "sway_start_and_every_reload relaunches the command on every reload; "
            "pass acknowledge_reload_relaunch=true to confirm",
        )
    return {"entry_id": entry_id, "argv": _startup_argv_arg(args.get("argv")), "run_on": run_on}


def _startup_argv_arg(argv: object) -> list[str]:
    """Reject malformed argv as a model-facing argument error, not a rule error."""

    if isinstance(argv, (str, bytes)) or not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= 64:
        raise SwayPluginError("invalid_argument", "argv must contain 1 to 64 strings", {"argument": "argv"})
    if any(not isinstance(item, str) or not item or "\x00" in item or "\n" in item for item in argv):
        raise SwayPluginError(
            "invalid_argument", "every argv element must be a non-empty single-line string", {"argument": "argv"}
        )
    return list(argv)


def _startup_warnings(entry: Mapping[str, Any]) -> list[str]:
    warnings = ["runs_on_sway_start_only"]
    if entry.get("run_on") == "sway_start_and_every_reload":
        warnings = [persistent._STARTUP_RELAUNCH_WARNING, "relaunches_on_every_sway_reload"]
    return warnings


def sway_startup(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    subprocess_run: Callable[..., Any] = subprocess.run,
    atomic_replace_fn: Callable[..., persistent.AtomicWrite] | None = None,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    reload_fn: Callable[..., persistent.ReloadResult] = persistent.reload_with_rollback,
    **kwargs: Any,
) -> str:
    """Manage one deterministic, plugin-owned persistent startup document."""

    if not isinstance(args, Mapping):
        raise SwayPluginError("invalid_argument", "arguments must be an object")
    action = _require(args, "action")
    if action not in {"list", "get", "preview", "add", "update", "remove"}:
        raise SwayPluginError("invalid_argument", "unsupported sway_startup action", {"action": action})
    if action == "preview":
        entry = persistent.normalize_managed_startup(_startup_from_args(args))
        return ok(
            PERSISTENT,
            {"action": "preview", "entry": entry, "rendered": persistent.render_startup_entry(entry)},
            _startup_warnings(entry),
        )

    store = persistent.ManagedStartupStore(settings.get("config_dir", ""))
    if action == "list":
        return ok(PERSISTENT, {"action": action, "entries": store.list(), "include": str(store.paths.include)})
    if action == "get":
        return ok(PERSISTENT, {"action": action, "entry": store.get(_entry_id_arg(args))})

    backup_keep = settings.get("backup_keep", 10)
    write_kwargs = {
        "subprocess_run": subprocess_run,
        "atomic_replace_fn": atomic_replace_fn,
        "backup_count": backup_keep,
    }
    if action == "add":
        result = store.add(_startup_from_args(args), **write_kwargs)
    elif action == "update":
        result = store.update(_entry_id_arg(args), _startup_from_args(args), **write_kwargs)
    else:
        result = store.remove(_entry_id_arg(args), **write_kwargs)
    reload_warnings, reload_data = _apply_persistent_reload(
        args,
        settings,
        store.paths,
        ipc_factory=ipc_factory,
        reload_fn=reload_fn,
    )
    return ok(
        PERSISTENT,
        {"action": action, "entry": result, "include": str(store.paths.include), **reload_data},
        (*_startup_warnings(result), *reload_warnings),
    )


def _entry_id_arg(args: Mapping[str, Any]) -> Any:
    entry_id = args.get("entry_id", args.get("startup_id"))
    if entry_id in (None, ""):
        raise SwayPluginError("invalid_argument", "missing required argument: entry_id", {"argument": "entry_id"})
    return entry_id


def _not_implemented(tool: str) -> Callable[..., str]:
    def handler(args: Mapping[str, Any], settings: Mapping[str, Any], **kwargs: Any) -> str:
        raise SwayPluginError("internal_error", f"{tool} is not implemented yet", {}, recoverable=False)

    return handler


def _translate_exception(exc: Exception) -> SwayPluginError:
    if isinstance(exc, SwayPluginError):
        return exc
    if isinstance(exc, ipc.SwayUnavailable):
        return SwayPluginError("sway_unavailable", str(exc))
    if isinstance(exc, ipc.SwayTimeout):
        return SwayPluginError("ipc_timeout", str(exc))
    if isinstance(exc, ipc.SwayPayloadTooLarge):
        return SwayPluginError("payload_too_large", str(exc))
    if isinstance(exc, (ipc.SwayProtocolError, tree.TreeFormatError)):
        return SwayPluginError("ipc_protocol_error", str(exc))
    if isinstance(exc, persistent.CardinalityError):
        return SwayPluginError("cardinality_unverified", str(exc))
    if isinstance(exc, persistent.DuplicateStartupEntry):
        return SwayPluginError("duplicate_startup_entry", str(exc))
    if isinstance(exc, persistent.ManualEditRefused):
        return SwayPluginError("manual_edit_refused", str(exc))
    if isinstance(exc, persistent.ConfigValidationError):
        return SwayPluginError("config_validation_failed", str(exc))
    if isinstance(exc, persistent.AtomicWriteError):
        return SwayPluginError("atomic_write_failed", str(exc), recoverable=False)
    if isinstance(exc, persistent.ReloadRollbackError):
        return SwayPluginError("reload_failed", str(exc), recoverable=False)
    if isinstance(exc, persistent.PersistentConfigError):
        code = "rule_not_found" if "not found" in str(exc) else "invalid_rule"
        return SwayPluginError(code, str(exc))
    return SwayPluginError("internal_error", f"{type(exc).__name__}: {exc}", recoverable=False)


def build_handlers(
    get_config: ConfigGetter,
    *,
    ipc_factory: IPCFactory = ipc.SwayIPC,
    process_factory: launch.ProcessFactory = subprocess.Popen,
    subprocess_run: Callable[..., Any] = subprocess.run,
    atomic_replace_fn: Callable[..., persistent.AtomicWrite] | None = None,
) -> dict[str, Callable[..., str]]:
    """Bind every tool handler to configuration and optional test dependencies."""

    def bind(func: Callable[..., str]) -> Callable[[Mapping[str, Any]], str]:
        def bound(args: Mapping[str, Any], **kwargs: Any) -> str:
            try:
                settings = _settings(get_config)
                return func(args, settings, ipc_factory=ipc_factory, **kwargs)
            except Exception as exc:
                return error(_translate_exception(exc))

        return bound

    return {
        "sway_inspect": bind(sway_inspect),
        "sway_window": bind(sway_window),
        "sway_workspace": bind(sway_workspace),
        "sway_layout": bind(sway_layout),
        "sway_launch": bind(
            lambda args, settings, **kwargs: sway_launch(
                args, settings, process_factory=process_factory, **kwargs
            )
        ),
        "sway_rule": bind(
            lambda args, settings, **kwargs: sway_rule(
                args,
                settings,
                subprocess_run=subprocess_run,
                atomic_replace_fn=atomic_replace_fn,
                **kwargs,
            )
        ),
        "sway_startup": bind(
            lambda args, settings, **kwargs: sway_startup(
                args,
                settings,
                subprocess_run=subprocess_run,
                atomic_replace_fn=atomic_replace_fn,
                **kwargs,
            )
        ),
    }


__all__ = ["build_handlers", "sway_inspect", "ConfigGetter", "IPCFactory"]
