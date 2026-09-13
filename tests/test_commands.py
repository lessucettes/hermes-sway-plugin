"""Typed Sway 1.9 command builders and command-reply validation."""

from __future__ import annotations

import pytest

from hermes_sway_plugin.commands import (
    command_or_raise,
    criterion_for_con_id,
    mark_name,
    quote,
)
from hermes_sway_plugin.errors import SwayPluginError


def test_quotes_spaces_quotes_and_backslashes_for_sway_scalars():
    assert quote("work one") == '"work one"'
    assert quote('say "hello"') == '"say \\"hello\\""'
    assert quote(r"C:\path\file") == '"C:\\\\path\\\\file"'
    with pytest.raises(SwayPluginError):
        quote("line\nbreak")


def test_builds_numeric_con_id_criteria_without_interpolation():
    assert criterion_for_con_id(42) == "[con_id=42]"
    with pytest.raises(SwayPluginError):
        criterion_for_con_id("42")
    with pytest.raises(SwayPluginError):
        criterion_for_con_id(-1)


def test_validates_mark_names_against_the_public_contract():
    assert mark_name("chat.role-1") == "chat.role-1"
    for invalid in ("", "spaces are bad", "slash/no", "x" * 65):
        with pytest.raises(SwayPluginError):
            mark_name(invalid)


def test_accepts_all_successful_run_command_replies():
    reply = [{"success": True}, {"success": True}]
    assert command_or_raise("focus", reply) == reply


def test_rejects_partial_command_failure_with_a_bounded_error():
    with pytest.raises(SwayPluginError) as excinfo:
        command_or_raise("move container", [{"success": True}, {"success": False, "error": "x" * 3000}])
    assert excinfo.value.code == "command_rejected"
    assert len(excinfo.value.details["sway_error"]) <= 2000


def test_rejects_malformed_command_reply():
    for reply in ({"success": True}, [], [{"success": "yes"}], ["wrong"]):
        with pytest.raises(SwayPluginError) as excinfo:
            command_or_raise("focus", reply)
        assert excinfo.value.code == "ipc_protocol_error"
