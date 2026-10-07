"""Real local owner loss during input preparation; no container or cloud access."""

import subprocess
import sys
from pathlib import Path
from time import monotonic
from unittest.mock import Mock

import pytest

from outage_explorer.infrastructure.worker_runtime.docker import DockerRuntime
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger
from tests.integration.test_analytical_input_staging import (  # noqa: F401
    approved,
    profile,
)

CRASHING_PREPARATION = """
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from unittest.mock import Mock
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.docker import DockerRuntime
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger

root, source, checksum, byte_count, rows, checkpoint = sys.argv[1:]
profile = RuntimeProfile(
    "sha256:" + "a" * 64, "unix:///tmp/docker.sock", "test", "test", "test",
    staging_root=root,
)
ledger = OwnershipLedger(Path(root), "c" * 32)
ledger.open()
control = Mock()
control.run.side_effect = AssertionError("no Docker during preparation")
runtime = DockerRuntime(profile, control, ledger)
real_mkdir, real_open, real_chmod = Path.mkdir, Path.open, os.chmod

def interrupted_mkdir(path, *args, **kwargs):
    if checkpoint == "before_directory":
        os._exit(23)
    real_mkdir(path, *args, **kwargs)
    if checkpoint == "empty_directory":
        os._exit(23)

@contextmanager
def interrupted_copy(path, *args, **kwargs):
    with real_open(path, *args, **kwargs) as stream:
        if checkpoint == "partial_copy" and path.suffix == ".partial":
            wrapped = Mock(wraps=stream)
            def write(chunk):
                stream.write(chunk[:32])
                stream.flush()
                os._exit(23)
            wrapped.write.side_effect = write
            yield wrapped
        else:
            yield stream

def interrupted_seal(path, mode, *args, **kwargs):
    real_chmod(path, mode, *args, **kwargs)
    if checkpoint == "sealed_directory" and mode == 0o555:
        os._exit(23)

Path.mkdir, Path.open, os.chmod = interrupted_mkdir, interrupted_copy, interrupted_seal
file = ApprovedFile(source, checksum, int(byte_count), int(rows))
runtime.prepare_inputs((file,), monotonic() + 5)
raise AssertionError("fault injection did not interrupt preparation")
"""


@pytest.mark.parametrize(
    "checkpoint",
    ["before_directory", "empty_directory", "partial_copy", "sealed_directory"],
)
def test_restart_reclaims_exact_recorded_preparation(profile, approved, checkpoint):  # noqa: F811
    root = Path(profile.staging_root)
    unrelated = root / "execution-unrelated"
    unrelated.mkdir(mode=0o700)
    canary = unrelated / "preserve"
    canary.write_bytes(b"unrelated input")
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            CRASHING_PREPARATION,
            str(root),
            approved.path,
            approved.sha256,
            str(approved.byte_count),
            str(approved.rows),
            checkpoint,
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert crashed.returncode == 23, crashed.stderr.decode()
    restarted = OwnershipLedger(root, "d" * 32)
    try:
        restarted.open()
        record = restarted.read()
        assert record["phase"] == "preparing"
        staging = Path(record["staging"])
        assert staging.exists() == (checkpoint != "before_directory")
        if checkpoint == "partial_copy":
            assert (staging / (approved.sha256 + ".partial")).stat().st_size == 32
        if checkpoint == "sealed_directory":
            assert staging.stat().st_mode & 0o777 == 0o555
        control = Mock()
        control.run.side_effect = AssertionError("no worker exists to reap")
        runtime = DockerRuntime(profile, control, restarted)
        runtime.recover_owned()
        assert not staging.exists()
        assert restarted.read() is None
        assert canary.read_bytes() == b"unrelated input"
        assert Path(approved.path).exists()
        control.run.assert_not_called()
        runtime.prepare_inputs((approved,), monotonic() + 5)
        runtime.terminate_and_reap()
        assert restarted.read() is None
        assert {path.name for path in root.iterdir()} == {
            "owner.lock",
            "execution-unrelated",
        }
    finally:
        restarted.close()
