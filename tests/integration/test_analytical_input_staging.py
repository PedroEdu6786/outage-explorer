"""Controlled local filesystem checks; no Docker denial evidence."""

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from time import monotonic
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.inputs import stage_inputs


@pytest.fixture
def profile(tmp_path):
    root = tmp_path / "staging"
    root.mkdir(mode=0o700)
    return RuntimeProfile(
        "sha256:" + "a" * 64,
        "unix:///tmp/docker.sock",
        "controlled",
        "controlled",
        "controlled",
        staging_root=str(root),
        cache_root=str(tmp_path / "cache"),
        result_root=str(tmp_path / "results"),
    )


@pytest.fixture
def approved(tmp_path):
    path = tmp_path / "input.parquet"
    pq.write_table(pa.table({"n": [1, 2]}), path)
    raw = path.read_bytes()
    return ApprovedFile(str(path), hashlib.sha256(raw).hexdigest(), len(raw), 2)


def test_private_copy_sealed_exact_entries_uid_readability_and_mutable_source(
    profile, approved
):
    staged = stage_inputs(profile, (approved,), monotonic() + 5)
    path = Path(staged.files[0].path)
    assert path.name == approved.sha256 + ".parquet"
    assert path.read_bytes() == Path(approved.path).read_bytes()
    assert path.stat().st_mode & 0o777 == 0o444  # UID 65534 reads exact bind.
    assert staged.directory.stat().st_mode & 0o777 == 0o555
    with pytest.raises(PermissionError):
        (staged.directory / "unapproved.parquet").touch()
    assert path.stat().st_ino != Path(approved.path).stat().st_ino
    Path(approved.path).write_bytes(b"changed source")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == approved.sha256
    assert list(staged.directory.iterdir()) == [path]
    staged.close()
    assert not staged.directory.exists()
    staged.close()


@pytest.mark.parametrize(
    "fault",
    ["digest", "size", "rows", "symlink", "parent_symlink", "directory", "replacement"],
)
def test_corrupt_racy_or_nonregular_inputs_leave_no_staging(
    profile, approved, tmp_path, fault
):
    path = Path(approved.path)
    if fault == "digest":
        approved = replace(approved, sha256="0" * 64)
    elif fault == "size":
        approved = replace(approved, byte_count=approved.byte_count + 1)
    elif fault == "rows":
        approved = replace(approved, rows=3)
    elif fault == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        approved = replace(approved, path=str(link))
    elif fault == "parent_symlink":
        link = tmp_path / "link"
        link.symlink_to(tmp_path, target_is_directory=True)
        approved = replace(approved, path=str(link / path.name))
    elif fault == "directory":
        approved = replace(approved, path=str(tmp_path))
    if fault == "replacement":
        real = os.fsync

        def swap(fd):
            real(fd)
            copy = tmp_path / "replacement"
            copy.write_bytes(path.read_bytes())
            os.replace(copy, path)

        context = patch(
            "outage_explorer.infrastructure.worker_runtime.inputs.os.fsync",
            side_effect=swap,
        )
    else:
        from contextlib import nullcontext

        context = nullcontext()
    with context, pytest.raises(DataUnavailableError):
        stage_inputs(profile, (approved,), monotonic() + 5)
    assert list(Path(profile.staging_root).iterdir()) == []


@pytest.mark.parametrize("bound", ["files", "bytes", "deadline", "conflict"])
def test_independent_preparation_limits(profile, approved, bound):
    files = (approved,)
    error = AnalyticalResourceError
    if bound == "files":
        profile = replace(profile, input_files=1)
        files += (replace(approved, sha256="b" * 64),)
    elif bound == "bytes":
        profile = replace(profile, input_bytes=1)
    elif bound == "conflict":
        files += (replace(approved, rows=1),)
        error = DataUnavailableError
    with pytest.raises(error):
        stage_inputs(
            profile, files, monotonic() - 1 if bound == "deadline" else monotonic() + 5
        )
    assert not list(Path(profile.staging_root).iterdir())
