"""Model-facing JSON schemas for the sway toolset.

Schemas describe intent only; they never contain Sway command strings.
"""

from __future__ import annotations


def _target_selector() -> dict[str, object]:
    return {
        "type": "object",
        "description": (
            "Exactly one selector: {'con_id': int}, {'mark': str}, or {'match': {...}} "
            "with conjunctive exact fields."
        ),
        "properties": {
            "con_id": {"type": "integer", "minimum": 1},
            "mark": {"type": "string"},
            "match": {
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "class": {"type": "string"},
                    "instance": {"type": "string"},
                    "title": {"type": "string"},
                    "pid": {"type": "integer"},
                    "shell": {"type": "string"},
                    "workspace": {"type": "string"},
                    "floating": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


SWAY_INSPECT = {
    "name": "sway_inspect",
    "description": (
        "Inspect the live Sway 1.9 desktop: version, focus, workspaces, outputs, windows, "
        "marks, or a compact normalized tree. Read-only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "view": {
                "type": "string",
                "enum": ["summary", "windows", "workspaces", "outputs", "tree", "marks"],
                "default": "summary",
            },
            "filter": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "output": {"type": "string"},
                    "app_id": {"type": "string"},
                    "class": {"type": "string"},
                    "instance": {"type": "string"},
                    "title_contains": {"type": "string"},
                    "mark": {"type": "string"},
                    "shell": {"type": "string"},
                    "floating": {"type": "boolean"},
                    "focused": {"type": "boolean"},
                    "include_scratchpad": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            "include_geometry": {"type": "boolean", "default": True},
        },
        "required": [],
        "additionalProperties": False,
    },
}

SWAY_WINDOW = {
    "name": "sway_window",
    "description": (
        "Mutate exactly one existing window in the current Sway session. Inspect only "
        "when a unique fresh target is not already known. Runtime state only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": _target_selector(),
            "action": {
                "type": "string",
                "enum": [
                    "focus",
                    "move_to_workspace",
                    "move_to_output",
                    "move_direction",
                    "set_floating",
                    "set_fullscreen",
                    "resize",
                    "position",
                    "move_to_scratchpad",
                    "show_from_scratchpad",
                    "set_sticky",
                    "mark",
                    "unmark",
                    "close",
                ],
            },
            "workspace": {"type": "string"},
            "output": {"type": "string"},
            "direction": {"type": "string", "enum": ["left", "right", "up", "down"]},
            "enabled": {"type": "boolean"},
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
            "unit": {"type": "string", "enum": ["px", "ppt"]},
            "position": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["center", "coordinates"]},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "absolute": {"type": "boolean", "default": False},
                },
                "required": ["mode"],
                "additionalProperties": False,
            },
            "mark": {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{1,64}$"},
            "confirm_close": {"type": "boolean", "default": False},
        },
        "required": ["target", "action"],
        "additionalProperties": False,
    },
}

SWAY_WORKSPACE = {
    "name": "sway_workspace",
    "description": (
        "Runtime workspace operations: focus or create, rename, or move an existing "
        "workspace to another output. Runtime state only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["focus_or_create", "rename", "move_to_output"],
            },
            "workspace": {"type": "string"},
            "new_name": {"type": "string"},
            "output": {"type": "string"},
            "restore_focus": {"type": "boolean", "default": True},
        },
        "required": ["action", "workspace"],
        "additionalProperties": False,
    },
}

SWAY_LAYOUT = {
    "name": "sway_layout",
    "description": (
        "Bounded Sway 1.9 layout primitives: set the parent layout of a container, split "
        "at a container, or swap two containers. No arbitrary relative insertion."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set_parent_layout", "split_at", "swap"]},
            "target": _target_selector(),
            "other_target": _target_selector(),
            "layout": {
                "type": "string",
                "enum": ["default", "splith", "splitv", "stacking", "tabbed"],
            },
            "orientation": {"type": "string", "enum": ["horizontal", "vertical"]},
        },
        "required": ["action", "target"],
        "additionalProperties": False,
    },
}

SWAY_LAUNCH = {
    "name": "sway_launch",
    "description": (
        "Launch one argv-based process in the current session and best-effort correlate "
        "the new window. Association is never guaranteed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "cwd": {"type": "string"},
            "wait_for_window": {"type": "boolean", "default": True},
            "expected_identity": {
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "class": {"type": "string"},
                    "instance": {"type": "string"},
                    "title": {"type": "string"},
                    "shell": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "timeout_seconds": {"type": "number", "minimum": 0.5, "maximum": 30},
        },
        "required": ["argv"],
        "additionalProperties": False,
    },
}

