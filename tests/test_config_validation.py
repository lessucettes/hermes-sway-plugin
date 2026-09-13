from __future__ import annotations

from pathlib import Path

import pytest

from hermes_sway_plugin.persistent import ConfigValidationError, validate_candidate_and_main, validate_sway_config


def test_validation_uses_injected_subprocess_without_shell(tmp_path):
    candidate = tmp_path / "candidate.conf"
    candidate.write_text("# candidate\n", encoding="utf-8")
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = validate_sway_config(candidate, runner)
    assert result.ok is True
    assert calls == [(["sway", "-C", "-c", str(candidate)], {"text": True, "capture_output": True, "check": False})]


def test_validation_reports_nonzero_output_and_validates_both_paths(tmp_path):
    candidate, main = tmp_path / "candidate", tmp_path / "main"
    candidate.write_text("", encoding="utf-8")
    main.write_text("", encoding="utf-8")

    def bad_runner(*_args, **_kwargs):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "bad config"})()

    with pytest.raises(ConfigValidationError, match="bad config"):
        validate_sway_config(candidate, bad_runner)

    seen = []
    validate_candidate_and_main(candidate, main, lambda argv, **kwargs: seen.append(argv) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    assert seen == [["sway", "-C", "-c", str(candidate)], ["sway", "-C", "-c", str(main)]]
