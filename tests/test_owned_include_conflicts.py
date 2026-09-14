"""The plugin's own include line must never be reported as an external conflict.

Regression: the documented setup includes the managed file with an absolute path
or the ``~/.config/sway/hermes/*.conf`` glob.  Both were classified as
``unscannable_include``, so every ``sway_rule`` / ``sway_startup`` write failed
with ``external_conflict`` unless the caller passed
``allow_external_conflicts=true`` for its own configuration.
"""

from __future__ import annotations

from pathlib import Path

from hermes_sway_plugin.persistent import ManagedRuleStore, scan_include_conflicts


def test_absolute_include_of_the_managed_file_is_not_a_conflict(tmp_path):
    main = tmp_path / "config"
    owned = tmp_path / "hermes-sway-plugin-rules.conf"
    main.write_text(f"output * bg #202020 solid_color\ninclude {owned}\n", encoding="utf-8")
    owned.write_text('assign [app_id="^librewolf$"] workspace number 4\n', encoding="utf-8")

    conflicts = scan_include_conflicts(main, managed_include=owned)

    assert conflicts == ()
    store = ManagedRuleStore(str(tmp_path))
    assert store._conflicts({"kind": "window"}) == ()


def test_glob_include_of_the_managed_directory_is_not_a_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    directory = tmp_path / ".config" / "sway" / "hermes"
    directory.mkdir(parents=True)
    owned = directory / "hermes-sway-plugin-rules.conf"
    owned.write_text('assign [app_id="^librewolf$"] workspace number 4\n', encoding="utf-8")
    main = tmp_path / "config"
    main.write_text("include ~/.config/sway/hermes/*.conf\n", encoding="utf-8")

    assert scan_include_conflicts(main, managed_include=owned) == ()


def test_include_glob_star_does_not_cross_a_path_separator(tmp_path):
    directory = tmp_path / "hermes"
    owned = directory / "nested" / "hermes-sway-plugin-rules.conf"
    owned.parent.mkdir(parents=True)
    owned.write_text("", encoding="utf-8")
    main = tmp_path / "config"
    main.write_text(f"include {directory}/*.conf\n", encoding="utf-8")

    conflicts = scan_include_conflicts(main, managed_include=owned)

    assert [conflict.kind for conflict in conflicts] == ["unscannable_include"]


def test_an_unrelated_absolute_include_still_reports_unscannable(tmp_path):
    main = tmp_path / "config"
    owned = tmp_path / "hermes-sway-plugin-rules.conf"
    other = tmp_path / "elsewhere" / "other.conf"
    other.parent.mkdir()
    other.write_text("for_window [app_id=\"x\"] floating enable\n", encoding="utf-8")
    main.write_text(f"include {other}\n", encoding="utf-8")

    conflicts = scan_include_conflicts(main, managed_include=owned)

    assert [conflict.kind for conflict in conflicts] == ["unscannable_include"]


def test_the_store_ignores_both_owned_includes_and_their_statements(tmp_path):
    config_dir = tmp_path / "sway"
    config_dir.mkdir()
    (config_dir / "config").write_text(
        f"include {config_dir / 'hermes-sway-plugin-rules.conf'}\n"
        f"include {config_dir / 'hermes-sway-plugin-startup.conf'}\n",
        encoding="utf-8",
    )
    (config_dir / "hermes-sway-plugin-rules.conf").write_text(
        'for_window [app_id="^owned$"] floating enable\n', encoding="utf-8"
    )

    conflicts = ManagedRuleStore(str(config_dir))._conflicts({"kind": "window"})

    # Owned statements are managed by the store itself, not external conflicts.
    assert conflicts == ()
