"""Rebuild/recovery using temporary files and controlled command boundaries."""

import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(tmp_path, monkeypatch):
    local = load("local_machine")
    monkeypatch.setitem(sys.modules, "local_machine", local)
    rebuild = load("local_rebuild")
    monkeypatch.setattr(local, "ROOT", tmp_path)
    monkeypatch.setattr(local, "STATE", tmp_path / ".local-runtime")
    local.STATE.mkdir()
    monkeypatch.setattr(local.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        "builtins.input", lambda *args: pytest.fail("unexpected prompt")
    )
    monkeypatch.setattr(rebuild, "check_refresh_idle", lambda: None)
    return rebuild


def test_snapshot_includes_working_edits_additions_and_deletions(
    host, tmp_path, monkeypatch
):
    (tmp_path / "src").mkdir()
    existing = tmp_path / "src/existing.py"
    deleted = tmp_path / "src/deleted.py"
    existing.write_text("original")
    deleted.write_text("remove me")
    existing.write_text("working changes")
    deleted.unlink()
    (tmp_path / "src/added.py").write_text("new file")
    (tmp_path / ".env").write_text("SECRET=private")
    (tmp_path / "src/.env").write_text("PRIVATE")
    (tmp_path / "src/key.pem").write_text("PRIVATE")
    (tmp_path / "src/ignored.py").write_text("ignored")
    (tmp_path / ".gitignore").write_text("src/ignored.py\n.local-runtime/\n")

    def git_files(args, **kwargs):
        assert args[:7] == [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
        ]
        # Git includes tracked deletions and excludes ignored/unallowlisted files.
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=b"src/existing.py\0src/deleted.py\0src/added.py\0src/.env\0src/key.pem\0",
        )

    monkeypatch.setattr(host.local, "run", git_files)
    with tarfile.open(host.working_tree_archive()) as archive:
        assert set(archive.getnames()) == {"src/existing.py", "src/added.py"}
        assert archive.extractfile("src/existing.py").read() == b"working changes"
    assert existing.read_text() == "working changes"
    assert not deleted.exists()


def test_snapshot_rejects_symlinks(host, tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/link.py").symlink_to("/private/secret")
    monkeypatch.setattr(
        host.local,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=b"src/link.py\0"),
    )
    with pytest.raises(ValueError, match="symlinks"):
        host.working_tree_archive()


@pytest.fixture
def host_steps(host, monkeypatch):
    events = []
    archive = host.local.STATE / "source.tar"
    archive.write_bytes(b"controlled")
    monkeypatch.setattr(host, "working_tree_archive", lambda: archive)
    monkeypatch.setattr(host.local, "run", lambda *a, **kw: None)
    monkeypatch.setattr(host.local, "remote", lambda *a: None)
    monkeypatch.setattr(
        host.local, "execute", lambda action, reviewer: events.append(action)
    )
    monkeypatch.setattr(
        host.local, "controller", lambda command: events.append("automated-evidence")
    )
    monkeypatch.setattr(host, "guest", lambda state, action: events.append(action))
    return events


def test_rebuild_and_repeat_are_unattended(host, host_steps):
    for _ in range(2):
        assert host.main([]) == 0
    assert (
        host_steps
        == [
            "prepare",
            "install",
            "reset-evidence",
            "candidate",
            "validate",
            "reports",
            "automated-evidence",
            "configure",
            "finish",
        ]
        * 2
    )


def test_validation_failure_does_not_configure_and_can_resume(
    host, host_steps, monkeypatch
):
    def fail(action, reviewer):
        host_steps.append(action)
        if action == "validate":
            raise subprocess.CalledProcessError(1, ["controlled"])

    monkeypatch.setattr(host.local, "execute", fail)
    assert host.main([]) == 1
    assert host_steps[-1] == "validate"
    assert "configure" not in host_steps
    monkeypatch.setattr(
        host.local, "execute", lambda action, reviewer: host_steps.append(action)
    )
    assert host.main(["resume"]) == 0
    assert host_steps[-1] == "finish"


def test_configure_retry_does_not_rebuild_or_revalidate(host, host_steps):
    host.save({"identifier": "a" * 32, "next": "configure"})
    assert host.main(["resume"]) == 0
    assert host_steps == ["configure", "finish"]


def test_incomplete_update_refuses_another_rebuild(host, host_steps):
    host.save({"identifier": "a" * 32, "next": "prepare"})
    assert host.main([]) == 1
    assert host_steps == []
    assert host.main(["rollback"]) == 0
    assert host_steps == ["rollback"]


