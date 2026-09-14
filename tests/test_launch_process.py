"""Safe argv process spawning for the Sway launch tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_sway_plugin import launch
from hermes_sway_plugin.errors import SwayPluginError
from hermes_sway_plugin.launch import launch_process


class Process:
    pid = 4242


def test_launches_exact_argv_with_detached_closed_stdio(tmp_path):
    captured = {}

    def factory(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return Process()

    result = launch_process(["kitty", "--title", "chat"], str(tmp_path), factory)

    assert result == {"pid": 4242, "started": True}
    assert captured["argv"] == ["kitty", "--title", "chat"]
    assert captured["cwd"] == str(tmp_path)
    assert captured["shell"] is False
    assert captured["close_fds"] is True
    assert captured["start_new_session"] is True
    assert captured["stdin"] is not None
    assert captured["stdout"] is not None
    assert captured["stderr"] is not None


def test_rejects_invalid_argv_and_relative_or_missing_cwd(tmp_path):
    for argv in ([], [""], ["ok", 1], ["x"] * 65):
        with pytest.raises(SwayPluginError) as excinfo:
            launch_process(argv, None, lambda *a, **kw: Process())
        assert excinfo.value.code == "invalid_argument"

    with pytest.raises(SwayPluginError) as excinfo:
        launch_process(["kitty"], "relative", lambda *a, **kw: Process())
    assert excinfo.value.code == "invalid_argument"

    with pytest.raises(SwayPluginError) as excinfo:
        launch_process(["kitty"], str(tmp_path / "missing"), lambda *a, **kw: Process())
    assert excinfo.value.code == "invalid_argument"


def test_launch_reaps_the_child_when_it_exits(tmp_path):
    import threading

    reaped = threading.Event()

    class ReapableProcess:
        pid = 4242

        def wait(self):
            reaped.set()
            return 0

    launch_process(["true"], str(tmp_path), lambda *args, **kwargs: ReapableProcess())

    assert reaped.wait(1)


def test_partial_proc_ancestry_keeps_the_evidence_already_observed(monkeypatch):
    def read_text(path, **_kwargs):
        if str(path) == "/proc/5000/stat":
            return "5000 (worker) S 4242 0 0 0"
        raise FileNotFoundError(str(path))

    monkeypatch.setattr(Path, "read_text", read_text)

    assert launch._proc_ancestor_pids(5000) == (4242,)


def test_maps_executable_and_cwd_os_errors_to_launch_failed(tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("no kitty")

    with pytest.raises(SwayPluginError) as excinfo:
        launch_process(["kitty"], str(tmp_path), missing)
    assert excinfo.value.code == "launch_failed"
    assert "no kitty" in excinfo.value.message


def test_wait_for_window_false_is_process_success_not_window_match(tmp_path):
    result = launch_process(["kitty"], str(tmp_path), lambda *a, **kw: Process())
    assert result["started"] is True
    assert "window" not in result
