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

    def layout(self, action: str, target: object, **arguments: Any) -> dict[str, Any]:
        """Apply one bounded layout mutation and verify fresh tree evidence.

        Sway is permitted to introduce or flatten intermediate containers while
        executing these commands, so verification tracks the selected live
        containers and their observable relationship rather than assuming an
        unchanged complete ancestry chain.
        """
        before = self._snapshot()
        node = resolve_target(before, target, window_only=False)
        warnings = ["Sway may automatically split or flatten containers, changing ancestry; inspect the resulting layout"]

        if action == "set_parent_layout":
            layout = arguments.get("layout")
            if layout not in {"default", "splith", "splitv", "stacking", "tabbed"}:
                raise SwayPluginError(
                    "invalid_argument",
                    "layout must be default, splith, splitv, stacking, or tabbed",
                )
            parent = before.node(node.parent_id) if node.parent_id is not None else None
            if parent is None:
                raise SwayPluginError(
                    "precondition_failed",
                    "set_parent_layout requires a target with a live parent container",
                    {"con_id": node.id},
                )
            self._run(f"{commands.criterion_for_con_id(parent.id)} layout {layout}")
            after = self._post_snapshot()
            current = after.node(node.id)
            if current is None:
                raise SwayPluginError(
                    "postcondition_failed",
                    "target disappeared while verifying the layout mutation",
                    {"con_id": node.id, "action": action},
                )
            current_parent = after.node(current.parent_id) if current.parent_id is not None else None
            if current_parent is None:
                raise SwayPluginError(
                    "postcondition_failed",
                    "target no longer has a live parent after setting its parent layout",
                    {"con_id": node.id, "action": action},
                )
            if layout != "default" and current_parent.layout != layout:
                raise SwayPluginError(
                    "postcondition_failed",
                    "target parent did not reach the requested layout",
                    {"con_id": node.id, "layout": layout, "observed_layout": current_parent.layout},
                )
            return {
                "action": action,
                "con_id": node.id,
                "parent_con_id": parent.id,
                "layout": layout,
                "warnings": warnings,
            }

        if action == "split_at":
            orientation = arguments.get("orientation")
            if orientation not in {"horizontal", "vertical"}:
                raise SwayPluginError("invalid_argument", "orientation must be horizontal or vertical")
            self._run(f"{commands.criterion_for_con_id(node.id)} split {orientation}")
            after = self._post_snapshot()
            if after.node(node.id) is None:
                raise SwayPluginError(
                    "postcondition_failed",
                    "target disappeared while verifying the split",
                    {"con_id": node.id, "action": action},
                )
            return {"action": action, "con_id": node.id, "orientation": orientation, "warnings": warnings}

        if action == "swap":
            return self._swap(before, node, arguments.get("other_target"), warnings)

        raise SwayPluginError("invalid_argument", "unsupported layout action", {"action": action})

    def _swap(
        self,
        before: tree.Snapshot,
        node: tree.NodeSummary,
        other_target: object,
        warnings: list[str],
    ) -> dict[str, Any]:
        """Swap two non-nested containers and prove they exchanged tree slots."""
        other = resolve_target(before, other_target, window_only=False)
        if other.id == node.id:
            raise SwayPluginError("precondition_failed", "swap requires two distinct containers", {"con_id": node.id})
        if other.id in node.ancestor_ids or node.id in other.ancestor_ids:
            raise SwayPluginError(
                "precondition_failed",
                "swap cannot exchange an ancestor with its descendant",
                {"con_id": node.id, "other_con_id": other.id},
            )
        target_slot = self._slot(before, node.id)
        other_slot = self._slot(before, other.id)
        self._run(f"{commands.criterion_for_con_id(node.id)} swap container with con_id {other.id}")
        after = self._post_snapshot()
        if after.node(node.id) is None or after.node(other.id) is None:
            raise SwayPluginError(
                "postcondition_failed",
                "a swap target disappeared while verifying the mutation",
                {"con_id": node.id, "other_con_id": other.id},
            )
        if self._slot(after, node.id) != other_slot or self._slot(after, other.id) != target_slot:
            raise SwayPluginError(
                "postcondition_failed",
                "containers did not exchange their exact tree positions",
                {"con_id": node.id, "other_con_id": other.id},
            )
        return {"action": "swap", "con_id": node.id, "other_con_id": other.id, "warnings": warnings}

    @staticmethod
    def _slot(snapshot: tree.Snapshot, con_id: int) -> tuple[int, int] | None:
        """Return a container's immediate parent and child index, if live."""
        node = snapshot.node(con_id)
        if node is None or node.parent_id is None:
            return None
        parent = snapshot.node(node.parent_id)
        if parent is None:
            return None
        try:
            return parent.id, parent.child_ids.index(con_id)
        except ValueError:
            return None

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
        mark: str | None = None
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
            if not isinstance(candidate, Mapping):
                raise SwayPluginError("invalid_argument", "position must be an object")
            if candidate.get("mode") == "center":
                command = f"{criterion} move position center"
                warnings.append("centering is compositor-dependent; inspect the resulting geometry")
            elif candidate.get("mode") == "coordinates":
                x, y = candidate.get("x"), candidate.get("y")
                if not all(isinstance(value, int) and not isinstance(value, bool) for value in (x, y)):
                    raise SwayPluginError("invalid_argument", "position coordinates must be integers")
                position = candidate
                command = f"{criterion} move position {x} px {y} px"
            else:
                raise SwayPluginError("invalid_argument", "position mode must be center or coordinates")
        elif action == "move_to_scratchpad":
            command = f"{criterion} move scratchpad"
        elif action == "show_from_scratchpad":
            current_before = self._current_window(before, node.id)
            if current_before is None or not current_before.scratchpad:
                raise SwayPluginError("precondition_failed", "window is not currently in the scratchpad")
            command = f"{criterion} scratchpad show"
        elif action == "set_sticky":
            current_before = self._current_window(before, node.id)
            enabled = arguments.get("enabled")
            if current_before is None or not current_before.floating:
                raise SwayPluginError("precondition_failed", "sticky requires a floating window")
            if not isinstance(enabled, bool):
                raise SwayPluginError("invalid_argument", "enabled must be a boolean")
            command = f"{criterion} sticky {'enable' if enabled else 'disable'}"
        elif action in {"mark", "unmark"}:
            mark = commands.mark_name(arguments.get("mark"))
            operation = "mark --add" if action == "mark" else "unmark"
            command = f"{criterion} {operation} {commands.quote(mark)}"
        elif action == "close":
            if arguments.get("confirm_close") is not True:
                raise SwayPluginError("precondition_failed", "close requires confirm_close=true")
            command = f"{criterion} kill"
        else:
            raise SwayPluginError("invalid_argument", "unsupported window action", {"action": action})

        self._run(command)
        after = self._post_snapshot()
        current = self._current_window(after, node.id)
        if action == "close":
            if current is not None:
                raise SwayPluginError("postcondition_failed", "window remained after close", {"con_id": node.id})
            return {"con_id": node.id, "action": action, "warnings": warnings}
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
        elif action == "position" and position is not None:
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
        elif action == "move_to_scratchpad" and not current.scratchpad:
            raise SwayPluginError("postcondition_failed", "window did not enter the scratchpad", {"con_id": node.id})
        elif action == "show_from_scratchpad" and current.scratchpad:
            raise SwayPluginError("postcondition_failed", "window remained in the scratchpad", {"con_id": node.id})
        elif action == "set_sticky" and current.sticky != enabled:
            raise SwayPluginError("postcondition_failed", "window sticky state did not change", {"con_id": node.id})
        elif action == "mark" and mark not in current.marks:
            raise SwayPluginError("postcondition_failed", "mark was not applied", {"con_id": node.id, "mark": mark})
        elif action == "unmark" and mark in current.marks:
            raise SwayPluginError("postcondition_failed", "mark was not removed", {"con_id": node.id, "mark": mark})
        return {"con_id": node.id, "action": action, "warnings": warnings}
    def workspace(self, action: str, workspace: object, **arguments: Any) -> dict[str, Any]:
        """Apply one workspace mutation and verify it from a fresh tree."""
        if not isinstance(workspace, str) or not workspace:
            raise SwayPluginError("invalid_argument", "workspace must be a non-empty string")
        before = self._snapshot()
        existing = {item.name: item for item in before.workspaces()}
        warnings: list[str] = []
        result_workspace = workspace
        prior_focus = before.focused_workspace
        output: str | None = None
        restore_focus = False
        if action == "focus_or_create":
            command = f"workspace {commands.quote(workspace)}"
            self._run(command)
        elif action == "rename":
            new_name = arguments.get("new_name")
            if workspace not in existing:
                raise SwayPluginError("target_not_found", "workspace does not currently exist", {"workspace": workspace})
            if not isinstance(new_name, str) or not new_name:
                raise SwayPluginError("invalid_argument", "new_name must be a non-empty string")
            if new_name in existing:
                raise SwayPluginError("precondition_failed", "a workspace already has the new name", {"workspace": new_name})
            result_workspace = new_name
            self._run(f"rename workspace {commands.quote(workspace)} to {commands.quote(new_name)}")
        elif action == "move_to_output":
            output = arguments.get("output")
            restore_focus = arguments.get("restore_focus", True)
            if workspace not in existing:
                raise SwayPluginError("target_not_found", "workspace does not currently exist", {"workspace": workspace})
            if not isinstance(output, str) or not output:
                raise SwayPluginError("invalid_argument", "output must be a non-empty string")
            if not isinstance(restore_focus, bool):
                raise SwayPluginError("invalid_argument", "restore_focus must be a boolean")
            self._run(f"workspace {commands.quote(workspace)}; move workspace to output {commands.quote(output)}")
            if restore_focus and prior_focus is not None and prior_focus != workspace:
                self._run(f"workspace {commands.quote(prior_focus)}")
        else:
            raise SwayPluginError("invalid_argument", "unsupported workspace action", {"action": action})

        after = self._post_snapshot()
        after_workspaces = {item.name: item for item in after.workspaces()}
        current = after_workspaces.get(result_workspace)
        if action == "focus_or_create" and after.focused_workspace != workspace:
            raise SwayPluginError("postcondition_failed", "workspace did not become focused", {"workspace": workspace})
        if action == "rename" and (current is None or workspace in after_workspaces):
            raise SwayPluginError("postcondition_failed", "workspace was not renamed", {"workspace": workspace, "new_name": result_workspace})
        if action == "move_to_output" and (current is None or current.output != output):
            raise SwayPluginError("postcondition_failed", "workspace did not move to the requested output", {"workspace": workspace, "output": output})
        if action == "move_to_output" and restore_focus and prior_focus is not None and prior_focus != workspace and after.focused_workspace != prior_focus:
            raise SwayPluginError("postcondition_failed", "prior workspace focus was not restored", {"workspace": prior_focus})
        return {"workspace": result_workspace, "action": action, "warnings": warnings}


__all__ = ["RuntimeService"]
