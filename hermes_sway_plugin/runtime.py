"""Verified runtime mutations over an injected Sway IPC-like client."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from . import commands, ipc, tree
from .errors import SwayPluginError
from .resolve import resolve_target

CLOSE_VERIFY_SECONDS = 2.0
CLOSE_POLL_SECONDS = 0.1
RESERVED_WORKSPACE_SELECTORS = frozenset(
    {
        "next",
        "prev",
        "next_on_output",
        "prev_on_output",
        "current",
        "back_and_forth",
        "number",
    }
)


def _exact_workspace_name(value: object, argument: str) -> str:
    if not isinstance(value, str) or not value:
        raise SwayPluginError("invalid_argument", f"{argument} must be a non-empty string")
    if value.casefold() in RESERVED_WORKSPACE_SELECTORS:
        raise SwayPluginError(
            "invalid_argument",
            f"{argument} must not be a reserved Sway workspace selector",
            {argument: value},
        )
    return value


def _reject_workspace_case_collision(name: str, existing_names: set[str]) -> None:
    collision = next(
        (
            existing_name
            for existing_name in existing_names
            if existing_name != name and existing_name.casefold() == name.casefold()
        ),
        None,
    )
    if collision is not None:
        raise SwayPluginError(
            "precondition_failed",
            "workspace name collides case-insensitively with an existing workspace",
            {"workspace": name, "existing_workspace": collision},
        )


class RuntimeService:
    """Execute one typed mutation against fresh pre- and post-command trees."""

    def __init__(
        self,
        client: Any,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        close_verify_seconds: float = CLOSE_VERIFY_SECONDS,
        close_poll_seconds: float = CLOSE_POLL_SECONDS,
    ) -> None:
        self._client = client
        self._monotonic = monotonic
        self._sleep = sleep
        self._close_verify_seconds = close_verify_seconds
        self._close_poll_seconds = close_poll_seconds

    def _snapshot(self) -> tree.Snapshot:
        ipc.assert_sway_19(self._client.request(ipc.GET_VERSION))
        return tree.build_snapshot(self._client.request(ipc.GET_TREE))

    def _post_snapshot(self) -> tree.Snapshot:
        return tree.build_snapshot(self._client.request(ipc.GET_TREE))

    def _wait_until_absent(self, con_id: int) -> bool:
        """Poll fresh trees until a killed window is gone, or the deadline passes.

        Sway's ``kill`` requests that the client close the view. The window can
        remain briefly, indefinitely, or disappear asynchronously after the reply.
        """

        deadline = self._monotonic() + self._close_verify_seconds
        while True:
            if self._current_window(self._post_snapshot(), con_id) is None:
                return True
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            self._sleep(min(self._close_poll_seconds, remaining))

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
            if not isinstance(layout, str) or layout not in {"default", "splith", "splitv", "stacking", "tabbed"}:
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
            # Sway's ``layout`` command operates on the selected container's
            # parent. Select the target itself for both nested and workspace-parent
            # cases; selecting the parent would change one level too high.
            self._run(f"{commands.criterion_for_con_id(node.id)} layout {layout}")
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
                    {
                        "con_id": node.id,
                        "layout": layout,
                        "observed_layout": current_parent.layout,
                        "observed_parent_con_id": current_parent.id,
                    },
                )
            return {
                "action": action,
                "con_id": node.id,
                "parent_con_id": current_parent.id,
                "layout": layout,
                "warnings": warnings,
            }

        if action == "split_at":
            orientation = arguments.get("orientation")
            if not isinstance(orientation, str) or orientation not in {"horizontal", "vertical"}:
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
        workspace = (
            _exact_workspace_name(arguments.get("workspace"), "workspace")
            if action == "move_to_workspace"
            else None
        )
        before = self._snapshot()
        node = resolve_target(before, target, window_only=True)
        criterion = commands.criterion_for_con_id(node.id)
        warnings: list[str] = []
        output: str | None = None
        enabled: bool | None = None
        width: int | None = None
        height: int | None = None
        unit: str | None = None
        position: Mapping[str, Any] | None = None
        expected_position: tuple[int, int] | None = None
        mark: str | None = None
        if action == "focus":
            command = f"{criterion} focus"
        elif action == "move_to_workspace":
            assert workspace is not None
            _reject_workspace_case_collision(workspace, {item.name for item in before.workspaces()})
            command = f"{criterion} move --no-auto-back-and-forth container to workspace {commands.quote(workspace)}"
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
                if (
                    not isinstance(x, int)
                    or isinstance(x, bool)
                    or not isinstance(y, int)
                    or isinstance(y, bool)
                ):
                    raise SwayPluginError("invalid_argument", "position coordinates must be integers")
                x_value, y_value = x, y
                absolute = candidate.get("absolute", False)
                if not isinstance(absolute, bool):
                    raise SwayPluginError("invalid_argument", "position.absolute must be a boolean")
                position = candidate
                if absolute:
                    expected_position = (x_value, y_value)
                    command = f"{criterion} move absolute position {x_value} px {y_value} px"
                else:
                    workspace_name = current_before.workspace or before.focused_workspace
                    workspace_node = next(
                        (
                            item
                            for item in before.nodes.values()
                            if item.type == "workspace" and item.name == workspace_name
                        ),
                        None,
                    )
                    if workspace_node is None or workspace_node.rect is None:
                        raise SwayPluginError(
                            "precondition_failed",
                            "relative position requires an observable workspace origin",
                            {"con_id": node.id, "workspace": workspace_name},
                        )
                    expected_position = (
                        workspace_node.rect.x + x_value,
                        workspace_node.rect.y + y_value,
                    )
                    command = f"{criterion} move position {x_value} px {y_value} px"
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
        if action == "close":
            closed = self._wait_until_absent(node.id)
            if not closed:
                warnings.append("close_requested_but_window_still_observed")
            return {
                "con_id": node.id,
                "action": action,
                "close_requested": True,
                "closed_observed": closed,
                "warnings": warnings,
            }
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
        elif action == "position" and expected_position is not None:
            if (
                current.rect is None
                or current.rect.x != expected_position[0]
                or current.rect.y != expected_position[1]
            ):
                raise SwayPluginError(
                    "postcondition_failed",
                    "window position did not reach the requested coordinates",
                    {
                        "con_id": node.id,
                        "expected": {"x": expected_position[0], "y": expected_position[1]},
                        "observed": current.rect.compact() if current.rect else None,
                    },
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
        result = {"con_id": node.id, "action": action, "warnings": warnings}
        if action in {"resize", "position"}:
            result["observed"] = {
                "rect": current.rect.compact() if current.rect is not None else None,
            }
        if action == "resize":
            result["requested"] = {"width": width, "height": height, "unit": unit}
        return result

    def workspace(self, action: str, workspace: object, **arguments: Any) -> dict[str, Any]:
        """Apply one workspace mutation and verify it from a fresh tree."""
        workspace = _exact_workspace_name(workspace, "workspace")
        new_name = (
            _exact_workspace_name(arguments.get("new_name"), "new_name")
            if action == "rename"
            else None
        )
        before = self._snapshot()
        existing = {item.name: item for item in before.workspaces()}
        existing_names = set(existing)
        existing_casefolded = {name.casefold() for name in existing_names}
        _reject_workspace_case_collision(workspace, existing_names)
        warnings: list[str] = []
        result_workspace = workspace
        prior_focus = before.focused_workspace
        output: str | None = None
        restore_focus = False
        if action == "focus_or_create":
            command = f"workspace --no-auto-back-and-forth {commands.quote(workspace)}"
            self._run(command)
        elif action == "rename":
            assert new_name is not None
            if workspace not in existing:
                raise SwayPluginError("target_not_found", "workspace does not currently exist", {"workspace": workspace})
            if new_name.casefold() in existing_casefolded:
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
            self._run(
                f"workspace --no-auto-back-and-forth {commands.quote(workspace)}; "
                f"move workspace to output {commands.quote(output)}"
            )
            if restore_focus and prior_focus is not None and prior_focus != workspace:
                self._run(f"workspace --no-auto-back-and-forth {commands.quote(prior_focus)}")
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
