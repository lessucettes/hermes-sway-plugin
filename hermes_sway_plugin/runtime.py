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

    def window(self, target: object, action: str, **arguments: Any) -> dict[str, Any]:
        """Apply one window mutation and assert its observable postcondition."""
        if action != "focus":
            raise SwayPluginError("invalid_argument", "unsupported window action", {"action": action})
        before = self._snapshot()
        node = resolve_target(before, target, window_only=True)
        command = f"{commands.criterion_for_con_id(node.id)} focus"
        self._run(command)
        after = self._post_snapshot()
        current = after.focused_window()
        if current is None or current.con_id != node.id:
            raise SwayPluginError(
                "postcondition_failed",
                "window did not become focused after the command",
                {"con_id": node.id, "action": action},
            )
        return {"con_id": node.id, "action": action, "warnings": []}


__all__ = ["RuntimeService"]
