"""Model-facing JSON schemas for the sway toolset.

Schemas describe intent only; they never contain Sway command strings.
"""

from __future__ import annotations


TARGET_SELECTOR = {
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
        "required": ["view"],
        "additionalProperties": False,
    },
}

SWAY_WINDOW = {
    "name": "sway_window",
    "description": (
        "Mutate exactly one existing window or container in the current Sway session. "
        "Call sway_inspect first and prefer a fresh con_id. Runtime state only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": TARGET_SELECTOR,
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
            "target": TARGET_SELECTOR,
            "other_target": TARGET_SELECTOR,
            "layout": {
                "type": "string",
                "enum": ["default", "splith", "splitv", "stacking", "tabbed"],
            },
            "orientation": {"type": "string", "enum": ["horizontal", "vertical", "none"]},
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
            "timeout_seconds": {"type": "number", "minimum": 0.5, "maximum": 30, "default": 10},
        },
        "required": ["argv"],
        "additionalProperties": False,
    },
}

SWAY_RULE = {
    "name": "sway_rule",
    "description": (
        "Manage autonomous window and workspace-output rules in plugin-owned Sway "
        "configuration. Rules apply to new windows only and keep working without Hermes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "preview", "add", "update", "remove"]},
            "rule_id": {"type": "string"},
            "kind": {"type": "string", "enum": ["window", "workspace_output"]},
            "match": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "mode": {"type": "string", "enum": ["exact", "regex"]},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
            "intended_cardinality": {"type": "string", "enum": ["one", "many"]},
            "allow_unverified_cardinality": {"type": "boolean", "default": False},
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
            "allow_external_conflicts": {"type": "boolean", "default": False},
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
            "startup_id": {"type": "string"},
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "run_on": {
                "type": "string",
                "enum": ["sway_start_only", "sway_start_and_every_reload"],
            },
            "acknowledge_reload_relaunch": {"type": "boolean", "default": False},
            "reload": {"type": "boolean", "default": True},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}


TOOL_SCHEMAS = (
    SWAY_INSPECT,
    SWAY_WINDOW,
    SWAY_WORKSPACE,
    SWAY_LAYOUT,
    SWAY_LAUNCH,
    SWAY_RULE,
    SWAY_STARTUP,
)
