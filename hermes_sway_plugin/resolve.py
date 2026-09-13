"""Exactly-one target resolution for runtime Sway operations."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import SwayPluginError
from .tree import NodeSummary, Snapshot

_MATCH_FIELDS = {
    "app_id",
    "class",
    "instance",
    "title",
    "pid",
    "shell",
    "workspace",
    "floating",
}


def _candidate(node: NodeSummary, snapshot: Snapshot) -> dict[str, Any]:
    if node.is_window:
        return snapshot._window(node).compact(include_geometry=False)
    return node.compact()


def _invalid(message: str, **details: Any) -> SwayPluginError:
    return SwayPluginError("invalid_argument", message, details)


def _exact_match(node: NodeSummary, match: Mapping[str, Any]) -> bool:
    values = {
        "app_id": node.app_id,
        "class": node.x11_class,
        "instance": node.x11_instance,
        "title": node.name,
        "pid": node.pid,
        "shell": node.shell,
        "workspace": node.workspace,
        "floating": node.floating,
    }
    return all(values[key] == value for key, value in match.items())


def _selectors(target: Mapping[str, Any]) -> tuple[str, Any]:
    present = [(key, target[key]) for key in ("con_id", "mark", "match") if key in target]
    if len(present) != 1:
        raise _invalid("target requires exactly one of con_id, mark, or match")
    kind, value = present[0]
    if kind == "con_id":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise _invalid("target.con_id must be a positive integer")
    elif kind == "mark":
        if not isinstance(value, str) or not value:
            raise _invalid("target.mark must be a non-empty string")
    else:
        if not isinstance(value, Mapping) or not value:
            raise _invalid("target.match must be a non-empty object")
        unknown = sorted(set(value) - _MATCH_FIELDS)
        if unknown:
            raise _invalid("target.match contains unsupported fields", fields=unknown)
        for key, expected in value.items():
            if key == "pid":
                if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
                    raise _invalid("target.match.pid must be a positive integer")
            elif key == "floating":
                if not isinstance(expected, bool):
                    raise _invalid("target.match.floating must be a boolean")
            elif not isinstance(expected, str):
                raise _invalid(f"target.match.{key} must be a string")
    return kind, value


def resolve_target(snapshot: Snapshot, target: object, *, window_only: bool) -> NodeSummary:
    """Resolve one current node, never guessing a focused or first candidate.

    ``con_id`` is valid for any live node in layout operations. Other window
    mutations require a view (a Wayland ``app_id`` or XWayland identity/window).
    """
    if not isinstance(target, Mapping):
        raise _invalid("target must be an object")
    kind, value = _selectors(target)
    nodes = list(snapshot.nodes.values())
    if kind == "con_id":
        candidates = [node for node in nodes if node.id == value]
    elif kind == "mark":
        candidates = [node for node in nodes if value in node.marks]
    else:
        candidates = [node for node in nodes if _exact_match(node, value)]

    if window_only:
        candidates = [node for node in candidates if node.is_window]

    if not candidates:
        if kind == "con_id" and value in snapshot.nodes and window_only:
            raise SwayPluginError(
                "precondition_failed",
                f"container {value} is not a window view",
                {"con_id": value},
            )
        raise SwayPluginError("target_not_found", "no current Sway target matches", {"target": dict(target)})
    if len(candidates) > 1:
        raise SwayPluginError(
            "target_ambiguous",
            "more than one current Sway target matches; inspect and select a con_id",
            {"target": dict(target), "candidates": [_candidate(node, snapshot) for node in candidates]},
        )
    return candidates[0]


__all__ = ["resolve_target"]
