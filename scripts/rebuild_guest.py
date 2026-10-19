"""Transactional local source replacement on the dedicated Linux guest.

Runs as root through the explicit host rebuild command. No cloud operations.
Previous source, configuration and evidence are retained for explicit rollback.
"""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

SOURCE = Path("/opt/outage-runtime-validation")
REPORTS = Path("/var/lib/outage-runtime-validation")
HISTORY = Path("/var/lib/outage-runtime-history")
CONFIG = Path("/run/outage-api")
SPILL = Path("/var/lib/outage-analytical/spill")
UNIT = "outage-api-local.service"
TAG = "outage-analytical-worker:validation"
HELPERS = "infrastructure/analytical-worker/native-linux-validation"
EVIDENCE = (
    "candidate.json",
    "parser-candidate.json",
    "runtime-reviewed.json",
    "parser-reviewed.json",
    "local-scope-review.json",
    "controlled.xml",
    "parser.xml",
    "docker.xml",
    "dependencies.log",
    "build.log",
    "owned/validation-reports",
)


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return run(args, capture_output=True, text=True).stdout.strip()


def save(path, value):
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream)
    temporary.replace(path)


def quiescent():
    state = output(["systemctl", "show", UNIT, "-p", "ActiveState", "--value"])
    if state not in {"inactive", "failed", ""}:
        raise ValueError("API has not stopped")
    if output(["docker", "ps", "-q"]):
        raise ValueError(
            "Docker workloads remain; finish their cleanup before rebuilding"
        )
    processes = subprocess.run(
        ["pgrep", "-f", "^/opt/outage-runtime-validation/.venv/bin/python"],
        capture_output=True,
        check=False,
    )
    if processes.returncode != 1:
        raise ValueError("Guest Python workloads remain or process inspection failed")
    if (REPORTS / "owned/staging/worker.json").exists():
        raise ValueError("Unresolved worker ownership; reconcile it before rebuilding")
    # Never unlink or replace these stable ownership locks.
    with ExitStack() as stack:
        for name in ("owned/staging/owner.lock", "parser-ownership/parser.lock"):
            path = REPORTS / name
            if path.exists():
                fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
                stack.callback(os.close, fd)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def archive_evidence(destination):
    destination.mkdir(mode=0o700)
    for name in EVIDENCE:
        path = REPORTS / name
        if path.exists():
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.rename(target)


def restore_evidence(origin):
    for name in EVIDENCE:
        path = origin / name
        if path.exists():
            target = REPORTS / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.rename(target)


def prepare(identifier, stage, backup):
    if SOURCE.is_symlink():
        installed = SOURCE.resolve()
        if installed.parent != SOURCE.parent or not re.fullmatch(
            r"outage-runtime-update-[0-9a-f]{32}", installed.name
        ):
            raise ValueError("Installed source link is not a managed rebuild")
    if not SOURCE.is_dir():
        raise ValueError(
            "No installed runtime; use local-runtime for initial installation"
        )
    for path in (REPORTS, stage):
        if path.is_symlink() or not path.is_dir():
            raise ValueError(
                "Installed runtime/staged source missing or unsafe; use local-runtime only for initial installation"
            )
    if not (SOURCE / ".venv/bin/python").is_file():
        raise ValueError("Installed Python environment missing")
    run(["mountpoint", "-q", str(SPILL)])
    if output(["systemctl", "show", UNIT, "-p", "LoadState", "--value"]) == "masked":
        raise ValueError(
            "API is already masked; resolve the existing maintenance operation"
        )
    old_image = output(["docker", "image", "inspect", "--format", "{{.Id}}", TAG])
    backup.mkdir(mode=0o700)
    shutil.copy2(__file__, backup / "driver.py")
    state = {"phase": "preparing", "masked": False, "old_image": old_image}
    save(backup / "state.json", state)
    with (HISTORY / "active").open("x") as stream:
        stream.write(identifier)
    # A runtime mask prevents even another checkout's supervisor from starting
    # the transient service during the multi-command update.
    state["masked"] = True
    save(backup / "state.json", state)
    run(["systemctl", "mask", "--runtime", UNIT])
    loaded = output(["systemctl", "show", UNIT, "-p", "ActiveState", "--value"])
    if loaded not in {"", "inactive", "failed"}:
        run(["systemctl", "stop", UNIT])
    quiescent()
    if CONFIG.exists():
        if CONFIG.is_symlink():
            raise ValueError("Unsafe API configuration directory")
        shutil.copytree(CONFIG, backup / "configuration")
    state["phase"] = "building"
    save(backup / "state.json", state)
    print(f"Build logs: {backup}/dependencies.log and {backup}/build.log", flush=True)
    run(
        [
            "sh",
            str(stage / HELPERS / "build-guest.sh"),
            str(stage),
            str(backup),
            f"outage-analytical-worker:rebuild-{identifier}",
        ]
    )
    state["phase"] = "prepared"
    save(backup / "state.json", state)


