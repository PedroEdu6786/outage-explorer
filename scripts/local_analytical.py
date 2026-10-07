"""Supervise credential renewal for the already provisioned local Linux API.

Explicit operator entry point, never imported by the product. Private credentials
travel only over local/SSH stdin to the trusted API, never to analytical containers.
"""

import argparse
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
        group = run(SSH + ["stat", "-c", "%g", "/run/docker.sock"]).decode().strip()
        if not group.isascii() or not group.isdecimal() or int(group) <= 0:
            raise ValueError("Invalid Docker socket group")
        command = [
            *UNIT_COMMAND[:-2],
            f"--property=SupplementaryGroups={group}",
            *UNIT_COMMAND[-2:],
        ]
        run(SSH + command)
    else:
        run(SSH + ["sudo", "systemctl", "restart", UNIT])


def credential_profiles(environment):
    profiles = {environment.get("AWS_PROFILE") or "default"}
    if environment.get("OUTAGE_ACCESS_DATABASE_MODE") == "iam":
        profiles.add(environment.get("OUTAGE_ACCESS_DATABASE_PROFILE") or "default")
    return sorted(profiles)


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


def transfer(entries, command):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, value in entries.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o600
            info.uid = info.gid = 65534
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    run(SSH + ["sh", "-c", command], data=stream.getvalue())


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
    command = (
        "test -d /run/outage-api && "
        "sudo tar -xf - -C /run/outage-api && "
        "sudo mv /run/outage-api/credentials.json.new /run/outage-api/credentials.json"
    )
    if config is not None:
        for name in ("read_credentials.py", "aws-config", "aws-credentials"):
            command += f" && sudo mv {RUNTIME}/{name}.new {RUNTIME}/{name}"
    transfer(entries, command)


def configure(environment, runtime_path, inspection_path):
    """Install settings only; never start services, migrate or publish."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from outage_explorer.infrastructure.sql_validation.configuration import (
        read_inspection_config,
    )
    from outage_explorer.infrastructure.worker_runtime.configuration import (
        read_runtime_config,
    )

    profile, evidence = read_runtime_config(runtime_path)
    parser, review = read_inspection_config(inspection_path)
    if evidence is None or review is None or parser.python != PYTHON:
        raise ValueError("Matching reviewed runtime/parser configuration required")
    evidence.require_ready(profile, started=True, local_acceptance=True)
    review.require_ready(parser)
    prefixes = (
        "OUTAGE_AUTH_",
        "OUTAGE_ACCESS_DATABASE_",
        "COGNITO_",
        "OUTAGE_S3_",
        "OUTAGE_REFRESH_",
    )
    values = {
        key: value
        for key, value in environment.items()
        if value is not None
        and (
            key.startswith(prefixes)
            or key in {"AWS_PROFILE", "AWS_REGION", "OUTAGE_DATA_HTTP_ENABLED"}
        )
    }
    entries = {
        "start.py": (ROOT / "scripts/local_api_entrypoint.py").read_bytes(),
        "runtime.json": runtime_path.read_bytes(),
        "parser.json": inspection_path.read_bytes(),
    }
    ca_path = values.get("OUTAGE_ACCESS_DATABASE_SSLROOTCERT")
    dsn = values.get("OUTAGE_ACCESS_DATABASE_DSN")
    if dsn:
        connection = conninfo_to_dict(dsn)
        ca_path = connection.get("sslrootcert") or ca_path
        if ca_path:
            connection["sslrootcert"] = RUNTIME + "/rds-ca.pem"
            values["OUTAGE_ACCESS_DATABASE_DSN"] = make_conninfo(**connection)
    if ca_path:
        entries["rds-ca.pem"] = Path(ca_path).expanduser().read_bytes()
        if values.get("OUTAGE_ACCESS_DATABASE_MODE") == "iam":
            values["OUTAGE_ACCESS_DATABASE_SSLROOTCERT"] = RUNTIME + "/rds-ca.pem"
    values.update(
        PATH="/usr/bin:/bin",
        HOME="/nonexistent",
        PYTHONDONTWRITEBYTECODE="1",
        AWS_CONFIG_FILE=RUNTIME + "/aws-config",
        AWS_SHARED_CREDENTIALS_FILE=RUNTIME + "/aws-credentials",
        AWS_EC2_METADATA_DISABLED="true",
    )
    entries["environment.json"] = json.dumps(values).encode()
    # The surrounding sh is unprivileged; only fixed host operations use sudo.
    # Refuse live reconfiguration and symlink destinations; never print settings.
    command = (
        "if systemctl is-active --quiet outage-api-local; then exit 1; fi; "
        "test ! -L /run/outage-api && "
        "sudo install -d -o 65534 -g 65534 -m 0700 /run/outage-api && "
        "sudo tar -xf - -C /run/outage-api"
    )
    transfer(entries, command)


def main(argv=None):
    global SSH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native", action="store_true", help="Use this Linux host instead of Colima"
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Install private API settings without starting it",
    )
    parser.add_argument(
        "--config", type=Path, help="Reviewed analytical JSON (configuration only)"
    )
    parser.add_argument(
        "--inspection-config",
        type=Path,
        help="Reviewed parser JSON (configuration only)",
    )
    args = parser.parse_args(argv)
    if args.native:
        if sys.platform != "linux":
            parser.error("--native requires the Linux Docker daemon host")
        SSH = []
    if args.configure != (
        args.config is not None and args.inspection_config is not None
    ) or (not args.configure and (args.config or args.inspection_config)):
        parser.error("--configure requires both --config and --inspection-config")
    environment = {**dotenv_values(ROOT / ".env"), **os.environ}
    if args.configure:
        try:
            configure(environment, args.config, args.inspection_config)
        except Exception:
            print(
                "API configuration failed. Check reviewed files, CA path and stopped service; private diagnostics suppressed.",
                file=sys.stderr,
            )
            return 1
        print("Private API configuration installed; API and refresh remain stopped.")
        return 0
    state = ROOT / ".local-runtime"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / "credential-sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Local API credential renewal is already running.", file=sys.stderr)
            return 1
        profiles = credential_profiles(environment)
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
                "Local API startup failed. Check the Linux service/configuration and AWS login.",
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
