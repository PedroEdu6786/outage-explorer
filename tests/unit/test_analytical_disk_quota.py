"""Controlled kernel facts and lifecycle faults; no real mounts or quota claims."""

import io
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.application.ports.execution import QueryRead
from outage_explorer.infrastructure.worker_runtime import quota
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.docker import DockerRuntime
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger
from tests.unit.test_docker_runtime import OWNER, Control


@pytest.fixture
def disk(tmp_path, monkeypatch):
    root = tmp_path / "spill"
    root.mkdir(mode=0o700)
    os.chown(root, -1, os.getgid())
    info = root.stat()
    capacity = SimpleNamespace(
        f_blocks=2048,
        f_frsize=4096,
        f_files=1024,
        f_fsid=321,
        f_flag=0,
    )
    profile = RuntimeProfile(
        "sha256:" + "a" * 64,
        "unix:///run/docker.sock",
        "linux/amd64",
        "test",
        "test",
        temporary_backend="quota-disk",
        temporary_root=str(root),
        temporary_filesystem_identity=f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}:321",
    )
    # Controlled host credentials emulate the configured UID; real directories
    # stay owned by the test runner. Product validation is not bypassed in startup.
    host_profile = SimpleNamespace(**profile.__dict__)
    host_profile.uid, host_profile.gid = os.getuid(), os.getgid()
    monkeypatch.setattr(quota.platform, "system", lambda: "Linux")
    monkeypatch.setattr(quota, "_mount", lambda root: ("7", "8:1", "/dev/loop0"))
    monkeypatch.setattr(quota.os, "fstatvfs", lambda fd: capacity)
    yield quota.DiskSpill(host_profile, OWNER), capacity, profile


def test_dedicated_pool_private_mount_and_exclusive_lock(disk):
    spill, _, _ = disk
    assert not list(spill.root.iterdir())  # construction is inert
    spill.open()
    spill.allocate()
    assert spill.directory.stat().st_mode & 0o777 == 0o700
    mount = spill.mount_argument()
    assert mount == f"type=bind,src={spill.directory},dst=/tmp,bind-recursive=disabled"
    competitor = quota.DiskSpill(spill.profile, "d" * 32)
    with pytest.raises(RuntimeUnavailableError):
        competitor.open()
    child = spill.directory / "private-worker-dir"
    child.mkdir(mode=0o700)
    (child / "file").write_bytes(b"synthetic")
    child.chmod(0o000)
    spill.close()
    assert not spill.directory.exists()
    with pytest.raises(RuntimeUnavailableError):
        competitor.open()  # lock survives until caller clears durable intent
    spill.release()
    competitor.open()
    competitor.release()


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("f_blocks", 100_000),
        ("f_files", 100_000),
        ("f_blocks", 0),
        ("f_files", 0),
        ("f_flag", os.ST_RDONLY),
        ("f_fsid", 999),
    ],
)
def test_invalid_or_unbounded_filesystem_fails_closed(disk, attribute, value):
    spill, capacity, _ = disk
    setattr(capacity, attribute, value)
    with pytest.raises(RuntimeUnavailableError):
        spill.open()
    assert not spill.directory.exists() and spill._root_fd is None


def test_capacity_drift_and_mount_replacement_keep_lock(disk, monkeypatch):
    spill, capacity, _ = disk
    spill.open()
    spill.allocate()
    capacity.f_blocks -= 1
    with pytest.raises(RuntimeUnavailableError):
        spill.mount_argument()
    with pytest.raises(RuntimeUnavailableError):
        spill.close()
    assert spill.directory.exists() and spill._lock_fd is not None
    capacity.f_blocks += 1
    monkeypatch.setattr(quota, "_mount", lambda root: ("8", "8:1", "/dev/loop0"))
    with pytest.raises(RuntimeUnavailableError):
        spill.close()
    spill.release()


def test_foreign_pool_contents_symlink_and_private_parent_rejected(disk):
    spill, _, _ = disk
    (spill.root / "unrelated").write_text("synthetic")
    with pytest.raises(RuntimeUnavailableError):
        spill.open()
    (spill.root / "unrelated").unlink()
    spill.root.chmod(0o755)
    with pytest.raises(RuntimeUnavailableError):
        spill.open()
    spill.root.chmod(0o700)
    link = spill.root.parent / "link"
    link.symlink_to(spill.root, target_is_directory=True)
    spill.root = link
    with pytest.raises(RuntimeUnavailableError):
        spill.open()


@pytest.mark.parametrize("fault", ["symlink", "replacement"])
def test_worker_directory_replacement_never_removed(disk, fault):
    spill, _, _ = disk
    spill.open()
    spill.allocate()
    original = spill.directory.with_name("retained")
    spill.directory.rename(original)
    if fault == "symlink":
        spill.directory.symlink_to(original, target_is_directory=True)
    else:
        spill.directory.mkdir()
    with pytest.raises(RuntimeUnavailableError):
        spill.close()
    assert original.exists() and spill.directory.exists()
    spill.release()


