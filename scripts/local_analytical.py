"""Supervise credential renewal for the already provisioned local Linux API.

Explicit operator entry point, never imported by the product. Private credentials
travel only over SSH stdin to the trusted API, never to analytical containers.
"""

import configparser
import fcntl
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SSH = ["colima", "ssh", "--profile", "outage-runtime", "--"]
PYTHON = "/opt/outage-runtime-validation/.venv/bin/python"
RUNTIME = "/run/outage-api"
UNIT = "outage-api-local"
# The guest service is transient: stopping it unloads the unit, so it must be
# recreated with the same properties it was activated with.
UNIT_COMMAND = [
    "sudo",
    "systemd-run",
    f"--unit={UNIT}",
    "--property=User=65534",
    "--property=Group=65534",
    "--property=SupplementaryGroups=991",
    "--property=WorkingDirectory=/opt/outage-runtime-validation",
    "--property=UMask=0077",
    "--property=KillSignal=SIGINT",
    "--property=TimeoutStopSec=30",
    "--property=KillMode=control-group",
    PYTHON,
    f"{RUNTIME}/start.py",
]

# Credential-process stdout is consumed privately by the SDK, never by our logs.
READER = """import json, sys
try:
    with open('/run/outage-api/credentials.json') as stream:
        value = json.load(stream)[sys.argv[1]]
    print(json.dumps(value))
except Exception:
    print('Local application credentials unavailable', file=sys.stderr)
    raise SystemExit(1)
"""


def run(arguments, *, data=None, timeout=30):
    result = subprocess.run(
        arguments, input=data, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode:
        # CLI errors may contain request/credential diagnostics. Never relay them.
        raise RuntimeError("Local runtime command failed")
    return result.stdout


def export_credentials(profiles):
    documents = {}
    for profile in profiles:
        raw = run(
            [
                "aws",
                "configure",
                "export-credentials",
                "--profile",
                profile,
                "--format",
                "process",
            ]
        )
        value = json.loads(raw)
        if value.get("Version") != 1 or not all(
            isinstance(value.get(key), str) and value[key]
            for key in ("AccessKeyId", "SecretAccessKey")
        ):
            raise ValueError("Invalid local credential export")
        if "Expiration" in value:
            expires = datetime.fromisoformat(value["Expiration"].replace("Z", "+00:00"))
            if (
                expires.tzinfo is None
                or (expires - datetime.now(UTC)).total_seconds() <= 30
            ):
                raise ValueError("Local AWS login credentials expired")
        documents[profile] = value
    return documents


def start_service():
    """Restart the transient guest unit, creating it first if it was stopped."""
    state = run(SSH + ["systemctl", "show", UNIT, "-p", "LoadState", "--value"])
    if state.decode().strip() == "not-found":
        run(SSH + UNIT_COMMAND)
    else:
        run(SSH + ["sudo", "systemctl", "restart", UNIT])


def credential_config(profiles):
    config = configparser.RawConfigParser()
    for profile in profiles:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile):
            raise ValueError("Unsupported local profile name")
        section = "default" if profile == "default" else "profile " + profile
        config[section] = {
            "credential_process": f"{PYTHON} {RUNTIME}/read_credentials.py {profile}"
        }
    stream = io.StringIO()
    config.write(stream)
    return stream.getvalue().encode()


def install(documents, config=None):
    entries = {"credentials.json.new": json.dumps(documents).encode()}
    if config is not None:
        entries.update(
            {
                "aws-config.new": config,
                "aws-credentials.new": b"",  # Remove the stale static provider.
                "read_credentials.py.new": READER.encode(),
            }
        )
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, value in entries.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o600
            info.uid = info.gid = 65534
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    command = (
        "test -d /run/outage-api && "
        "sudo tar -xf - -C /run/outage-api && "
        "sudo mv /run/outage-api/credentials.json.new /run/outage-api/credentials.json"
    )
    if config is not None:
        for name in ("read_credentials.py", "aws-config", "aws-credentials"):
            command += f" && sudo mv {RUNTIME}/{name}.new {RUNTIME}/{name}"
    run(SSH + ["sh", "-c", command], data=stream.getvalue())


def main():
    state = ROOT / ".local-runtime"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / "credential-sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Local API credential renewal is already running.", file=sys.stderr)
            return 1
        environment = {**dotenv_values(ROOT / ".env"), **os.environ}
        profiles = sorted(
            {
                environment.get("AWS_PROFILE") or "default",
                environment.get("OUTAGE_ACCESS_DATABASE_PROFILE") or "default",
            }
        )
        started = False
        try:
            config = credential_config(profiles)
            install(export_credentials(profiles), config)
            start_service()
            started = True
            print(
                "Local API: http://localhost:8000; credential renewal active. Ctrl+C stops the API.",
                flush=True,
            )
            while True:
                time.sleep(60)
                try:
                    install(export_credentials(profiles))
                except Exception:
                    print(
                        "Credential renewal failed; retrying in 60 seconds. Check the existing AWS login.",
                        file=sys.stderr,
                        flush=True,
                    )
        except KeyboardInterrupt:
            return 0
        except Exception:
            print(
                "Local API startup failed. Check the existing Colima service/configuration and AWS login.",
                file=sys.stderr,
            )
            return 1
        finally:
            if started:
                try:
                    run(SSH + ["sudo", "systemctl", "stop", "outage-api-local"])
                except Exception:
                    print(
                        "Could not stop local API; use make stop-analytical.",
                        file=sys.stderr,
                    )


if __name__ == "__main__":
    raise SystemExit(main())
