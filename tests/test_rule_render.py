"""Declarative window and workspace-output rules render to bounded Sway syntax.

The destination forms and their ordering encode behavior verified against real
Sway 1.9 sessions:

* ``for_window ... move container to workspace`` runs at map time and is regularly
  undone, leaving the window on the focused workspace, so a workspace destination
  is rendered as ``assign``.
* ``move position center`` re-parents a floating container to the focused
  workspace, so when a destination and centering are both requested the
  destination move is re-issued as the last statement of the rule body.
"""

from __future__ import annotations

import pytest

from hermes_sway_plugin.persistent import RuleRenderError, render_rule, render_window_rule, render_workspace_output_rule


def test_window_rule_renders_workspace_destination_as_assign_and_keeps_it_last_when_centered():
    rule = {
        "match": {"app_id": {"value": "org.example.App"}},
        "destination": {"workspace": "2"},
        "effects": {
            "center": True,
            "floating": True,
            "width_px": 800,
            "height_px": 600,
            "border": {"style": "pixel", "width": 2},
            "opacity": 0.75,
        },
    }

    assert render_window_rule(rule) == (
        'assign [app_id="^org\\\\.example\\\\.App$"] workspace number 2\n'
        'for_window [app_id="^org\\\\.example\\\\.App$"] floating enable, '
        'resize set width 800 px, resize set height 600 px, move position center, '
        'move container to workspace number 2, border pixel 2, opacity 0.75'
    )
    assert render_rule({"kind": "window", **rule}) == render_window_rule(rule)


def test_window_rule_keeps_a_named_destination_quoted_in_both_statements():
    rule = {
        "match": {"class": {"value": "TelegramDesktop"}},
        "destination": {"workspace": "chat"},
        "effects": {"floating": True},
    }

    assert render_window_rule(rule) == (
        'assign [class="^TelegramDesktop$"] workspace "chat"\n'
        'for_window [class="^TelegramDesktop$"] floating enable, move container to workspace "chat"'
    )


def test_window_rule_renders_an_output_destination_only_as_a_for_window_move():
    rule = {
        "match": {"app_id": {"value": "org.example.App"}},
        "destination": {"output": "DP-2"},
        "effects": {"center": True, "floating": True},
    }

    assert render_window_rule(rule) == (
        'for_window [app_id="^org\\\\.example\\\\.App$"] floating enable, '
        'move position center, move container to output "DP-2"'
    )


def test_window_rule_without_a_destination_is_a_single_for_window_statement():
    rule = {"match": {"app_id": {"value": "org.example.App"}}, "effects": {"no_focus": True, "opacity": 0.9}}

    rendered = render_window_rule(rule)

    assert "\n" not in rendered
    assert rendered == (
        'for_window [app_id="^org\\\\.example\\\\.App$"] no_focus, opacity 0.9'
    )


def test_window_rule_requires_match_and_an_effect_or_destination():
    with pytest.raises(RuleRenderError, match="match"):
        render_window_rule({"destination": {"workspace": "2"}})
    with pytest.raises(RuleRenderError, match="effect or destination"):
        render_window_rule({"match": {"app_id": {"value": "org.example.App"}}})


def test_workspace_output_rule_requires_workspace_and_unique_outputs():
    rule = {"workspace": "dev", "outputs": ["DP-1", "HDMI-A-1"]}
    assert render_workspace_output_rule(rule) == 'workspace "dev" output "DP-1" "HDMI-A-1"'
    assert render_rule({"kind": "workspace_output", **rule}) == render_workspace_output_rule(rule)

    with pytest.raises(RuleRenderError, match="unique"):
        render_workspace_output_rule({"workspace": "dev", "outputs": ["DP-1", "DP-1"]})
