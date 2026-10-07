"""Ownership transitions keep committed state authoritative after failed writes."""

import os
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger

OWNER = "c" * 32


@pytest.fixture
def ledger(tmp_path):
    value = OwnershipLedger(tmp_path / "ownership", OWNER)
    value.open()
    yield value
    value.close()


@pytest.mark.parametrize("transition", ["intend", "creating", "removed"])
@pytest.mark.parametrize("failure", ["write", "flush", "fsync", "replace"])
def test_failed_write_preserves_commit_and_allows_retry(
    ledger, monkeypatch, transition, failure
):
    if transition != "intend":
        ledger.intend("/private/staging", preparing=True)
    if transition == "removed":
        ledger.creating()
    committed = ledger.read()

    def advance():
        if transition == "intend":
            ledger.intend("/private/staging", preparing=True)
        else:
            getattr(ledger, transition)()

    real_fdopen = os.fdopen

    @contextmanager
    def failing_stream(fd, mode):
        with real_fdopen(fd, mode) as stream:
            wrapped = Mock(wraps=stream)
            getattr(wrapped, failure).side_effect = OSError("controlled write failure")
            yield wrapped

    with monkeypatch.context() as fault:
        if failure in {"write", "flush"}:
            fault.setattr(os, "fdopen", failing_stream)
        else:
            fault.setattr(
                os, failure, Mock(side_effect=OSError("controlled write failure"))
            )
        with pytest.raises(OSError, match="controlled write failure"):
            advance()

    assert not (ledger.root / "worker.partial").exists()
    assert ledger.read() == committed
    advance()
    expected_phase = "preparing" if transition == "intend" else transition
    assert ledger.read()["phase"] == expected_phase


def test_competing_owner_cannot_discard_an_in_progress_write(ledger):
    partial = ledger.root / "worker.partial"
    partial.write_bytes(b"in progress")
    partial.chmod(0o600)
    ledger.open()
    assert partial.read_bytes() == b"in progress"
    competitor = OwnershipLedger(ledger.root, "d" * 32)
    try:
        with pytest.raises(RuntimeUnavailableError, match="ownership busy"):
            competitor.open()
        assert partial.read_bytes() == b"in progress"
    finally:
        competitor.close()


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "public_file"])
def test_invalid_partial_fails_closed_and_releases_owner_lock(tmp_path, kind):
    root = tmp_path / "ownership"
    root.mkdir(mode=0o700)
    partial = root / "worker.partial"
    target = tmp_path / "target"
    target.write_bytes(b"untouched")
    if kind == "symlink":
        partial.symlink_to(target)
    elif kind == "directory":
        partial.mkdir()
    elif kind == "fifo":
        os.mkfifo(partial, 0o600)
    else:
        partial.write_bytes(b"not private")
        partial.chmod(0o644)
    owner = OwnershipLedger(root, OWNER)
    try:
        with pytest.raises(RuntimeUnavailableError, match="Invalid partial"):
            owner.open()
        assert partial.lstat()
        assert target.read_bytes() == b"untouched"
        with pytest.raises(RuntimeUnavailableError, match="unstarted"):
            owner.read()
        if kind == "directory":
            partial.rmdir()
        else:
            partial.unlink()
        replacement = OwnershipLedger(root, "d" * 32)
        try:
            replacement.open()
            replacement.intend("/private/staging", preparing=True)
        finally:
            replacement.close()
    finally:
        owner.close()


def test_directory_sync_failure_keeps_committed_intent(ledger, monkeypatch):
    with monkeypatch.context() as fault:
        fault.setattr(
            ledger, "_sync", Mock(side_effect=OSError("controlled directory failure"))
        )
        with pytest.raises(OSError, match="controlled directory failure"):
            ledger.intend("/private/staging", preparing=True)
    assert not (ledger.root / "worker.partial").exists()
    assert ledger.read()["phase"] == "preparing"
    with pytest.raises(RuntimeUnavailableError, match="Unresolved"):
        ledger.intend("/private/new-staging", preparing=True)
    ledger.creating()
    assert ledger.read()["phase"] == "creating"


def test_discarding_partial_does_not_hide_corrupt_committed_record(tmp_path):
    root = tmp_path / "ownership"
    root.mkdir(mode=0o700)
    for name, content in (("worker.partial", b"unfinished"), ("worker.json", b"bad")):
        path = root / name
        path.write_bytes(content)
        path.chmod(0o600)
    owner = OwnershipLedger(root, OWNER)
    try:
        owner.open()
        with pytest.raises(RuntimeUnavailableError, match="Invalid runtime ownership"):
            owner.read()
        with pytest.raises(RuntimeUnavailableError, match="Invalid runtime ownership"):
            owner.intend("/private/staging", preparing=True)
        assert (root / "worker.json").read_bytes() == b"bad"
    finally:
        owner.close()
