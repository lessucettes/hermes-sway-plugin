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
_WINDOW_ACTION_FIELDS = {
    "focus": set(),
    "move_to_workspace": {"workspace"},
    "move_to_output": {"output"},
    "move_direction": {"direction"},
    "set_floating": {"enabled"},
    "set_fullscreen": {"enabled"},
    "resize": {"width", "height", "unit"},
    "position": {"position"},
    "move_to_scratchpad": set(),
    "show_from_scratchpad": set(),
    "set_sticky": {"enabled"},
    "mark": {"mark"},
    "unmark": {"mark"},
    "close": {"confirm_close"},
}
_WORKSPACE_ACTION_FIELDS = {
    "focus_or_create": set(),
    "rename": {"new_name"},
    "move_to_output": {"output", "restore_focus"},
}
_LAYOUT_ACTION_FIELDS = {
    "set_parent_layout": {"layout"},
    "split_at": {"orientation"},
    "swap": {"other_target"},
}


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


def _reject_action_irrelevant_fields(
    args: Mapping[str, Any],
    action: object,
    action_fields: Mapping[str, set[str]],
    common: set[str],
) -> None:
    if not isinstance(action, str) or action not in action_fields:
        raise SwayPluginError("invalid_argument", "unsupported action", {"action": action})
    irrelevant = sorted(set(args) - common - action_fields[action])
    if irrelevant:
        raise SwayPluginError(
            "invalid_argument",
            "arguments are not valid for this action",
            {"action": action, "fields": irrelevant},
        )


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
    states = tree.parse_workspace_states(client.request(ipc.GET_WORKSPACES))
    workspace_records = snapshot.workspaces(
        include_scratchpad=bool(criteria.get("include_scratchpad", False)),
        states=states,
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
    # GET_WORKSPACES is authoritative for live focus when the tree omits it.
    focused_workspace = next((state.name for state in states.values() if state.focused), None)
    if focused_workspace is None:
        focused_workspace = snapshot.focused_workspace
    focused_output = snapshot.focused_output
    if focused_output is None and focused_workspace is not None:
        focused_output = next(
            (record.output for record in workspace_records if record.name == focused_workspace and record.output),
            None,
        )
    common = {
        "version": _compact_version(version),
        "focused": {
            "window": focused.compact(include_geometry=include_geometry) if focused else None,
            "workspace": focused_workspace,
            "output": focused_output,
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
    view = args.get("view", "summary")
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
    _reject_action_irrelevant_fields(args, action, _WINDOW_ACTION_FIELDS, {"action", "target"})
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
    _reject_action_irrelevant_fields(args, action, _WORKSPACE_ACTION_FIELDS, {"action", "workspace"})
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
        intended = args.get("intended_cardinality", "many")
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


def _active_config_has_include(client: Any, include: Path, main_config: Path) -> bool:
    """Recognize a live literal include that resolves to the managed file.

    Sway expands relative paths, ``~`` and filesystem globs. We mirror those safe
    cases without evaluating variables or command substitutions.
    """

    reply = client.request(ipc.GET_CONFIG)
    text = reply.get("config") if isinstance(reply, Mapping) else reply
    if not isinstance(text, str):
        raise ipc.SwayProtocolError("GET_CONFIG reply does not contain configuration text")
    owned = {include.resolve()}
    for raw in text.splitlines():
        statement = raw.strip()
        if statement.casefold().startswith("include "):
            target = statement[8:].strip()
            if target and persistent.include_target_matches_owned(main_config.parent, target, owned):
                return True
    return False


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
        require_verified=False,
    )
    return {
        "intended": audit.intended,
        "match_count": audit.match_count,
        "matched_indices": list(audit.matched_indices),
        "verified": audit.verified,
    }


def _record_atomic_writes(
    writer: Callable[..., persistent.AtomicWrite] | None,
) -> tuple[Callable[..., persistent.AtomicWrite], list[persistent.AtomicWrite]]:
    writes: list[persistent.AtomicWrite] = []
    actual = persistent.atomic_replace if writer is None else writer

    def recording_writer(*args: Any, **kwargs: Any) -> persistent.AtomicWrite:
        result = actual(*args, **kwargs)
        writes.append(result)
        return result

    return recording_writer, writes


def _persistent_reload_options(
    args: Mapping[str, Any], settings: Mapping[str, Any]
) -> tuple[bool, float, float]:
    """Validate every post-write setting before a persistent mutation starts."""

    reload_requested = _boolean(args.get("reload"), "reload", True)
    ipc_timeout = settings.get("ipc_timeout_seconds", 3.0)
    if not isinstance(ipc_timeout, (int, float)) or isinstance(ipc_timeout, bool) or ipc_timeout <= 0:
        raise SwayPluginError("invalid_argument", "ipc_timeout_seconds must be a positive number")
    reload_timeout = settings.get("reload_timeout_seconds", 5.0)
    if not isinstance(reload_timeout, (int, float)) or isinstance(reload_timeout, bool) or reload_timeout <= 0:
        raise SwayPluginError("invalid_argument", "reload_timeout_seconds must be a positive number")
    return reload_requested, float(ipc_timeout), float(reload_timeout)


def _apply_persistent_reload(
    args: Mapping[str, Any],
    settings: Mapping[str, Any],
    paths: persistent.ManagedRulePaths | persistent.ManagedStartupPaths,
    write: persistent.AtomicWrite,
    reload_options: tuple[bool, float, float],
    *,
    ipc_factory: IPCFactory,
    reload_fn: Callable[..., persistent.ReloadResult],
) -> tuple[list[str], dict[str, Any]]:
    """Reload only when the running Sway config explicitly owns this include."""

    reload_requested, ipc_timeout, reload_timeout = reload_options
    if not reload_requested:
        persistent.discard_atomic_write(write)
        return [], {"reloaded": False}
    try:
        client = ipc_factory(timeout=ipc_timeout)
        if not _active_config_has_include(client, paths.include, paths.main_config):
            persistent.discard_atomic_write(write)
            return ["include_not_configured"], {"reloaded": False}
    except (ipc.SwayUnavailable, ipc.SwayTimeout, ipc.SwayProtocolError):
        persistent.discard_atomic_write(write)
        return ["reload_not_attempted"], {"reloaded": False}
    result = reload_fn(
        client,
        lambda: persistent.restore_atomic_write(write),
        timeout=reload_timeout,
    )
    persistent.discard_atomic_write(write)
    if result.rolled_back:
        raise SwayPluginError(
            "reload_rolled_back",
            "Sway did not confirm the requested configuration reload; the previous managed file was restored",
            {
                "include": str(paths.include),
                "reloaded": False,
                "rolled_back": True,
                "reload_error": result.error,
            },
        )
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
        warnings = ("applies_to_new_windows_only",) if rule["kind"] == "window" else ()
        return ok(
            PERSISTENT,
            {
                "action": "preview",
                "rule": rule,
                "rendered": persistent.render_rule(rule),
                "include": str(persistent.managed_rule_paths(settings.get("config_dir", "")).include),
            },
            warnings,
        )

    store = persistent.ManagedRuleStore(settings.get("config_dir", ""))
    if action == "list":
        return ok(PERSISTENT, {"action": action, "rules": store.list(), "include": str(store.paths.include)})
    if action == "get":
        return ok(PERSISTENT, {"action": action, "rule": store.get(_require(args, "rule_id"))})

    reload_options = _persistent_reload_options(args, settings)
    backup_keep = settings.get("backup_keep", 10)
    recording_writer, writes = _record_atomic_writes(atomic_replace_fn)
    write_kwargs = {
        "subprocess_run": subprocess_run,
        "atomic_replace_fn": recording_writer,
        "backup_count": backup_keep,
    }
    external_conflicts: tuple[persistent.IncludeConflict, ...] = ()
    if action == "add":
        requested = {**_rule_from_args(args), "rule_id": args.get("rule_id")}
        audit_data = _audit_live_rule_cardinality(requested, args, settings, ipc_factory=ipc_factory)
        external_conflicts = store._conflicts(requested)
        result = store.add(requested, **write_kwargs)
    elif action == "update":
        requested = _rule_from_args(args)
        audit_data = _audit_live_rule_cardinality(requested, args, settings, ipc_factory=ipc_factory)
        external_conflicts = store._conflicts(requested)
        result = store.update(_require(args, "rule_id"), requested, **write_kwargs)
    else:
        audit_data = None
        result = store.remove(_require(args, "rule_id"), **write_kwargs)
    reload_warnings, reload_data = _apply_persistent_reload(
        args,
        settings,
        store.paths,
        writes[-1],
        reload_options,
        ipc_factory=ipc_factory,
        reload_fn=reload_fn,
    )
    applies_to_new_windows = action in {"add", "update"} and result.get("kind") == "window"
    result_warnings: list[str] = []
    if applies_to_new_windows:
        result_warnings.append("applies_to_new_windows_only")
    if audit_data is not None and not audit_data["verified"]:
        result_warnings.append("cardinality_unverified")
    if external_conflicts:
        result_warnings.append("external_rule_statements_present")
    result_warnings.extend(reload_warnings)
    return ok(
        PERSISTENT,
        {
            "action": action,
            "rule": result,
            "include": str(store.paths.include),
            "applies_to_new_windows_only": applies_to_new_windows,
            **reload_data,
            **({"cardinality_audit": audit_data} if audit_data is not None else {}),
            **(
                {
                    "external_conflicts": [
                        {
                            "kind": conflict.kind,
                            "source": str(conflict.source),
                            "line": conflict.line,
                            "text": conflict.text,
                        }
                        for conflict in external_conflicts
                    ]
                }
                if external_conflicts
                else {}
            ),
        },
        result_warnings,
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
    _reject_action_irrelevant_fields(args, action, _LAYOUT_ACTION_FIELDS, {"action", "target"})
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

    entry_id = args.get("startup_id", args.get("entry_id"))
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


def _startup_result(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Present a stored entry under the schema-declared ``startup_id`` name."""

    return {"startup_id": entry["entry_id"], "argv": entry["argv"], "run_on": entry["run_on"]}


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
            {"action": "preview", "entry": _startup_result(entry), "rendered": persistent.render_startup_entry(entry)},
            _startup_warnings(entry),
        )

    store = persistent.ManagedStartupStore(settings.get("config_dir", ""))
    if action == "list":
        return ok(
            PERSISTENT,
            {
                "action": action,
                "entries": [_startup_result(entry) for entry in store.list()],
                "include": str(store.paths.include),
            },
        )
    if action == "get":
        return ok(PERSISTENT, {"action": action, "entry": _startup_result(store.get(_entry_id_arg(args)))})

    reload_options = _persistent_reload_options(args, settings)
    backup_keep = settings.get("backup_keep", 10)
    recording_writer, writes = _record_atomic_writes(atomic_replace_fn)
    write_kwargs = {
        "subprocess_run": subprocess_run,
        "atomic_replace_fn": recording_writer,
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
        writes[-1],
        reload_options,
        ipc_factory=ipc_factory,
        reload_fn=reload_fn,
    )
    entry_warnings = _startup_warnings(result) if action in {"add", "update"} else []
    return ok(
        PERSISTENT,
        {"action": action, "entry": _startup_result(result), "include": str(store.paths.include), **reload_data},
        (*entry_warnings, *reload_warnings),
    )


def _entry_id_arg(args: Mapping[str, Any]) -> Any:
    entry_id = args.get("startup_id", args.get("entry_id"))
    if entry_id in (None, ""):
        raise SwayPluginError("invalid_argument", "missing required argument: startup_id", {"argument": "startup_id"})
    return entry_id


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
        message = str(exc)
        if "startup entry not found" in message:
            code = "startup_not_found"
        elif "rule not found" in message:
            code = "rule_not_found"
        else:
            code = "invalid_rule"
        return SwayPluginError(code, message)
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