@pytest.mark.parametrize(
    "options,filesystem,root,child",
    [
        ("rw,noexec,nosuid,nodev", "ext4", "/", False),
        ("rw,nosuid,nodev", "ext4", "/", False),
        ("rw,noexec,nosuid,nodev", "tmpfs", "/", False),
        ("rw,noexec,nosuid,nodev", "ext4", "/subdir", False),
        ("rw,noexec,nosuid,nodev", "ext4", "/", True),
    ],
)
def test_actual_mount_parser_requires_full_dedicated_safe_ext4(
    tmp_path,
    monkeypatch,
    options,
    filesystem,
    root,
    child,
):
    target = tmp_path / "spill"
    raw = f"7 2 8:1 {root} {target} {options} - {filesystem} /dev/loop0 rw\n"
    if child:
        raw += f"8 7 0:1 / {target}/foreign rw - tmpfs tmpfs rw\n"
    monkeypatch.setattr(Path, "open", lambda *args: io.BytesIO(raw.encode()))
    if (
        options == "rw,noexec,nosuid,nodev"
        and filesystem == "ext4"
        and root == "/"
        and not child
    ):
        assert quota._mount(target) == ("7", "8:1", "/dev/loop0")
    else:
        with pytest.raises(ValueError):
            quota._mount(target)


@pytest.fixture
def adapter(disk, tmp_path, monkeypatch):
    spill, _, candidate = disk
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    profile = replace(candidate, staging_root=str(staging))
    ledger = OwnershipLedger(tmp_path / "ownership", OWNER)
    ledger.open()
    control = Control()
    monkeypatch.setattr(DockerRuntime, "_validate_daemon", lambda self: None)
    original = quota.DiskSpill

    def controlled_disk(p, owner):
        controlled = SimpleNamespace(**p.__dict__)
        controlled.uid, controlled.gid = os.getuid(), os.getgid()
        return original(controlled, owner)

    monkeypatch.setattr(
        "outage_explorer.infrastructure.worker_runtime.docker.DiskSpill",
        controlled_disk,
    )
    runtime = DockerRuntime(profile, control, ledger)
    yield runtime, control, ledger
    if runtime._spill is not None:
        runtime._spill.release()
    ledger.close()


@pytest.mark.parametrize("failure", ["create", "start", "inspect", "wait", "rm"])
def test_uncertain_worker_retains_spill_until_exact_cleanup(adapter, failure):
    runtime, control, ledger = adapter
    if failure in {"create", "start", "inspect"}:
        control.fail = failure
        with pytest.raises(RuntimeUnavailableError):
            runtime.query(
                QueryRead("SELECT 42", ()),
                runtime.profile.execution_bounds,
                monotonic() + 5,
            )
    else:
        runtime.query(
            QueryRead("SELECT 42", ()),
            runtime.profile.execution_bounds,
            monotonic() + 5,
        )
    if failure in {"create", "start"}:
        control.fail = "inspect"
    else:
        control.fail = failure
    spill = runtime._spill
    with pytest.raises(RuntimeUnavailableError):
        runtime.terminate_and_reap()
    assert spill.directory.exists() and spill._lock_fd is not None
    assert ledger.read()["spill"] == str(spill.directory)
    control.fail = None
    runtime.terminate_and_reap()
    assert not spill.directory.exists() and ledger.read() is None
    assert spill._lock_fd is None


def test_recovery_reaps_container_before_spill_reclamation(adapter):
    runtime, control, ledger = adapter
    runtime.query(
        QueryRead("SELECT 42", ()), runtime.profile.execution_bounds, monotonic() + 5
    )
    spill = runtime._spill
    spill.release()  # emulate process death; durable record and directory survive
    recovered = DockerRuntime(runtime.profile, control, ledger)
    recovered.recover_owned()
    assert ledger.read() is None and not spill.directory.exists()
    assert any(args[0] == "rm" for args, _ in control.calls)


def test_preparing_crash_recovers_without_container_lookup(adapter):
    runtime, control, ledger = adapter
    runtime.prepare_inputs((), monotonic() + 5)
    assert ledger.read()["phase"] == "preparing"
    runtime._spill.release()
    DockerRuntime(runtime.profile, control, ledger).recover_owned()
    assert ledger.read() is None and not control.calls