def install(identifier, stage, backup, state):
    if state["phase"] == "installed":
        return  # A completed SSH operation may have lost its response.
    if state["phase"] != "prepared":
        raise ValueError("Replacement build did not complete; roll back and retry")
    quiescent()
    state["phase"] = "installing"
    save(backup / "state.json", state)
    archive_evidence(backup / "evidence")
    SOURCE.rename(backup / "source")
    # Keep the virtualenv at its build path: entry-point shebangs and installed
    # metadata contain that path. Switch the fixed API path to the new release.
    SOURCE.symlink_to(stage, target_is_directory=True)
    # Old profiles must not be usable against new source before validation.
    for name in ("runtime.json", "parser.json"):
        path = CONFIG / name
        if path.exists():
            # /run is normally tmpfs, while history lives on the root disk.
            shutil.move(str(path), str(backup / name))
    run(["docker", "tag", f"outage-analytical-worker:rebuild-{identifier}", TAG])
    state["phase"] = "installed"
    save(backup / "state.json", state)


def finish(backup, state):
    if state["phase"] not in {"installed", "complete"} or not all(
        (CONFIG / name).is_file()
        for name in ("runtime.json", "parser.json", "environment.json")
    ):
        raise ValueError("Validated API configuration has not been installed")
    quiescent()
    run(["systemctl", "unmask", "--runtime", UNIT])
    state["phase"] = "complete"
    save(backup / "state.json", state)
    (HISTORY / "active").unlink()


def rollback(backup, state):
    quiescent()
    installed = (backup / "source").exists()
    if (backup / "source").exists():
        if SOURCE.exists():
            SOURCE.rename(backup / f"failed-source-{uuid4().hex}")
        (backup / "source").rename(SOURCE)
    if (backup / "evidence").exists():
        if installed:
            archive_evidence(backup / f"failed-evidence-{uuid4().hex}")
        restore_evidence(backup / "evidence")
    if (backup / "configuration").exists():
        replacement = CONFIG.with_name(f"outage-api-restore-{uuid4().hex}")
        shutil.copytree(backup / "configuration", replacement)
        if CONFIG.exists():
            shutil.copytree(CONFIG, backup / f"failed-configuration-{uuid4().hex}")
            CONFIG.rename(CONFIG.with_name(f"outage-api-retired-{uuid4().hex}"))
        replacement.rename(CONFIG)
    if state.get("old_image"):
        run(["docker", "tag", state["old_image"], TAG])
    if state.get("masked"):
        run(["systemctl", "unmask", "--runtime", UNIT])
    state["phase"] = "rolled-back"
    save(backup / "state.json", state)
    (HISTORY / "active").unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("prepare", "install", "reset-evidence", "finish", "rollback")
    )
    parser.add_argument("identifier")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{32}", args.identifier):
        parser.error("Invalid rebuild identity")
    if sys.platform != "linux" or os.getuid() != 0:
        parser.error("Run through make local-rebuild on the dedicated guest")
    HISTORY.mkdir(mode=0o700, exist_ok=True)
    backup = HISTORY / args.identifier
    stage = SOURCE.parent / f"outage-runtime-update-{args.identifier}"
    with (HISTORY / "update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "prepare":
            if (HISTORY / "active").exists():
                raise ValueError(
                    "An unfinished rebuild exists; use local-rebuild-resume or local-rebuild-rollback"
                )
            prepare(args.identifier, stage, backup)
        else:
            if not (HISTORY / "active").exists():
                if args.action == "rollback" and not (backup / "source").exists():
                    return 0  # Preparation failed before changing installed source.
                if args.action == "finish" and (backup / "state.json").exists():
                    if (
                        json.loads((backup / "state.json").read_text())["phase"]
                        == "complete"
                    ):
                        return 0
                raise ValueError("No active rebuild matches this recovery request")
            if (HISTORY / "active").read_text() != args.identifier:
                raise ValueError("Rebuild identity does not match the active update")
            state = json.loads((backup / "state.json").read_text())
            if args.action == "install":
                install(args.identifier, stage, backup, state)
            elif args.action == "finish":
                finish(backup, state)
            elif args.action == "rollback":
                rollback(backup, state)
            elif state["phase"] == "installed":
                quiescent()
                archive_evidence(backup / f"validation-attempt-{uuid4().hex}")
            else:
                raise ValueError(
                    "Source installation is incomplete; roll back and retry"
                )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(
            f"Guest rebuild stopped: {error}. Previous build retained in {HISTORY}.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
