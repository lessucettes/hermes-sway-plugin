from __future__ import annotations

from pathlib import Path

from hermes_sway_plugin.persistent import scan_include_conflicts


def test_conflict_scan_recurses_only_literal_relative_includes(tmp_path):
    main = tmp_path / "config"
    extra = tmp_path / "extra.conf"
    main.write_text('include extra.conf\ninclude $HOME/unknown\n', encoding="utf-8")
    extra.write_text('for_window [app_id="other"] floating enable\nworkspace "dev" output DP-1\n', encoding="utf-8")

    conflicts = scan_include_conflicts(main, managed_include=tmp_path / "hermes.conf")

    assert [conflict.kind for conflict in conflicts] == ["for_window", "workspace_output", "unscannable_include"]
    assert conflicts[-1].source == main


def test_conflict_scan_ignores_comments_and_the_owned_include(tmp_path):
    main = tmp_path / "config"
    owned = tmp_path / "hermes.conf"
    main.write_text('# include dangerous\ninclude hermes.conf\n', encoding="utf-8")
    owned.write_text('for_window [app_id="owned"] floating enable\n', encoding="utf-8")
    assert scan_include_conflicts(main, managed_include=owned) == ()
