"""Hermes tool handlers: argument validation and JSON-string results."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .errors import SwayPluginError, error


ConfigGetter = Callable[..., Any]


def _settings(get_config: ConfigGetter) -> Mapping[str, Any]:
    """Read the plugin's own settings namespace once per call."""
    return {
        "ipc_timeout_seconds": get_config("ipc_timeout_seconds", 3.0),
        "reload_timeout_seconds": get_config("reload_timeout_seconds", 5.0),
        "launch_timeout_seconds": get_config("launch_timeout_seconds", 10.0),
        "config_dir": get_config("config_dir", ""),
        "backup_keep": get_config("backup_keep", 10),
    }


def _require(args: Mapping[str, Any], key: str) -> Any:
    if key not in args or args[key] in (None, ""):
        raise SwayPluginError("invalid_argument", f"missing required argument: {key}", {"argument": key})
    return args[key]


def sway_inspect(args: Mapping[str, Any], get_config: ConfigGetter, **kwargs: Any) -> str:
    raise SwayPluginError(
        "internal_error",
        "sway_inspect is not implemented yet",
        {},
        recoverable=False,
    )


def _not_implemented(tool: str) -> Callable[..., str]:
    def handler(args: Mapping[str, Any], get_config: ConfigGetter, **kwargs: Any) -> str:
        raise SwayPluginError("internal_error", f"{tool} is not implemented yet", {}, recoverable=False)

    return handler


def build_handlers(get_config: ConfigGetter) -> dict[str, Callable[..., str]]:
    """Bind every tool handler to the plugin settings getter."""

    def bind(func: Callable[..., str]) -> Callable[[Mapping[str, Any]], str]:
        def bound(args: Mapping[str, Any], **kwargs: Any) -> str:
            try:
                settings = _settings(get_config)
            except SwayPluginError:
                raise
            except Exception as exc:  # settings are caller-supplied; never leak
                return error(SwayPluginError("internal_error", f"cannot read plugin settings: {exc}"))
            try:
                return func(args, settings, **kwargs)
            except SwayPluginError as exc:
                return error(exc)
            except Exception as exc:
                return error(exc)

        return bound

    return {
        "sway_inspect": bind(sway_inspect),
        "sway_window": bind(_not_implemented("sway_window")),
        "sway_workspace": bind(_not_implemented("sway_workspace")),
        "sway_layout": bind(_not_implemented("sway_layout")),
        "sway_launch": bind(_not_implemented("sway_launch")),
        "sway_rule": bind(_not_implemented("sway_rule")),
        "sway_startup": bind(_not_implemented("sway_startup")),
    }

__all__ = ["build_handlers", "sway_inspect", "ConfigGetter"]