SWAY_RULE = {
    "name": "sway_rule",
    "description": (
        "Manage autonomous window and workspace-output rules in plugin-owned Sway "
        "configuration. Reload does not retrofit unchanged open windows. Rules keep working without Hermes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "preview", "add", "update", "remove"]},
            "rule_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"},
            "kind": {"type": "string", "enum": ["window", "workspace_output"]},
            "match": {
                "type": "object",
                "properties": {
                    "app_id": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "class": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "instance": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "title": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "window_role": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "shell": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "con_mark": {"type": "object", "properties": {"value": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "regex"], "default": "exact"}}, "required": ["value"], "additionalProperties": False},
                    "window_type": {"type": "object", "properties": {"value": {"type": "string", "enum": ["normal", "dialog", "utility", "toolbar", "splash", "menu", "dropdown_menu", "popup_menu", "tooltip", "notification"]}}, "required": ["value"], "additionalProperties": False},
                },
                "additionalProperties": False,
            },
            "intended_cardinality": {"type": "string", "enum": ["one", "many"], "default": "many"},
            "destination": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "output": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "effects": {
                "type": "object",
                "properties": {
                    "floating": {"type": "boolean"},
                    "width_px": {"type": "integer", "minimum": 1},
                    "height_px": {"type": "integer", "minimum": 1},
                    "center": {"type": "boolean"},
                    "fullscreen": {"type": "boolean"},
                    "sticky": {"type": "boolean"},
                    "no_focus": {"type": "boolean"},
                    "border": {
                        "type": "object",
                        "properties": {
                            "style": {"type": "string", "enum": ["none", "normal", "pixel"]},
                            "width": {"type": "integer", "minimum": 0},
                        },
                        "required": ["style"],
                        "additionalProperties": False,
                    },
                    "opacity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "additionalProperties": False,
            },
            "workspace": {"type": "string"},
            "outputs": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "reload": {"type": "boolean", "default": True},

        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

SWAY_STARTUP = {
    "name": "sway_startup",
    "description": (
        "Manage autonomous startup commands in plugin-owned Sway configuration. Ordinary "
        "applications use sway_start_only (Sway exec); reload mode needs explicit consent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "preview", "add", "update", "remove"]},
            "startup_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"},
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "run_on": {
                "type": "string",
                "enum": ["sway_start_only", "sway_start_and_every_reload"],
                "default": "sway_start_only",
            },
            "acknowledge_reload_relaunch": {"type": "boolean", "default": False},
            "reload": {"type": "boolean", "default": True},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}


_PROPERTY_DESCRIPTIONS = {
    "sway_inspect": {
        "view": "Smallest state view needed; omit for focused state and counts.",
        "filter": "Exact window filters; used only with the windows view.",
        "max_results": "Maximum list items returned by bounded views.",
        "include_geometry": "Include window rectangles when geometry matters.",
    },
    "sway_window": {
        "target": "Exactly one live window selector; prefer a fresh con_id when known.",
        "action": "One bounded runtime mutation to apply.",
        "workspace": "Exact destination workspace for move_to_workspace.",
        "output": "Exact output name for move_to_output.",
        "direction": "Direction for move_direction.",
        "enabled": "Desired state for floating, fullscreen, or sticky actions.",
        "width": "Requested width for resize; provide one axis or both.",
        "height": "Requested height for resize; provide one axis or both.",
        "unit": "Resize unit; omit for Sway's contextual default: px when floating, ppt when tiled.",
        "position": "Floating-window position: center or coordinates, optionally global absolute coordinates.",
        "mark": "Session mark to add or remove.",
        "confirm_close": "Must be true for close; Sway requests client closure and observes the result.",
    },
    "sway_workspace": {
        "action": "Focus or create, rename, or move one exact workspace.",
        "workspace": "Exact workspace name, not next/prev command syntax.",
        "new_name": "New exact name required by rename.",
        "output": "Exact connector name required by move_to_output.",
        "restore_focus": "Return focus to the previously focused workspace after moving another workspace.",
    },
    "sway_layout": {
        "action": "Parent-layout, split-orientation, or swap operation.",
        "target": "Exactly one container or window selector.",
        "other_target": "Second exact selector required only by swap.",
        "layout": "Parent layout required only by set_parent_layout.",
        "orientation": "Split orientation required only by split_at.",
    },
    "sway_launch": {
        "argv": "Executable and arguments as an array; never a shell command string.",
        "cwd": "Optional absolute existing working directory.",
        "wait_for_window": "Observe new Sway windows after process start; disable for background commands.",
        "expected_identity": "Optional exact app_id for Wayland or class/instance for XWayland correlation.",
        "timeout_seconds": "Optional correlation timeout; omit to use the plugin setting.",
    },
    "sway_rule": {
        "action": "List/get/preview or mutate one plugin-owned persistent rule.",
        "rule_id": "Stable optional ID for add; required for get, update, and remove.",
        "kind": "Window behavior or workspace-to-output placement.",
        "match": "Restart-stable Sway criteria for a window rule; exact matching is the default.",
        "intended_cardinality": "Expected current match count for advisory diagnostics; defaults to many.",
        "destination": "At most one assignment destination: workspace or output.",
        "effects": "Bounded effects applied when Sway evaluates a matching window rule.",
        "workspace": "Workspace name for workspace_output rules.",
        "outputs": "Ordered output preference list for workspace_output rules.",
        "reload": "Reload the running compositor when its active config includes the managed file.",
    },
    "sway_startup": {
        "action": "List/get/preview or mutate one plugin-owned startup entry.",
        "startup_id": "Stable optional ID for add; required for get, update, and remove.",
        "argv": "Executable and arguments rendered shell-safely into Sway configuration.",
        "run_on": "Start only with Sway by default, or also on every reload with acknowledgement.",
        "acknowledge_reload_relaunch": "Must be true when run_on relaunches the command after every reload.",
        "reload": "Reload the running compositor when its active config includes the managed file.",
    },
}

for _schema in (SWAY_INSPECT, SWAY_WINDOW, SWAY_WORKSPACE, SWAY_LAYOUT, SWAY_LAUNCH, SWAY_RULE, SWAY_STARTUP):
    for _property, _description in _PROPERTY_DESCRIPTIONS[_schema["name"]].items():
        _schema["parameters"]["properties"][_property]["description"] = _description


TOOL_SCHEMAS = (
    SWAY_INSPECT,
    SWAY_WINDOW,
    SWAY_WORKSPACE,
    SWAY_LAYOUT,
    SWAY_LAUNCH,
    SWAY_RULE,
    SWAY_STARTUP,
)