@pytest.fixture
def guest(tmp_path, monkeypatch):
    module = load("rebuild_guest")
    for name in ("SOURCE", "REPORTS", "HISTORY", "CONFIG", "SPILL"):
        path = tmp_path / name.lower()
        path.mkdir()
        monkeypatch.setattr(module, name, path)
    (module.SOURCE / ".venv/bin").mkdir(parents=True)
    (module.SOURCE / ".venv/bin/python").write_text("old interpreter")
    (module.SOURCE / "deleted.py").write_text("old source")
    (module.CONFIG / "environment.json").write_text("private settings")
    for name in ("runtime.json", "parser.json"):
        (module.CONFIG / name).write_text("old profile")
    (module.REPORTS / "candidate.json").write_text("old evidence")
    (module.REPORTS / "owned/cache").mkdir(parents=True)
    (module.REPORTS / "owned/cache/keep").write_text("cache")
    module.check_quiescence = module.quiescent
    monkeypatch.setattr(module, "quiescent", lambda: None)
    monkeypatch.setattr(module, "run", lambda *a, **kw: None)

    def output(args):
        if args[0] == "docker":
            return "sha256:" + "a" * 64
        return "inactive"

    monkeypatch.setattr(module, "output", output)
    return module


def stage_and_prepare(guest, tmp_path, identifier="a" * 32):
    stage = tmp_path / f"outage-runtime-update-{identifier}"
    stage.mkdir()
    (stage / "added.py").write_text("new source")
    (stage / ".venv/bin").mkdir(parents=True)
    (stage / ".venv/bin/python").write_text("new interpreter")
    backup = guest.HISTORY / identifier
    guest.prepare(identifier, stage, backup)
    return stage, backup, json.loads((backup / "state.json").read_text())


