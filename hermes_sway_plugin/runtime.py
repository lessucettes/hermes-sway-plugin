"""Verified runtime mutations over an injected Sway IPC-like client."""

from __future__ import annotations

from typing import Any, Mapping

from . import commands, ipc, tree
from .errors import SwayPluginError
from .resolve import resolve_target


class RuntimeService:
    """Execute one typed mutation against fresh pre- and post-command trees."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _snapshot(self) -> tree.Snapshot:
        ipc.assert_sway_19(self._client.request(ipc.GET_VERSION))
        return tree.build_snapshot(self._client.request(ipc.GET_TREE))

    def _post_snapshot(self) -> tree.Snapshot:
        return tree.build_snapshot(self._client.request(ipc.GET_TREE))

    def _run(self, command: str) -> None:
        commands.command_or_raise(command, self._client.command(command))

    def _current_window(self, snapshot: tree.Snapshot, con_id: int) -> tree.WindowSummary | None:
        return next((window for window in snapshot.windows(include_scratchpad=True) if window.con_id == con_id), None)

    def window(self, target: object, action: str, **arguments: Any) -> dict[str, Any]:
        """Apply one window mutation and assert its observable postcondition."""
        before = self._snapshot()
        node = resolve_target(before, target, window_only=True)
        criterion = commands.criterion_for_con_id(node.id)
        warnings: list[str] = []
        workspace: str | None = None
        output: str | None = None
        enabled: bool | None = None
        width: int | None = None
        height: int | None = None
        position: Mapping[str, Any] | None = None
        if action == "focus":
            command = f"{criterion} focus"
        elif action == "move_to_workspace":
            workspace = arguments.get("workspace")
            if not isinstance(workspace, str) or not workspace:
                raise SwayPluginError("invalid_argument", "workspace must be a non-empty string")
            command = f"{criterion} move container to workspace {commands.quote(workspace)}"
        elif action == "move_to_output":
            output = arguments.get("output")
            if not isinstance(output, str) or not output:
                raise SwayPluginError("invalid_argument", "output must be a non-empty string")
            command = f"{criterion} move container to output {commands.quote(output)}"
        elif action == "move_direction":
            direction = arguments.get("direction")
            if direction not in {"left", "right", "up", "down"}:
                raise SwayPluginError("invalid_argument", "direction must be left, right, up, or down")
            command = f"{criterion} move {direction}"
            warnings.append("directional placement is compositor-dependent; inspect the resulting layout")
        elif action in {"set_floating", "set_fullscreen"}:
            enabled = arguments.get("enabled")
            if not isinstance(enabled, bool):
                raise SwayPluginError("invalid_argument", "enabled must be a boolean")
            operation = "floating" if action == "set_floating" else "fullscreen"
            command = f"{criterion} {operation} {'enable' if enabled else 'disable'}"
        elif action == "resize":
            current_before = self._current_window(before, node.id)
            if current_before is None or not current_before.floating or current_before.fullscreen:
                raise SwayPluginError("precondition_failed", "resize requires a floating, non-fullscreen window")
            width, height = arguments.get("width"), arguments.get("height")
            unit = arguments.get("unit", "px")
            if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (width, height)):
                raise SwayPluginError("invalid_argument", "width and height must be positive integers")
            if unit not in {"px", "ppt"}:
                raise SwayPluginError("invalid_argument", "unit must be px or ppt")
            command = f"{criterion} resize set {width} {unit} {height} {unit}"
        elif action == "position":
            current_before = self._current_window(before, node.id)
            if current_before is None or not current_before.floating or current_before.fullscreen:
                raise SwayPluginError("precondition_failed", "position requires a floating, non-fullscreen window")
            candidate = arguments.get("position")
            if not isinstance(candidate, Mapping) or candidate.get("mode") != "coordinates":
                raise SwayPluginError("invalid_argument", "position must specify coordinate mode")
            x, y = candidate.get("x"), candidate.get("y")
            if not all(isinstance(value, int) and not isinstance(value, bool) for value in (x, y)):
                raise SwayPluginError("invalid_argument", "position coordinates must be integers")
            position = candidate
            command = f"{criterion} move position {x} px {y} px"
        else:
            raise SwayPluginError("invalid_argument", "unsupported window action", {"action": action})

        self._run(command)
        after = self._post_snapshot()
        current = self._current_window(after, node.id)
        if current is None:
            raise SwayPluginError(
                "postcondition_failed",
                "window disappeared while verifying the mutation",
                {"con_id": node.id, "action": action},
            )
        if action == "focus":
            observed = after.focused_window()
            if observed is None or observed.con_id != node.id:
                raise SwayPluginError(
                    "postcondition_failed",
                    "window did not become focused after the command",
                    {"con_id": node.id, "action": action},
                )
        elif action == "move_to_workspace" and (current is None or current.workspace != workspace):
            raise SwayPluginError(
                "postcondition_failed",
                "window did not move to the requested workspace",
                {"con_id": node.id, "workspace": workspace},
            )
        elif action == "move_to_output" and (current is None or current.output != output):
            raise SwayPluginError(
                "postcondition_failed",
                "window did not move to the requested output",
                {"con_id": node.id, "output": output},
            )
        elif action == "set_floating" and current.floating != enabled:
            raise SwayPluginError("postcondition_failed", "window floating state did not change", {"con_id": node.id})
        elif action == "set_fullscreen" and current.fullscreen != enabled:
            raise SwayPluginError("postcondition_failed", "window fullscreen state did not change", {"con_id": node.id})
        elif action == "resize" and (
            current.rect is None or current.rect.width != width or current.rect.height != height
        ):
            raise SwayPluginError("postcondition_failed", "window size did not reach the requested dimensions", {"con_id": node.id})
        elif action == "position":
            assert position is not None
            if (
                current.rect is None
                or current.rect.x != position["x"]
                or current.rect.y != position["y"]
            ):
                raise SwayPluginError(
                    "postcondition_failed",
                    "window position did not reach the requested coordinates",
                    {"con_id": node.id},
                )
        return {"con_id": node.id, "action": action, "warnings": warnings}


__all__ = ["RuntimeService"]
