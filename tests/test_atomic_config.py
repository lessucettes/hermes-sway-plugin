from __future__ import annotations

from pathlib import Path

from hermes_sway_plugin.persistent import atomic_replace


def test_atomic_replace_writes_candidate_in_target_directory_and_prunes_backups(tmp_path):
    target = tmp_path / "managed.conf"
    target.write_text("old", encoding="utf-8")

    result = atomic_replace(target, "one", backup_count=2)
    atomic_replace(target, "two", backup_count=2)
    atomic_replace(target, "three", backup_count=2)

    assert target.read_text(encoding="utf-8") == "three"
    assert result.candidate.parent == tmp_path
    assert not result.candidate.exists()
    assert sorted(path.name for path in tmp_path.glob("managed.conf.bak.*")) == ["managed.conf.bak.1", "managed.conf.bak.2"]
    assert (tmp_path / "managed.conf.bak.1").read_text(encoding="utf-8") == "two"