def test_spill_allocation_before_staging_is_recoverable(adapter, monkeypatch):
    runtime, control, ledger = adapter
    monkeypatch.setattr(
        "outage_explorer.infrastructure.worker_runtime.docker.stage_inputs",
        Mock(side_effect=RuntimeUnavailableError("interrupted before staging")),
    )
    with pytest.raises(RuntimeUnavailableError, match="interrupted before staging"):
        runtime.prepare_inputs((), monotonic() + 5)
    record = ledger.read()
    assert record["phase"] == "preparing"
    assert not Path(record["staging"]).exists()
    assert Path(record["spill"]).exists()
    runtime._spill.release()  # Emulate owner loss, leaving exact recorded spill.
    DockerRuntime(runtime.profile, control, ledger).recover_owned()
    assert ledger.read() is None
    assert not Path(record["spill"]).exists()
    assert control.calls == []


def test_ledger_clear_failure_keeps_pool_lock_until_retry(adapter, monkeypatch):
    runtime, _, ledger = adapter
    runtime.query(
        QueryRead("SELECT 42", ()), runtime.profile.execution_bounds, monotonic() + 5
    )
    spill = runtime._spill
    original = ledger.clear
    monkeypatch.setattr(ledger, "clear", Mock(side_effect=OSError()))
    with pytest.raises(RuntimeUnavailableError):
        runtime.terminate_and_reap()
    assert spill._lock_fd is not None and ledger.read()
    monkeypatch.setattr(ledger, "clear", original)
    runtime.terminate_and_reap()
    assert spill._lock_fd is None and ledger.read() is None


def test_restart_after_partial_cleanup_uses_durable_removed_proof(adapter, monkeypatch):
    runtime, _, ledger = adapter
    runtime.query(
        QueryRead("SELECT 42", ()), runtime.profile.execution_bounds, monotonic() + 5
    )
    spill = runtime._spill
    original = ledger.clear
    monkeypatch.setattr(ledger, "clear", Mock(side_effect=OSError()))
    with pytest.raises(RuntimeUnavailableError):
        runtime.terminate_and_reap()
    assert ledger.read()["phase"] == "removed"
    assert runtime._staging is None and not spill.directory.exists()
    spill.release()
    monkeypatch.setattr(ledger, "clear", original)
    recovered = DockerRuntime(runtime.profile, runtime.control, ledger)
    recovered.recover_owned()
    assert ledger.read() is None


def test_invalid_spill_ledger_never_reclaims_foreign_path(adapter):
    runtime, _, ledger = adapter
    stage = Path(runtime.profile.staging_root) / "execution-controlled"
    stage.mkdir(mode=0o700)
    ledger.intend(str(stage), spill="/unrelated/private/path", preparing=True)
    with pytest.raises(RuntimeUnavailableError):
        runtime.recover_owned()
    assert stage.exists() and ledger.read()


def test_profile_storage_changes_invalidate_evidence_identity(disk):
    _, _, profile = disk
    assert replace(profile, temporary_inodes=2048).identity != profile.identity
    assert (
        replace(profile, temporary_filesystem_identity="8:1:999").identity
        != profile.identity
    )


def test_native_daemon_rejects_desktop_and_mismatch(monkeypatch):
    profile = RuntimeProfile(
        "sha256:" + "a" * 64, "unix:///run/docker.sock", "linux/amd64", "v", "test"
    )
    monkeypatch.setattr(quota.platform, "system", lambda: "Linux")
    monkeypatch.setattr(quota.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(quota.platform, "release", lambda: "kernel")
    monkeypatch.setattr(quota.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        Path, "stat", lambda self: SimpleNamespace(st_mode=stat.S_IFSOCK, st_uid=0)
    )
    monkeypatch.setattr(Path, "resolve", lambda self: Path("/run/docker.sock"))
    facts = {
        "version": "v",
        "os": "linux",
        "kernel": "kernel",
        "name": "host",
        "architecture": "x86_64",
    }
    quota.validate_native_daemon(profile, json.dumps(facts).encode())
    for key in facts:
        invalid = dict(facts)
        invalid[key] = "mismatch"
        with pytest.raises(RuntimeUnavailableError):
            quota.validate_native_daemon(profile, json.dumps(invalid).encode())
    monkeypatch.setattr(quota.platform, "system", lambda: "Darwin")
    with pytest.raises(RuntimeUnavailableError):
        quota.validate_native_daemon(profile, json.dumps(facts).encode())


@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="Linux path descriptors required")
def test_secure_traversal_accepts_execute_only_ancestor(tmp_path):
    ancestor = tmp_path / "traverse"
    ancestor.mkdir(mode=0o700)
    selected = ancestor / "private-root"
    selected.mkdir(mode=0o700)
    ancestor.chmod(0o111)
    try:
        fd = quota._open_directory(selected)
        try:
            assert os.fstat(fd).st_ino == selected.stat().st_ino
            assert os.listdir(fd) == []  # selected root remains readable
        finally:
            os.close(fd)
    finally:
        ancestor.chmod(0o700)
