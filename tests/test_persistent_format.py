"""Stable, tamper-evident format for plugin-owned Sway includes."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.persistent import (
    ManualEditRefused,
    parse_managed_config,
    render_managed_config,
)


def test_managed_renderer_is_deterministic_and_parser_preserves_metadata():
    rendered = render_managed_config(
        "for_window [app_id=\"org.example.App\"] move container to workspace \"2\"\n",
        {"rules": ["b", "a"], "format": 1},
    )

    assert rendered == (
        "# hermes-sway-plugin: managed-v1\n"
        '# hermes-sway-plugin: metadata={"format":1,"rules":["b","a"]}\n'
        "# hermes-sway-plugin: sha256=fd35a3d7c9d0e91407674e06527502fc7345c8d1486be155e0666786fb3283cf\n"
        "\n"
        'for_window [app_id="org.example.App"] move container to workspace "2"\n'
    )
    parsed = parse_managed_config(rendered)
    assert parsed.metadata == {"format": 1, "rules": ["b", "a"]}
    assert parsed.body == 'for_window [app_id="org.example.App"] move container to workspace "2"\n'


def test_parser_refuses_manual_edits_to_managed_body():
    rendered = render_managed_config("workspace \"1\" output HDMI-A-1\n", {"format": 1})

    with pytest.raises(ManualEditRefused, match="manual edit"):
        parse_managed_config(rendered.replace("HDMI-A-1", "DP-1"))