def test_build_failure_keeps_installed_source_and_profiles(
    guest, tmp_path, monkeypatch
):
    def fail(args, **kwargs):
        if args[0] == "sh":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(guest, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        stage_and_prepare(guest, tmp_path)
    assert (guest.SOURCE / "deleted.py").read_text() == "old source"
    assert (guest.CONFIG / "runtime.json").read_text() == "old profile"
    assert (guest.REPORTS / "candidate.json").read_text() == "old evidence"


def test_install_replaces_complete_source_and_rollback_restores_it(guest, tmp_path):
    stage, backup, state = stage_and_prepare(guest, tmp_path)
    guest.install("a" * 32, stage, backup, state)
    assert not (guest.SOURCE / "deleted.py").exists()
    assert (guest.SOURCE / "added.py").is_file()
    assert guest.SOURCE.resolve() == stage
    assert (stage / ".venv/bin/python").is_file()
    assert (backup / "source/deleted.py").is_file()
    assert (backup / "evidence/candidate.json").is_file()
    assert (guest.REPORTS / "owned/cache/keep").read_text() == "cache"
    assert not (guest.CONFIG / "runtime.json").exists()
    assert (guest.CONFIG / "environment.json").read_text() == "private settings"
    guest.rollback(backup, state)
    assert (guest.SOURCE / "deleted.py").is_file()
    assert not (guest.SOURCE / "added.py").exists()
    assert (guest.CONFIG / "runtime.json").read_text() == "old profile"
    assert (guest.REPORTS / "candidate.json").read_text() == "old evidence"
    assert not (guest.HISTORY / "active").exists()
    assert list(backup.glob("failed-source-*"))


def test_missing_configuration_cannot_finish_update(guest, tmp_path):
    stage, backup, state = stage_and_prepare(guest, tmp_path)
    guest.install("a" * 32, stage, backup, state)
    with pytest.raises(ValueError, match="configuration"):
        guest.finish(backup, state)
    assert (guest.HISTORY / "active").exists()


def test_success_preserves_backup_and_never_starts_api(guest, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(guest, "run", lambda args, **kw: calls.append(args))
    stage, backup, state = stage_and_prepare(guest, tmp_path)
    guest.install("a" * 32, stage, backup, state)
    for name in ("runtime.json", "parser.json"):
        (guest.CONFIG / name).write_text("new validated profile")
    guest.finish(backup, state)
    assert (backup / "source/deleted.py").exists()
    assert not (guest.HISTORY / "active").exists()
    assert not any("start" in args or "restart" in args for args in calls)


def test_second_guest_rebuild_preserves_working_virtualenv_paths(guest, tmp_path):
    for identifier in ("a" * 32, "b" * 32):
        stage, backup, state = stage_and_prepare(guest, tmp_path, identifier)
        guest.install(identifier, stage, backup, state)
        for name in ("runtime.json", "parser.json"):
            (guest.CONFIG / name).write_text("validated profile")
        guest.finish(backup, state)
        assert guest.SOURCE.resolve() == stage
        assert (stage / ".venv/bin/python").is_file()
    assert (guest.HISTORY / ("b" * 32) / "source").resolve().name.endswith("a" * 32)


def test_failed_api_stop_prevents_build_and_source_replacement(
    guest, tmp_path, monkeypatch
):
    def busy():
        raise ValueError("API has not stopped")

    monkeypatch.setattr(guest, "quiescent", busy)
    with pytest.raises(ValueError, match="not stopped"):
        stage_and_prepare(guest, tmp_path)
    assert (guest.SOURCE / "deleted.py").is_file()
    assert (guest.CONFIG / "runtime.json").is_file()


def test_running_api_is_masked_and_stopped_before_build(guest, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(guest, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        guest, "output", lambda args: "active" if "ActiveState" in args else "loaded"
    )
    stage_and_prepare(guest, tmp_path)
    assert calls.index(["systemctl", "mask", "--runtime", guest.UNIT]) < calls.index(
        ["systemctl", "stop", guest.UNIT]
    )
    assert calls.index(["systemctl", "stop", guest.UNIT]) < next(
        index for index, args in enumerate(calls) if args[0] == "sh"
    )


def test_busy_parser_lease_prevents_update(guest, monkeypatch):
    import fcntl

    monkeypatch.setattr(
        guest, "output", lambda args: "inactive" if args[0] == "systemctl" else ""
    )
    monkeypatch.setattr(
        guest.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1)
    )
    folder = guest.REPORTS / "parser-ownership"
    folder.mkdir()
    with (folder / "parser.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            guest.check_quiescence()


def test_unresolved_worker_ledger_prevents_update(guest, monkeypatch):
    monkeypatch.setattr(
        guest, "output", lambda args: "inactive" if args[0] == "systemctl" else ""
    )
    monkeypatch.setattr(
        guest.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1)
    )
    folder = guest.REPORTS / "owned/staging"
    folder.mkdir()
    ledger = folder / "worker.json"
    ledger.write_text("unresolved")
    with pytest.raises(ValueError, match="Unresolved"):
        guest.check_quiescence()
    assert ledger.read_text() == "unresolved"


def test_recovery_is_bound_to_the_active_update(guest, monkeypatch):
    monkeypatch.setattr(guest.sys, "platform", "linux")
    monkeypatch.setattr(guest.os, "getuid", lambda: 0)
    (guest.HISTORY / "active").write_text("a" * 32)
    with pytest.raises(ValueError, match="identity"):
        guest.main(["rollback", "b" * 32])
    assert (guest.HISTORY / "active").read_text() == "a" * 32


def test_lost_finish_response_can_be_resumed(guest, tmp_path, monkeypatch):
    identifier = "a" * 32
    stage, backup, state = stage_and_prepare(guest, tmp_path, identifier)
    guest.install(identifier, stage, backup, state)
    for name in ("runtime.json", "parser.json"):
        (guest.CONFIG / name).write_text("validated profile")
    guest.finish(backup, state)
    monkeypatch.setattr(guest.sys, "platform", "linux")
    monkeypatch.setattr(guest.os, "getuid", lambda: 0)
    assert guest.main(["finish", identifier]) == 0


def test_missing_runtime_rollback_does_not_touch_installed_files(guest, monkeypatch):
    monkeypatch.setattr(guest.sys, "platform", "linux")
    monkeypatch.setattr(guest.os, "getuid", lambda: 0)
    assert guest.main(["rollback", "a" * 32]) == 0
    assert (guest.SOURCE / "deleted.py").read_text() == "old source"


def test_prepare_failure_can_restore_old_runtime(guest, tmp_path, monkeypatch):
    def fail(args, **kwargs):
        if args[0] == "sh":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(guest, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        stage_and_prepare(guest, tmp_path)
    backup = guest.HISTORY / ("a" * 32)
    guest.rollback(backup, json.loads((backup / "state.json").read_text()))
    assert (guest.CONFIG / "runtime.json").read_text() == "old profile"
    assert (guest.REPORTS / "candidate.json").read_text() == "old evidence"
    assert not (guest.HISTORY / "active").exists()
