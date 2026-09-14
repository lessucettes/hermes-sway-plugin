"""Normalize raw Sway 1.9 IPC payloads into compact, immutable summaries."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Optional

SYNTHETIC_OUTPUT = "__i3"
SCRATCHPAD_OUTPUT = "__i3_scratch"


class TreeFormatError(Exception):
    """A required tree field is missing or malformed."""


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def compact(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class NodeSummary:
    id: int
    type: str
    name: Optional[str]
    layout: str
    parent_id: Optional[int]
    workspace: Optional[str]
    workspace_number: Optional[int]
    output: Optional[str]
    focused: bool
    visible: bool
    urgent: bool
    floating: bool
    fullscreen_mode: int
    sticky: bool
    marks: tuple[str, ...]
    rect: Optional[Rect]
    app_id: Optional[str]
    window: Optional[int]
    window_role: Optional[str]
    window_type: Optional[str]
    shell: Optional[str]
    x11_class: Optional[str]
    x11_instance: Optional[str]
    pid: Optional[int]
    child_ids: tuple[int, ...]
    ancestor_ids: tuple[int, ...]

    @property
    def is_window(self) -> bool:
        # A native xdg-shell view may map before it publishes an app_id. Sway's
        # non-null view shell is still authoritative window evidence.
        return (
            self.window is not None
            or self.app_id is not None
            or self.x11_class is not None
            or self.shell in {"xdg_shell", "xwayland"}
        )

    @property
    def in_scratchpad(self) -> bool:
        return self.workspace == "__i3_scratch" or self.output == SCRATCHPAD_OUTPUT

    def compact(self) -> dict:
        payload: dict[str, Any] = {
            "con_id": self.id,
            "type": self.type,
            "layout": self.layout,
            "focused": self.focused,
            "floating": self.floating,
        }
        if self.name is not None:
            payload["name"] = self.name
        if self.workspace is not None:
            payload["workspace"] = self.workspace
        if self.output is not None:
            payload["output"] = self.output
        if self.marks:
            payload["marks"] = list(self.marks)
        if self.app_id is not None:
            payload["app_id"] = self.app_id
        if self.x11_class is not None:
            payload["class"] = self.x11_class
        if self.window is not None:
            payload["window"] = self.window
        return payload


@dataclass(frozen=True)
class WindowSummary:
    con_id: int
    title: Optional[str]
    app_id: Optional[str]
    x11_class: Optional[str]
    x11_instance: Optional[str]
    window_role: Optional[str]
    window_type: Optional[str]
    shell: Optional[str]
    pid: Optional[int]
    workspace: Optional[str]
    output: Optional[str]
    floating: bool
    fullscreen: bool
    sticky: bool
    focused: bool
    urgent: bool
    marks: tuple[str, ...]
    rect: Optional[Rect]
    parent_layout: str
    scratchpad: bool

    def compact(self, include_geometry: bool = True) -> dict:
        payload: dict[str, Any] = {
            "con_id": self.con_id,
            "title": self.title,
            "app_id": self.app_id,
            "class": self.x11_class,
            "instance": self.x11_instance,
            "window_role": self.window_role,
            "window_type": self.window_type,
            "shell": self.shell,
            "pid": self.pid,
            "workspace": self.workspace,
            "output": self.output,
            "floating": self.floating,
            "fullscreen": self.fullscreen,
            "sticky": self.sticky,
            "focused": self.focused,
            "urgent": self.urgent,
            "marks": list(self.marks),
            "parent_layout": self.parent_layout,
            "scratchpad": self.scratchpad,
        }
        if include_geometry and self.rect is not None:
            payload["rect"] = self.rect.compact()
        return payload


@dataclass(frozen=True)
class WorkspaceState:
    """Live workspace flags from ``GET_WORKSPACES``.

    Sway 1.9 does not include ``visible``/``focused`` on workspace nodes in
    ``GET_TREE``, so these fields are the authoritative source for those flags.
    """

    name: str
    visible: bool
    focused: bool
    urgent: bool
    output: Optional[str] = None
    num: Optional[int] = None
    layout: Optional[str] = None
    rect: Optional[Rect] = None


def parse_workspace_states(reply: object) -> dict[str, WorkspaceState]:
    """Parse a ``GET_WORKSPACES`` reply into per-name live workspace state."""

    if not isinstance(reply, list):
        raise TreeFormatError("GET_WORKSPACES reply is not a list")
    states: dict[str, WorkspaceState] = {}
    for entry in reply:
        if not isinstance(entry, dict):
            raise TreeFormatError("GET_WORKSPACES entry is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise TreeFormatError("GET_WORKSPACES entry has no usable name")
        raw_num = entry.get("num")
        states[name] = WorkspaceState(
            name=name,
            visible=bool(entry.get("visible")),
            focused=bool(entry.get("focused")),
            urgent=bool(entry.get("urgent")),
            output=entry.get("output") if isinstance(entry.get("output"), str) else None,
            num=raw_num if isinstance(raw_num, int) and not isinstance(raw_num, bool) else None,
            layout=entry.get("layout") if isinstance(entry.get("layout"), str) else None,
            rect=_rect(entry.get("rect")),
        )
    return states


@dataclass(frozen=True)
class WorkspaceSummary:
    name: str
    num: Optional[int]
    output: Optional[str]
    visible: bool
    focused: bool
    urgent: bool
    layout: str
    rect: Optional[Rect]
    window_count: int

    def compact(self, include_geometry: bool = True) -> dict:
        payload: dict[str, Any] = {
            "name": self.name,
            "num": self.num,
            "output": self.output,
            "visible": self.visible,
            "focused": self.focused,
            "urgent": self.urgent,
            "layout": self.layout,
            "window_count": self.window_count,
        }
        if include_geometry and self.rect is not None:
            payload["rect"] = self.rect.compact()
        return payload


@dataclass(frozen=True)
class OutputSummary:
    name: str
    active: bool
    primary: bool
    make: Optional[str]
    model: Optional[str]
    serial: Optional[str]
    current_mode: Optional[dict]
    rect: Optional[Rect]
    focused: bool
    workspaces: tuple[str, ...]

    @property
    def hardware_identifier(self) -> Optional[str]:
        parts = [part for part in (self.make, self.model, self.serial) if part]
        return " ".join(parts) if parts else None

    def compact(self, include_geometry: bool = True) -> dict:
        payload: dict[str, Any] = {
            "name": self.name,
            "active": self.active,
            "primary": self.primary,
            "make": self.make,
            "model": self.model,
            "serial": self.serial,
            "focused": self.focused,
            "workspaces": list(self.workspaces),
        }
        if include_geometry:
            if self.current_mode is not None:
                payload["current_mode"] = self.current_mode
            if self.rect is not None:
                payload["rect"] = self.rect.compact()
        return payload


@dataclass(frozen=True)
class Snapshot:
    nodes: dict[int, NodeSummary] = field(default_factory=dict)
    outputs: tuple[OutputSummary, ...] = ()
    marks: tuple[str, ...] = ()
    focused_window_id: Optional[int] = None
    focused_workspace: Optional[str] = None
    focused_output: Optional[str] = None

    def node(self, con_id: int) -> Optional[NodeSummary]:
        return self.nodes.get(con_id)

    def windows(self, include_scratchpad: bool = False) -> tuple[WindowSummary, ...]:
        collected = []
        for node in self.nodes.values():
            if not node.is_window:
                continue
            window = self._window(node)
            if window.scratchpad and not include_scratchpad:
                continue
            collected.append(window)
        collected.sort(key=lambda window: window.con_id)
        return tuple(collected)

    def workspaces(
        self,
        include_scratchpad: bool = False,
        states: Optional[Mapping[str, WorkspaceState]] = None,
    ) -> tuple[WorkspaceSummary, ...]:
        """Return workspace records, preferring live ``GET_WORKSPACES`` flags.

        ``GET_TREE`` omits ``visible``/``focused`` on workspace nodes in Sway 1.9,
        so any supplied live state overrides those flags instead of reporting a
        misleading ``false``.
        """

        collected = []
        for node in self.nodes.values():
            if node.type != "workspace" or node.name is None:
                continue
            if node.name.startswith(SYNTHETIC_OUTPUT) and not include_scratchpad:
                continue
            window_count = sum(
                1
                for candidate in self.nodes.values()
                if candidate.is_window and candidate.workspace == node.name
            )
            state = (states or {}).get(node.name)
            collected.append(
                WorkspaceSummary(
                    name=node.name,
                    num=node.workspace_number if node.workspace_number is not None else (state.num if state else None),
                    output=node.output if node.output is not None else (state.output if state else None),
                    visible=state.visible if state else node.visible,
                    focused=state.focused if state else node.focused,
                    urgent=state.urgent if state else node.urgent,
                    layout=node.layout,
                    rect=node.rect if node.rect is not None else (state.rect if state else None),
                    window_count=window_count,
                )
            )
        collected.sort(key=lambda workspace: _workspace_sort_key(workspace.num, workspace.name))
        return tuple(collected)

    def focused_window(self) -> Optional[WindowSummary]:
        if self.focused_window_id is None:
            return None
        node = self.nodes.get(self.focused_window_id)
        if node is None or not node.is_window:
            return None
        return self._window(node)

    def ancestors(self, con_id: int) -> tuple[NodeSummary, ...]:
        node = self.nodes.get(con_id)
        if node is None:
            return ()
        return tuple(
            ancestor
            for ancestor_id in node.ancestor_ids
            if (ancestor := self.nodes.get(ancestor_id)) is not None
        )

    def _window(self, node: NodeSummary) -> WindowSummary:
        parent = self.nodes.get(node.parent_id) if node.parent_id is not None else None
        # Floating containers hang off the workspace/output without carrying the
        # workspace themselves, so fall back to the nearest ancestor that does.
        workspace = node.workspace
        output = node.output
        scratchpad = node.in_scratchpad
        for ancestor_id in node.ancestor_ids:
            ancestor = self.nodes.get(ancestor_id)
            if ancestor is None:
                continue
            if workspace is None and ancestor.workspace is not None:
                workspace = ancestor.workspace
            if output is None and ancestor.output is not None:
                output = ancestor.output
            scratchpad = scratchpad or ancestor.in_scratchpad
        return WindowSummary(
            con_id=node.id,
            title=node.name,
            app_id=node.app_id,
            x11_class=node.x11_class,
            x11_instance=node.x11_instance,
            window_role=node.window_role,
            window_type=node.window_type,
            shell=node.shell,
            pid=node.pid,
            workspace=workspace,
            output=output,
            floating=node.floating,
            fullscreen=node.fullscreen_mode > 0,
            sticky=node.sticky,
            focused=node.focused,
            urgent=node.urgent,
            marks=node.marks,
            rect=node.rect,
            parent_layout=parent.layout if parent is not None else "none",
            scratchpad=scratchpad,
        )


def _workspace_sort_key(num: Optional[int], name: str) -> tuple[int, str]:
    return (num if num is not None else 1 << 30, name)


def _rect(raw: object) -> Optional[Rect]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TreeFormatError("rect is not an object")
    values = []
    for key in ("x", "y", "width", "height"):
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TreeFormatError(f"rect.{key} is not an integer")
        values.append(value)
    return Rect(*values)


def _optional_str(raw: object) -> Optional[str]:
    return raw if isinstance(raw, str) else None


def _optional_int(raw: object) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    return raw if isinstance(raw, int) else None


def _child_list(raw: object, key: str) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TreeFormatError(f"{key} is not a list")
    return raw


def build_snapshot(raw_tree: object) -> Snapshot:
    """Walk a raw ``GET_TREE`` reply into a compact immutable snapshot."""
    if not isinstance(raw_tree, Mapping):
        raise TreeFormatError("GET_TREE reply is not an object")
    nodes: dict[int, NodeSummary] = {}
    focused_window_id: Optional[int] = None
    focused_workspace: Optional[str] = None
    focused_output: Optional[str] = None

    def walk(
        raw: object,
        parent_id: Optional[int],
        workspace: Optional[str],
        workspace_number: Optional[int],
        output: Optional[str],
        floating: bool,
        ancestors: tuple[int, ...],
    ) -> Optional[int]:
        nonlocal focused_window_id, focused_workspace, focused_output
        if not isinstance(raw, Mapping):
            raise TreeFormatError("tree node is not an object")
        con_id = raw.get("id")
        if not isinstance(con_id, int) or isinstance(con_id, bool):
            raise TreeFormatError("tree node is missing an integer id")
        node_type = raw.get("type")
        if not isinstance(node_type, str):
            raise TreeFormatError(f"node {con_id} is missing a string type")
        children = _child_list(raw.get("nodes"), "nodes")
        floating_children = _child_list(raw.get("floating_nodes"), "floating_nodes")

        node_workspace, node_workspace_number = workspace, workspace_number
        node_output = output
        if node_type == "workspace":
            node_workspace = _optional_str(raw.get("name")) or workspace
            node_workspace_number = _optional_int(raw.get("num"))
            if raw.get("focused"):
                focused_workspace = node_workspace
        elif node_type == "output":
            node_output = _optional_str(raw.get("name")) or output
            if raw.get("focused"):
                focused_output = node_output

        properties = raw.get("window_properties")
        if not isinstance(properties, Mapping):
            properties = {}
        is_floating = floating or node_type == "floating_con"
        summary = NodeSummary(
            id=con_id,
            type=node_type,
            name=_optional_str(raw.get("name")),
            layout=_optional_str(raw.get("layout")) or "none",
            parent_id=parent_id,
            workspace=node_workspace,
            workspace_number=node_workspace_number,
            output=node_output,
            focused=bool(raw.get("focused")),
            visible=bool(raw.get("visible")),
            urgent=bool(raw.get("urgent")),
            floating=is_floating,
            fullscreen_mode=_optional_int(raw.get("fullscreen_mode")) or 0,
            sticky=bool(raw.get("sticky")),
            marks=tuple(
                mark for mark in _child_list(raw.get("marks"), "marks") if isinstance(mark, str)
            ),
            rect=_rect(raw.get("rect")),
            app_id=_optional_str(raw.get("app_id")),
            window=_optional_int(raw.get("window")),
            window_role=_optional_str(properties.get("window_role")) or _optional_str(raw.get("window_role")),
            window_type=_optional_str(properties.get("window_type")) or _optional_str(raw.get("window_type")),
            shell=_optional_str(raw.get("shell")),
            x11_class=_optional_str(properties.get("class")) or _optional_str(raw.get("class")),
            x11_instance=_optional_str(properties.get("instance")) or _optional_str(raw.get("instance")),
            pid=_optional_int(raw.get("pid")),
            child_ids=(),
            ancestor_ids=ancestors,
        )
        if summary.is_window and summary.focused:
            focused_window_id = con_id

        child_ids: list[int] = []
        for child in children:
            child_id = walk(
                child,
                con_id,
                node_workspace,
                node_workspace_number,
                node_output,
                is_floating,
                ancestors + (con_id,),
            )
            if child_id is not None:
                child_ids.append(child_id)
        for child in floating_children:
            child_id = walk(
                child,
                con_id,
                node_workspace,
                node_workspace_number,
                node_output,
                True,
                ancestors + (con_id,),
            )
            if child_id is not None:
                child_ids.append(child_id)

        nodes[con_id] = replace(summary, child_ids=tuple(child_ids))
        return con_id

    walk(raw_tree, None, None, None, None, False, ())

    if focused_window_id is not None:
        window_node = nodes[focused_window_id]
        if focused_workspace is None:
            for ancestor_id in window_node.ancestor_ids:
                ancestor = nodes.get(ancestor_id)
                if ancestor is not None and ancestor.workspace is not None:
                    focused_workspace = ancestor.workspace
                    break
        if focused_output is None:
            for ancestor_id in window_node.ancestor_ids:
                ancestor = nodes.get(ancestor_id)
                if ancestor is not None and ancestor.output is not None:
                    focused_output = ancestor.output
                    break

    return Snapshot(
        nodes=nodes,
        marks=tuple(sorted({mark for node in nodes.values() for mark in node.marks})),
        focused_window_id=focused_window_id,
        focused_workspace=focused_workspace,
        focused_output=focused_output,
    )


def parse_outputs(raw_outputs: object) -> tuple[OutputSummary, ...]:
    if not isinstance(raw_outputs, list):
        raise TreeFormatError("GET_OUTPUTS reply is not a list")
    collected = []
    for raw in raw_outputs:
        if not isinstance(raw, Mapping):
            raise TreeFormatError("output entry is not an object")
        name = raw.get("name")
        if not isinstance(name, str):
            raise TreeFormatError("output entry is missing a string name")
        current_mode = raw.get("current_mode")
        current_workspace = raw.get("current_workspace")
        workspaces: tuple[str, ...] = ()
        if isinstance(current_workspace, str) and current_workspace:
            workspaces = (current_workspace,)
        collected.append(
            OutputSummary(
                name=name,
                active=bool(raw.get("active")),
                primary=bool(raw.get("primary")),
                make=_optional_str(raw.get("make")),
                model=_optional_str(raw.get("model")),
                serial=_optional_str(raw.get("serial")),
                current_mode=dict(current_mode) if isinstance(current_mode, Mapping) else None,
                rect=_rect(raw.get("rect")),
                focused=bool(raw.get("focused")),
                workspaces=workspaces,
            )
        )
    collected.sort(key=lambda output: output.name)
    return tuple(collected)


def parse_marks(raw_marks: object) -> tuple[str, ...]:
    if not isinstance(raw_marks, list):
        raise TreeFormatError("GET_MARKS reply is not a list")
    return tuple(sorted(mark for mark in raw_marks if isinstance(mark, str)))


def parse_workspaces(raw_workspaces: object) -> tuple[WorkspaceSummary, ...]:
    if not isinstance(raw_workspaces, list):
        raise TreeFormatError("GET_WORKSPACES reply is not a list")
    collected = []
    for raw in raw_workspaces:
        if not isinstance(raw, Mapping):
            raise TreeFormatError("workspace entry is not an object")
        name = raw.get("name")
        if not isinstance(name, str):
            raise TreeFormatError("workspace entry is missing a string name")
        collected.append(
            WorkspaceSummary(
                name=name,
                num=_optional_int(raw.get("num")),
                output=_optional_str(raw.get("output")),
                visible=bool(raw.get("visible")),
                focused=bool(raw.get("focused")),
                urgent=bool(raw.get("urgent")),
                layout=_optional_str(raw.get("layout")) or "none",
                rect=_rect(raw.get("rect")),
                window_count=0,
            )
        )
    collected.sort(key=lambda workspace: _workspace_sort_key(workspace.num, workspace.name))
    return tuple(collected)


def compact_tree(snapshot: Snapshot, root_id: Optional[int] = None) -> dict:
    """Return a compact hierarchy for ``sway_inspect(view="tree")``."""
    if root_id is None:
        root_id = next(
            (node.id for node in snapshot.nodes.values() if node.parent_id is None), None
        )
    if root_id is None:
        return {"con_id": None, "type": "root", "children": []}

    def render(con_id: int) -> dict:
        node = snapshot.nodes[con_id]
        rendered = node.compact()
        rendered["children"] = [
            render(child) for child in node.child_ids if child in snapshot.nodes
        ]
        return rendered

    return render(root_id)


def iter_ancestors(snapshot: Snapshot, con_id: int) -> Iterable[NodeSummary]:
    return snapshot.ancestors(con_id)
