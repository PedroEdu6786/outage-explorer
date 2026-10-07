"""Controlled setup orchestration; never install tools or contact a daemon."""

import base64
import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "local_machine", Path(__file__).parents[1] / "scripts/local_machine.py"
)
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


@pytest.fixture
def calls(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "STATE", tmp_path / "state")
    values = []

    def run(arguments, **kwargs):
        values.append((arguments, kwargs))
        if arguments[:2] == ["git", "archive"]:
            (local.STATE / "source.tar").write_bytes(b"controlled archive")
        return subprocess.CompletedProcess(arguments, 0, stdout=b"controlled")

    monkeypatch.setattr(local, "run", run)
    return values


def test_wrong_host_is_rejected_before_work(monkeypatch):
    monkeypatch.setattr(local.platform, "system", lambda: "Linux")
    monkeypatch.setattr(local, "execute", lambda *args: pytest.fail("unexpected work"))
    with pytest.raises(SystemExit):
        local.main(["runtime"])


def test_review_requires_named_operator(monkeypatch):
    monkeypatch.setattr(local.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local.platform, "machine", lambda: "arm64")
    with pytest.raises(SystemExit):
        local.main(["review"])


def test_dirty_source_stops_before_guest_mutation(calls, monkeypatch):
    def fail(arguments, **kwargs):
        assert arguments[:3] == ["git", "diff", "--exit-code"]
        raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(local, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        local.execute("runtime", "")
    assert calls == []


def test_runtime_installs_committed_source_without_starting_api(calls):
    local.execute("runtime", "")
    assert calls[0][0][:2] == ["git", "diff"]
    archive = calls[1][0]
    assert "requirements-dev.txt" in archive and "scripts" in archive
    assert ".env" not in archive
    assert any("start-colima.sh" in str(args) for args, _ in calls)
    assert not any("local_analytical.py" in str(args) for args, _ in calls)
    assert all(args[: len(local.SSH)] == local.SSH for args, _ in calls[3:])


def test_validation_runs_guest_checks_without_review_or_start(calls):
    local.execute("validate", "")
    outer = calls[0][1]["input"].decode()
    encoded = outer.split("printf %s ", 1)[1].split(" |", 1)[0]
    body = base64.b64decode(encoded).decode()
    assert "--junitxml=" in body and "-m runtime_docker" in body
    assert "review_local_runtime.py" not in body
    assert "scripts/local_analytical.py" not in body
    assert "--reuid=65534" in outer and "stat -c %g /run/docker.sock" in outer


def test_configuration_copies_private_files_and_never_starts(calls):
    local.execute("configure", "")
    assert (local.STATE / "runtime-reviewed.json").stat().st_mode & 0o777 == 0o600
    command = calls[-1][0]
    assert "--configure" in command
    assert "systemd-run" not in str(calls)


def test_forward_is_loopback_and_uses_dedicated_guest(calls):
    local.execute("forward", "")
    assert calls[-1][0][-1] == "colima-outage-runtime"
    assert "127.0.0.1:8000:127.0.0.1:8000" in calls[-1][0]


def test_reviewer_is_quoted_as_one_remote_argument(calls):
    import shlex

    name = "Operator's name $(do-not-execute)"
    local.execute("review", name)
    outer = calls[0][1]["input"].decode()
    encoded = outer.split("printf %s ", 1)[1].split(" |", 1)[0]
    body = base64.b64decode(encoded).decode()
    command = body.splitlines()[-1]
    args = shlex.split(command)
    assert args[args.index("--reviewer") + 1] == name
    assert args[-1] == "--accept-local-containment"
