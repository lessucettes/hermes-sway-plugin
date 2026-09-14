#!/usr/bin/env python3
"""Exercise mutating plugin behavior in an isolated real Sway 1.9 session."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hermes_sway_plugin import ipc, persistent, tree  # noqa: E402
from hermes_sway_plugin.runtime import RuntimeService  # noqa: E402


def wait_for(predicate, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.05)
    raise AssertionError(f"condition was not met within {timeout}s; last={last!r}")


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def stop_process(process: subprocess.Popen, timeout: float = 5.0) -> None:
    """Terminate and reap one process, escalating to kill when necessary."""
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
    assert process.poll() is not None


def main() -> int:
    required = ("sway", "xmessage")
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        print(json.dumps({"ok": False, "skipped": True, "missing": missing}))
        return 77

    checks: list[dict[str, object]] = []

    def record(name: str, **details: object) -> None:
        checks.append({"name": name, "ok": True, **details})

    with tempfile.TemporaryDirectory(prefix="hermes-sway-it-") as temporary:
        root = Path(temporary)
        runtime = root / "runtime"
        home = root / "home"
        xdg_config = root / "config"
        xdg_cache = root / "cache"
        xdg_data = root / "data"
        xdg_state = root / "state"
        config_dir = xdg_config / "sway"
        for directory in (
            runtime,
            home,
            xdg_config,
            xdg_cache,
            xdg_data,
            xdg_state,
            config_dir,
        ):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)

        env_file = root / "session.env"
        startup_marker = root / "startup.marker"
        rules_file = config_dir / "hermes-sway-plugin-rules.conf"
        config_file = config_dir / "config"
        log_file = root / "sway.log"
        config_file.write_text(
            "\n".join(
                [
                    "xwayland enable",
                    "focus_follows_mouse no",
                    "default_border pixel 1",
                    f"include {rules_file}",
                    "workspace 1",
                    f"exec /bin/sh -c {shlex.quote(f'env > {env_file}')}",
                    f"exec /usr/bin/touch {startup_marker}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        compositor_env = os.environ.copy()
        for key in (
            "SWAYSOCK",
            "I3SOCK",
            "WAYLAND_DISPLAY",
            "DISPLAY",
            "DBUS_SESSION_BUS_ADDRESS",
        ):
            compositor_env.pop(key, None)
        compositor_env.update(
            {
                "HOME": str(home),
                "XDG_RUNTIME_DIR": str(runtime),
                "XDG_CONFIG_HOME": str(xdg_config),
                "XDG_CACHE_HOME": str(xdg_cache),
                "XDG_DATA_HOME": str(xdg_data),
                "XDG_STATE_HOME": str(xdg_state),
                "WLR_BACKENDS": "headless",
                "WLR_HEADLESS_OUTPUTS": "2",
                "WLR_LIBINPUT_NO_DEVICES": "1",
                "WLR_RENDERER": "pixman",
                "WLR_NO_HARDWARE_CURSORS": "1",
            }
        )

        children: list[subprocess.Popen] = []
        sway_process: subprocess.Popen | None = None
        log_handle = None
        try:
            log_handle = log_file.open("w", encoding="utf-8")
            sway_process = subprocess.Popen(
                ["sway", "-c", str(config_file), "-d"],
                env=compositor_env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

            wait_for(env_file.is_file)
            session_env = compositor_env | parse_env(env_file)
            socket_path = Path(session_env["SWAYSOCK"])
            assert socket_path.is_relative_to(runtime), socket_path
            wait_for(socket_path.exists)
            client = ipc.SwayIPC(socket_path=str(socket_path), timeout=3.0)
            version = client.request(ipc.GET_VERSION)
            ipc.assert_sway_19(version)
            record("isolated Sway 1.9", socket=str(socket_path))
            wait_for(startup_marker.exists)
            record("startup exec ran")

            def snapshot() -> tree.Snapshot:
                return tree.build_snapshot(client.request(ipc.GET_TREE))

            def window_named(title: str):
                return next(
                    (item for item in snapshot().windows(True) if item.title == title),
                    None,
                )

            def launch_xmessage(title: str) -> subprocess.Popen:
                process = subprocess.Popen(
                    ["xmessage", "-title", title, "-buttons", "close:0", "fixture"],
                    env=session_env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                children.append(process)
                return process

            launch_xmessage("hermes-it-one")
            first = wait_for(lambda: window_named("hermes-it-one"))
            service = RuntimeService(client)
            service.window({"con_id": first.con_id}, "set_floating", enabled=True)
            resized = service.window(
                {"con_id": first.con_id}, "resize", width=420, height=240, unit="px"
            )
            assert resized["observed"]["rect"]["width"] > 0
            service.window(
                {"con_id": first.con_id},
                "position",
                position={"mode": "coordinates", "x": 20, "y": 30},
            )
            service.window({"con_id": first.con_id}, "mark", mark="hermes_it")
            record("window float, resize, position, and mark", con_id=first.con_id)

            service.workspace("focus_or_create", "it-2")
            service.window(
                {"con_id": first.con_id}, "move_to_workspace", workspace="it-2"
            )
            moved = window_named("hermes-it-one")
            assert moved is not None and moved.workspace == "it-2"
            record("workspace create and exact window move")

            launch_xmessage("hermes-it-two")
            second = wait_for(lambda: window_named("hermes-it-two"))
            layout_result = service.layout(
                "set_parent_layout", {"con_id": second.con_id}, layout="tabbed"
            )
            assert layout_result["layout"] == "tabbed"
            record("real parent tabbed layout", parent=layout_result["parent_con_id"])

            def run_in_session(*args, **kwargs):
                kwargs["env"] = session_env
                return subprocess.run(*args, **kwargs)

            store = persistent.ManagedRuleStore(config_dir)
            created = store.add(
                {
                    "rule_id": "integration-placement",
                    "kind": "window",
                    "match": {"title": {"value": "hermes-it-rule"}},
                    "intended_cardinality": "many",
                    "destination": {"workspace": "it-9"},
                    "effects": {"floating": True},
                },
                subprocess_run=run_in_session,
                backup_count=2,
            )
            assert created["rule_id"] == "integration-placement"
            client.command("reload")
            launch_xmessage("hermes-it-rule")
            ruled = wait_for(lambda: window_named("hermes-it-rule"))
            assert ruled.workspace == "it-9"
            assert ruled.floating is True
            record("persistent assign and effect after reload", con_id=ruled.con_id)

            previous = rules_file.read_text(encoding="utf-8")
            write = store.write([], subprocess_run=run_in_session, backup_count=2)
            assert rules_file.read_text(encoding="utf-8") != previous
            persistent.restore_atomic_write(write)
            assert rules_file.read_text(encoding="utf-8") == previous
            record("managed file rollback restores exact prior content")

            for title in ("hermes-it-rule", "hermes-it-two", "hermes-it-one"):
                current = window_named(title)
                if current is not None:
                    result = service.window(
                        {"con_id": current.con_id}, "close", confirm_close=True
                    )
                    assert result["close_requested"] is True
            record("client close requests completed")
        finally:
            for child in children:
                stop_process(child)
            if sway_process is not None:
                stop_process(sway_process, timeout=10.0)
            if log_handle is not None and not log_handle.closed:
                log_handle.close()

            assert all(child.poll() is not None for child in children)
            assert sway_process is None or sway_process.poll() is not None
            record(
                "child and compositor cleanup completed",
                child_count=len(children),
                children_stopped=all(child.poll() is not None for child in children),
                compositor_stopped=sway_process is None
                or sway_process.poll() is not None,
            )

    print(json.dumps({"ok": True, "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
