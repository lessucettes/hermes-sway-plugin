"""Root entry point for the Hermes ``sway`` directory plugin.

The import is deferred so this file also imports cleanly when pytest resolves
it as a top-level module during collection; Hermes itself loads the plugin
with ``spec_from_file_location`` under a package name, where both forms work.
"""


def register(ctx):
    from .hermes_sway_plugin.registration import register as _register

    return _register(ctx)


__all__ = ["register"]
