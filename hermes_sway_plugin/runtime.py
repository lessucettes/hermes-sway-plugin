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
        else:
            raise SwayPluginError("invalid_argument", "unsupported window action", {"action": action})

        self._run(command)
        after = self._post_snapshot()
        current = self._current_window(after, node.id)
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
        return {"con_id": node.id, "action": action, "warnings": warnings}


__all__ = ["RuntimeService"]
