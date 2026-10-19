"""Rebuild current source in the existing Colima guest without prompts."""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from uuid import uuid4

import local_machine as local

HISTORY = "/var/lib/outage-runtime-history"


def working_tree_archive():
    """Snapshot regular allowlisted working files; never alter Git state."""
    result = local.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *local.SOURCE,
        ],
        capture_output=True,
    )
    descriptor, temporary = tempfile.mkstemp(
        prefix="rebuild-", suffix=".tar", dir=local.STATE
    )
    os.close(descriptor)
    try:
        with tarfile.open(temporary, "w") as archive:
            for name in sorted(set(os.fsdecode(result.stdout).split("\0")) - {""}):
                relative = Path(name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not any(
                        relative == Path(root) or Path(root) in relative.parents
                        for root in local.SOURCE
                    )
                ):
                    raise ValueError("Unsafe source export path")
                if any(
                    part.startswith(".")
                    or part
                    in {
                        "__pycache__",
                        "build",
                        "dist",
                        "credentials",
                        "secrets",
                        "credentials.json",
                        "secrets.json",
                        "aws-config",
                        "aws-credentials",
                    }
                    or part.endswith(".egg-info")
                    for part in relative.parts
                ) or relative.suffix.lower() in {
                    ".pyc",
                    ".pyo",
                    ".pem",
                    ".key",
                    ".p12",
                    ".pfx",
                }:
                    continue
                path = local.ROOT / relative
                if any(
                    item.is_symlink()
                    for item in (path, *path.parents)
                    if local.ROOT in item.parents
                ):
                    raise ValueError(f"Source symlinks are unsupported: {relative}")
                if not path.exists():
                    continue
                if not path.is_file():
                    raise ValueError(f"Source must be a regular file: {relative}")
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o755 if info.mode & 0o111 else 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
        path = local.STATE / "rebuild-source.tar"
        os.replace(temporary, path)
        return path
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(state):
    path = local.STATE / "rebuild.json"
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(state, stream)
    temporary.replace(path)


def guest(state, action):
    identifier = state["identifier"]
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid local rebuild identity")
    script = f"{HISTORY}/{identifier}/driver.py"
    if action == "prepare":
        script = f"/opt/outage-runtime-update-{identifier}/scripts/rebuild_guest.py"
    if action == "rollback":
        local.remote(
            f"if sudo -n test -f {script}; then sudo -n python3 {script} rollback {identifier}; "
            f"else sudo -n python3 /opt/outage-runtime-update-{identifier}/scripts/rebuild_guest.py rollback {identifier}; fi\n"
        )
    else:
        local.run(local.SSH + ["sudo", "-n", "python3", script, action, identifier])


def step(state, name, operation):
    state["next"] = name
    save(state)
    print(f"Rebuild: {name}", flush=True)
    operation()


def configure(state):
    step(state, "configure", lambda: local.execute("configure", ""))
    step(state, "finish", lambda: guest(state, "finish"))
    state["next"] = "complete"
    save(state)
    print(
        "Rebuild complete. Start the API with make run-analytical; keep refresh idle."
    )


def validate(state):
    # Each attempt gets new evidence; failed reports are retained outside lookup.
    guest(state, "reset-evidence")
    for action in ("candidate", "validate", "reports"):
        step(state, action, lambda action=action: local.execute(action, ""))
    step(
        state,
        "automated-evidence",
        lambda: local.controller(
            ".venv/bin/python scripts/review_local_runtime.py --automated-local-rebuild\n"
        ),
    )
    configure(state)


def check_refresh_idle():
    result = subprocess.run(
        ["pgrep", "-f", r"outage_explorer\.entrypoints\.refresh_worker_startup"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 1:
        raise ValueError(
            "Stop the independent local refresh worker before rebuilding; it is never stopped automatically"
        )


def rebuild():
    previous = local.STATE / "rebuild.json"
    if previous.exists() and json.loads(previous.read_text())["next"] not in {
        "complete",
        "rolled-back",
    }:
        raise ValueError(
            "Unfinished rebuild: use make local-rebuild-resume or make local-rebuild-rollback"
        )
    print("Checking the existing Colima guest...", flush=True)
    check_refresh_idle()
    local.run(["colima", "status", "--profile", "outage-runtime"])
    local.remote("sudo -n true\n")
    archive = working_tree_archive()
    state = {"identifier": uuid4().hex, "next": "upload"}
    identifier = state["identifier"]
    stage = f"/opt/outage-runtime-update-{identifier}"
    # No installed resources have changed if upload fails; it is safe to retry.
    local.remote(f"sudo -n mkdir -m 0755 {stage}\n")
    with archive.open("rb") as stream:
        local.run(
            local.SSH + ["sudo", "-n", "tar", "-xf", "-", "-C", stage], stdin=stream
        )
    step(state, "prepare", lambda: guest(state, "prepare"))
    step(state, "install", lambda: guest(state, "install"))
    validate(state)


def recover(action):
    check_refresh_idle()
    path = local.STATE / "rebuild.json"
    if not path.exists():
        raise ValueError("No rebuild record exists in this checkout")
    state = json.loads(path.read_text())
    if state["next"] in {"complete", "rolled-back"}:
        raise ValueError(
            "No unfinished rebuild; use make local-rebuild for new changes"
        )
    if action == "rollback":
        guest(state, "rollback")
        state["next"] = "rolled-back"
        save(state)
        print("Previous build/configuration restored. API remains stopped.")
    elif state["next"] in {"configure", "finish"}:
        if state["next"] == "configure":
            configure(state)
        else:
            guest(state, "finish")
            state["next"] = "complete"
            save(state)
    elif state["next"] == "install":
        guest(state, "install")
        validate(state)
    elif state["next"] in {"candidate", "validate", "reports", "automated-evidence"}:
        validate(state)
    else:
        raise ValueError(
            "Preparation did not complete; run make local-rebuild-rollback, then make local-rebuild"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="rebuild",
        choices=("rebuild", "resume", "rollback"),
    )
    args = parser.parse_args(argv)
    if local.platform.system() != "Darwin" or local.platform.machine() != "arm64":
        parser.error(
            "Requires Apple Silicon macOS and the existing outage-runtime Colima guest"
        )
    local.STATE.mkdir(mode=0o700, exist_ok=True)
    try:
        with (local.STATE / "rebuild.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "rebuild":
                rebuild()
            else:
                recover(args.action)
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        KeyboardInterrupt,
    ) as error:
        print(f"Rebuild stopped: {error}", file=sys.stderr)
        print(
            "Existing data and previous builds are preserved. Check the failed stage/logs; "
            "use make local-rebuild-resume or make local-rebuild-rollback for an unfinished update.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
