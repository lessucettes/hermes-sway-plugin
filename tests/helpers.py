"""Shared test helpers for the sway plugin test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def load_fixture(name: str):
    """Load a recorded or synthetic JSON fixture by file name."""
    import json

    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

HERMES_REPO = Path(
    os.environ.get("HERMES_REPO", str(Path.home() / ".hermes" / "hermes-agent"))
).expanduser()


def hermes_repo_available() -> bool:
    """True when a usable Hermes checkout is present (hermes_cli importable)."""
    return (HERMES_REPO / "hermes_cli" / "plugins_manifest.py").is_file()


def ensure_hermes_repo_on_path() -> bool:
    """Prepend the Hermes checkout to sys.path so Hermes APIs can be imported."""
    if not hermes_repo_available():
        return False
    repo = str(HERMES_REPO)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    return True
