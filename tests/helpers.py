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


class RuntimeClient:
    """Injected request/command double with one fresh tree per observation."""

    def __init__(self, trees, *, version=None, command_replies=None):
        self._trees = list(trees)
        self._version = version or {"major": 1, "minor": 9, "human_readable": "1.9"}
        self._command_replies = list(command_replies or [[{"success": True}]])
        self.requests = []
        self.commands = []

    def request(self, message_type, payload=""):
        from hermes_sway_plugin import ipc

        self.requests.append(message_type)
        if message_type == ipc.GET_VERSION:
            return self._version
        if message_type == ipc.GET_TREE:
            if not self._trees:
                raise AssertionError("unexpected GET_TREE")
            return self._trees.pop(0)
        raise AssertionError(f"unexpected IPC request {message_type}")

    def command(self, command):
        self.commands.append(command)
        if not self._command_replies:
            raise AssertionError("unexpected Sway command")
        return self._command_replies.pop(0)


def focused_tree(raw_tree, con_id):
    """Return a copied tree with exactly ``con_id`` focused."""
    import copy

    tree = copy.deepcopy(raw_tree)

    def visit(node):
        node["focused"] = node.get("id") == con_id
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            visit(child)

    visit(tree)
    return tree


def moved_window_tree(raw_tree, con_id, workspace_id):
    """Return a tree with a view reparented directly into one workspace."""
    import copy

    tree = copy.deepcopy(raw_tree)
    moved = None

    def detach(node):
        nonlocal moved
        for key in ("nodes", "floating_nodes"):
            children = node.get(key, [])
            for child in list(children):
                if child.get("id") == con_id:
                    children.remove(child)
                    moved = child
                    return True
                if detach(child):
                    return True
        return False

    def find(node):
        if node.get("id") == workspace_id:
            return node
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            found = find(child)
            if found is not None:
                return found
        return None

    assert detach(tree) and moved is not None
    workspace = find(tree)
    assert workspace is not None
    workspace.setdefault("nodes", []).append(moved)
    return tree


def updated_node_tree(raw_tree, con_id, **updates):
    """Return a copied tree with fields changed on one identified node."""
    import copy

    tree = copy.deepcopy(raw_tree)

    def visit(node):
        if node.get("id") == con_id:
            node.update(updates)
            return True
        return any(visit(child) for child in node.get("nodes", []) + node.get("floating_nodes", []))

    assert visit(tree)
    return tree


def focused_workspace_tree(raw_tree, workspace_id):
    """Return a copied tree with exactly one workspace marked focused."""
    import copy

    tree = copy.deepcopy(raw_tree)

    def visit(node):
        if node.get("type") == "workspace":
            node["focused"] = node.get("id") == workspace_id
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            visit(child)

    visit(tree)
    return tree


def without_node_tree(raw_tree, con_id):
    """Return a copied tree with one node removed."""
    import copy

    tree = copy.deepcopy(raw_tree)

    def visit(node):
        for key in ("nodes", "floating_nodes"):
            children = node.get(key, [])
            for child in list(children):
                if child.get("id") == con_id:
                    children.remove(child)
                    return True
                if visit(child):
                    return True
        return False

    assert visit(tree)
    return tree


def moved_node_tree(raw_tree, con_id, parent_id):
    """Return a copied tree with one node reparented into ``parent_id``."""
    import copy

    tree = copy.deepcopy(raw_tree)
    moved = None

    def detach(node):
        nonlocal moved
        for key in ("nodes", "floating_nodes"):
            for child in list(node.get(key, [])):
                if child.get("id") == con_id:
                    node[key].remove(child)
                    moved = child
                    return True
                if detach(child):
                    return True
        return False

    def find(node):
        if node.get("id") == parent_id:
            return node
        return next((found for child in node.get("nodes", []) + node.get("floating_nodes", []) if (found := find(child)) is not None), None)

    assert detach(tree) and moved is not None
    parent = find(tree)
    assert parent is not None
    parent.setdefault("nodes", []).append(moved)
    return tree

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
