"""An empty configured directory must resolve to the documented XDG location."""

from __future__ import annotations

from hermes_sway_plugin import persistent


def test_empty_config_dir_resolves_under_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    paths = persistent.managed_rule_paths("")

    assert paths.config_dir == tmp_path / "xdg" / "sway" / "hermes"
    assert paths.include == paths.config_dir / "hermes-sway-plugin-rules.conf"
    assert paths.main_config == tmp_path / "xdg" / "sway" / "config"


def test_empty_config_dir_falls_back_to_the_home_config_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    startup = persistent.managed_startup_paths(None)

    assert startup.config_dir == tmp_path / "home" / ".config" / "sway" / "hermes"
    assert startup.include == startup.config_dir / "hermes-sway-plugin-startup.conf"


def test_relative_config_dir_is_still_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    for resolver in (persistent.managed_rule_paths, persistent.managed_startup_paths):
        # Both resolver functions share the same directory contract.
        try:
            resolver("relative/path")
        except persistent.ConfigFormatError as exc:
            assert "absolute" in str(exc)
        else:
            raise AssertionError("a relative configuration directory must be refused")
