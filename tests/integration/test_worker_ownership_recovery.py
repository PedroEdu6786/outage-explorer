"""Abrupt local owner loss at ledger write boundaries; no Docker or live I/O."""

import subprocess
import sys

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger

CRASHING_OWNER = """
import os
import sys
from pathlib import Path
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger

root, transition, checkpoint = sys.argv[1:]
ledger = OwnershipLedger(Path(root), "c" * 32)
ledger.open()
if transition != "intend":
    ledger.intend("/private/staging", preparing=True)
if transition == "removed":
    ledger.creating()

real_open, real_fsync, real_replace = os.open, os.fsync, os.replace

def interrupted_open(path, *args, **kwargs):
    fd = real_open(path, *args, **kwargs)
    if checkpoint == "created" and Path(path).name == "worker.partial":
        os._exit(23)
    return fd

def interrupted_fsync(fd):
    if checkpoint == "flushed":
        os._exit(23)
    real_fsync(fd)
    if checkpoint == "synced":
        os._exit(23)

def interrupted_replace(source, target):
    if checkpoint == "before_rename":
        os._exit(23)
    real_replace(source, target)
    if checkpoint == "after_rename":
        os._exit(23)

os.open, os.fsync, os.replace = interrupted_open, interrupted_fsync, interrupted_replace
if transition == "intend":
    ledger.intend("/private/staging", preparing=True)
else:
    getattr(ledger, transition)()
raise AssertionError("fault injection did not interrupt the owner")
"""


@pytest.mark.parametrize("transition", ["intend", "creating", "removed"])
@pytest.mark.parametrize(
    "checkpoint", ["created", "flushed", "synced", "before_rename", "after_rename"]
)
def test_restart_discards_only_uncommitted_write(tmp_path, transition, checkpoint):
    root = tmp_path / "ownership"
    crashed = subprocess.run(
        [sys.executable, "-c", CRASHING_OWNER, str(root), transition, checkpoint],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert crashed.returncode == 23, crashed.stderr.decode()
    assert (root / "worker.partial").exists() == (checkpoint != "after_rename")
    committed_path = root / "worker.json"
    committed = committed_path.read_bytes() if committed_path.exists() else None

    restarted = OwnershipLedger(root, "d" * 32)
    try:
        restarted.open()
        assert not (root / "worker.partial").exists()
        if transition == "intend" and checkpoint != "after_rename":
            assert restarted.read() is None
            restarted.intend("/private/new-staging", preparing=True)
            assert restarted.read()["owner"] == "d" * 32
        else:
            assert committed_path.read_bytes() == committed
            expected_phase = "preparing" if transition == "creating" else "creating"
            if checkpoint == "after_rename":
                expected_phase = "preparing" if transition == "intend" else transition
            assert restarted.read()["phase"] == expected_phase
            with pytest.raises(RuntimeUnavailableError, match="Unresolved"):
                restarted.intend("/private/new-staging", preparing=True)
            # The interrupted transition can be recorded again, but only the
            # runtime's normal worker reconciliation may clear committed intent.
            if checkpoint != "after_rename":
                getattr(restarted, transition)()
                assert restarted.read()["phase"] == transition
    finally:
        restarted.close()
