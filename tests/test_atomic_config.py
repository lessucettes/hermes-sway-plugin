from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_sway_plugin import persistent
from hermes_sway_plugin.persistent import AtomicWriteError, atomic_replace, restore_atomic_write


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


def test_backup_keep_zero_still_preserves_private_rollback_state(tmp_path):
    target = tmp_path / "managed.conf"
    target.write_text("old", encoding="utf-8")

    write = atomic_replace(target, "new", backup_count=0)

    assert write.backup is None
    assert write.prior_bytes == b"old"
    assert write.prior_digest is not None
    assert list(tmp_path.glob("managed.conf.rollback.*")) == []

    restore_atomic_write(write)

    assert target.read_text(encoding="utf-8") == "old"


def test_stale_rollback_refuses_to_overwrite_a_newer_atomic_write(tmp_path):
    target = tmp_path / "managed.conf"
    target.write_text("old", encoding="utf-8")
    stale = atomic_replace(target, "first", backup_count=2)
    current = atomic_replace(target, "second", backup_count=2)

    with pytest.raises(AtomicWriteError, match="changed since atomic write"):
        restore_atomic_write(stale)

    assert target.read_text(encoding="utf-8") == "second"
    assert stale.prior_bytes == b"old"
    assert current.prior_bytes == b"first"


def test_rollback_uses_the_captured_bytes_when_disk_snapshots_are_tampered(tmp_path):
    target = tmp_path / "managed.conf"
    target.write_text("trusted old content", encoding="utf-8")

    write = atomic_replace(target, "new content", backup_count=0)
    for snapshot in tmp_path.glob("managed.conf.rollback.*"):
        snapshot.write_text("attacker-controlled content", encoding="utf-8")

    restore_atomic_write(write)

    assert target.read_text(encoding="utf-8") == "trusted old content"


def test_rollback_rejects_an_aba_replacement_with_the_same_bytes(tmp_path):
    target = tmp_path / "managed.conf"
    target.write_text("old", encoding="utf-8")
    stale = atomic_replace(target, "expected", backup_count=0)
    replacement = tmp_path / "replacement"
    replacement.write_text("expected", encoding="utf-8")
    os.replace(replacement, target)

    with pytest.raises(AtomicWriteError, match="changed since atomic write"):
        restore_atomic_write(stale)

    assert target.read_text(encoding="utf-8") == "expected"


def test_user_backup_resists_destination_symlink_race(tmp_path, monkeypatch):
    target = tmp_path / "managed.conf"
    target.write_text("old", encoding="utf-8")
    victim = tmp_path / "victim"
    victim.write_text("untouched", encoding="utf-8")
    backup = tmp_path / "managed.conf.bak.1"
    real_replace = persistent.os.replace
    injected = False

    def race_replace(source, destination, *args, **kwargs):
        nonlocal injected
        if Path(destination) == backup:
            backup.unlink(missing_ok=True)
            backup.symlink_to(victim)
            injected = True
        return real_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(persistent.os, "replace", race_replace)

    atomic_replace(target, "new", backup_count=1)

    assert injected is True
    assert victim.read_text(encoding="utf-8") == "untouched"
    assert not backup.is_symlink()
    assert backup.read_text(encoding="utf-8") == "old"
