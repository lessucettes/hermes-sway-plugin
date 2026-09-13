"""Native Hermes registration for the sway toolset.

Registers exactly seven tools and the bundled ``sway:sway`` skill. No hooks, no
slash commands, no CLI commands, no background threads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from . import schemas
from .handlers import build_handlers

TOOLSET = "sway"
SKILL_NAME = "sway"
SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / SKILL_NAME / "SKILL.md"
SKILL_DESCRIPTION = (
    "Inspect and control a Sway 1.9 desktop, and persist autonomous window, "
    "workspace-output, and startup configuration that survives without Hermes."
)


def _runtime_available() -> bool:
    """True when a reachable Sway 1.9 socket can be discovered."""
    from .ipc import discover_socket_path, assert_sway_19, SwayIPC

    try:
        socket_path = discover_socket_path()
        ipc = SwayIPC(socket_path=socket_path, timeout=2.0)
        assert_sway_19(ipc.request(7))
    except Exception:
        return False
    return True


def _persistent_available() -> bool:
    """True when the local ``sway`` binary reports version 1.9.

    Persistent configuration can be generated and validated without a running
    session; it only needs the Sway binary for ``sway -C`` validation.
    """
    from .ipc import assert_sway_19, sway_binary_version

    try:
        assert_sway_19(sway_binary_version())
    except Exception:
        return False
    return True


def register(ctx: Any) -> None:
    """Wire the seven sway tools and the bundled skill into Hermes."""
    handlers = build_handlers(ctx.get_config)

    for schema in schemas.TOOL_SCHEMAS:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handlers[name],
            check_fn=_persistent_available if name in ("sway_rule", "sway_startup") else _runtime_available,
            description=schema["description"],
        )

    ctx.register_skill(
        SKILL_NAME,
        SKILL_PATH,
        description=SKILL_DESCRIPTION,
        frontmatter=_skill_frontmatter(),
    )


def _skill_frontmatter() -> dict[str, Any]:
    """Frontmatter for the bundled skill; kept here so the path stays the contract."""
    return {
        "name": SKILL_NAME,
        "description": SKILL_DESCRIPTION,
        "version": "0.1.0",
        "platforms": ["linux"],
        "metadata": {"hermes": {"tags": ["sway", "wayland", "linux", "desktop"]}},
    }


def tool_names() -> Iterable[str]:
    return tuple(schema["name"] for schema in schemas.TOOL_SCHEMAS)


__all__: list[str] = ["register", "tool_names", "TOOLSET", "SKILL_NAME", "SKILL_PATH"]
