"""Sway criteria rendering is exact by default and explicit for regexes."""

from __future__ import annotations

import re

import pytest

from hermes_sway_plugin.persistent import CriteriaError, render_criteria


def test_exact_criteria_are_anchored_and_escape_pcre_metacharacters():
    rendered = render_criteria(
        {
            "title": {"value": 'A/B (draft).txt'},
            "app_id": {"value": "org.example.App"},
        }
    )

    assert rendered == '[app_id="^org\\\\.example\\\\.App$" title="^A/B \\\\(draft\\\\)\\\\.txt$"]'
    assert re.fullmatch(r"org\.example\.App", "org.example.App")
    assert not re.fullmatch(r"org\.example\.App", "orgXexampleYApp")


def test_regex_criteria_are_unanchored_but_sway_quoted():
    assert render_criteria({"title": {"value": r"^draft\d+$", "mode": "regex"}}) == (
        '[title="^draft\\\\d+$"]'
    )


def test_window_type_uses_sways_literal_enum_syntax():
    assert render_criteria({"window_type": {"value": "dialog"}}) == '[window_type="dialog"]'
    with pytest.raises(CriteriaError, match="window_type.*regex"):
        render_criteria({"window_type": {"value": "dialog|utility", "mode": "regex"}})


def test_criteria_rejects_unknown_keys_and_unsafe_line_breaks():
    with pytest.raises(CriteriaError, match="unsupported"):
        render_criteria({"workspace": {"value": "1"}})
    with pytest.raises(CriteriaError, match="line break"):
        render_criteria({"title": {"value": "bad\nvalue"}})
