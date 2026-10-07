"""Explicit Make-driven setup of the dedicated Apple Silicon Colima environment."""

import argparse
import base64
import os
import platform
import shlex
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-runtime"
GUEST = "/opt/outage-runtime-validation"
REPORTS = "/var/lib/outage-runtime-validation"
HELPERS = "infrastructure/analytical-worker/native-linux-validation"
SSH = ["colima", "ssh", "--profile", "outage-runtime", "--"]
SOURCE = [
    "src",
    "tests",
    "scripts",
    "infrastructure/analytical-worker",
    "pyproject.toml",
    "requirements-dev.txt",
    "README.md",
]


def run(arguments, **kwargs):
    return subprocess.run(arguments, cwd=ROOT, check=True, **kwargs)


def remote(body):
    run(SSH + ["sh", "-s"], input=("set -eu\n" + body).encode())


def controller(body):
    # Transfer the fixed command body through stdin, not a remote shell argument.
    encoded = base64.b64encode(("set -eu\ncd " + GUEST + "\n" + body).encode()).decode()
    remote(
        "group=$(stat -c %g /run/docker.sock)\n"
        f'printf %s {encoded} | base64 -d | sudo setpriv --reuid=65534 --regid=65534 --groups="$group" '
        "env -i PATH=/usr/bin:/bin HOME=/nonexistent PYTHONDONTWRITEBYTECODE=1 /bin/sh -s\n"
    )


def execute(action, reviewer):
    STATE.mkdir(mode=0o700, exist_ok=True)
    if action == "dependencies":
        run(
            [
                "brew",
                "install",
                "git",
                "make",
                "python@3.12",
                "colima",
                "docker",
                "awscli",
                "nvm",
            ]
        )
        print(
            "Follow brew's nvm shell initialization instructions. Make selects installed Python automatically."
        )
    elif action == "ca":
        descriptor, temporary = tempfile.mkstemp(prefix="rds-ca-", dir=STATE)
        os.close(descriptor)
        try:
            run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--proto",
                    "=https",
                    "--proto-redir",
                    "=https",
                    "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
                    "--output",
                    temporary,
                ]
            )
            if b"-----BEGIN CERTIFICATE-----" not in Path(temporary).read_bytes():
                raise ValueError("RDS CA download did not contain certificates")
            os.replace(temporary, STATE / "rds-ca.pem")
        finally:
            Path(temporary).unlink(missing_ok=True)
        print(f"RDS TLS trust bundle: {STATE / 'rds-ca.pem'}")
    elif action == "runtime":
        # Refuse stale exports before creating or changing the guest.
        run(["git", "diff", "--exit-code", "--quiet", "HEAD", "--", *SOURCE])
        run(
            [
                "git",
                "archive",
                "--format=tar",
                f"--output={STATE / 'source.tar'}",
                "HEAD",
                *SOURCE,
            ]
        )
        run(["sh", f"{HELPERS}/start-colima.sh"])
        remote((ROOT / HELPERS / "prepare-guest.sh").read_text())
        with (STATE / "source.tar").open("rb") as stream:
            run(SSH + ["sudo", "tar", "-xf", "-", "-C", GUEST], stdin=stream)
        remote(f"sh {GUEST}/{HELPERS}/build-guest.sh\n")
    elif action == "candidate":
        controller(f".venv/bin/python {HELPERS}/create-profile.py\n")
    elif action == "validate":
        pytest = ".venv/bin/python -m pytest -q -p no:cacheprovider"
        controller(
            f"{pytest} tests/unit tests/architecture tests/test_local_analytical.py tests/test_local_runtime_setup.py tests/test_local_machine.py tests/integration/test_sql_compatibility.py --junitxml={REPORTS}/controlled.xml\n"
            f"{pytest} tests/integration/test_sql_parser_process.py --junitxml={REPORTS}/parser.xml\n"
            f"OUTAGE_RUNTIME_TEST_PROFILE={REPORTS}/candidate.json OUTAGE_RUNTIME_DOCKER_EXECUTABLE=/usr/bin/docker {pytest} tests/acceptance/test_query_runtime.py -m runtime_docker --junitxml={REPORTS}/docker.xml\n"
        )
    elif action == "reports":
        controller(
            f"cat {REPORTS}/controlled.xml {REPORTS}/parser.xml {REPORTS}/docker.xml {REPORTS}/owned/validation-reports/*.json\n"
        )
    elif action == "review":
        controller(
            f".venv/bin/python scripts/review_local_runtime.py --reviewer {shlex.quote(reviewer)} --accept-local-containment\n"
        )
    elif action == "configure":
        for name in ("runtime-reviewed.json", "parser-reviewed.json"):
            result = run(
                SSH + ["sudo", "cat", f"{REPORTS}/{name}"], capture_output=True
            )
            path = STATE / name
            with path.open("wb") as stream:
                os.chmod(path, 0o600)
                stream.write(result.stdout)
        run(
            [
                str(ROOT / ".venv/bin/python"),
                "scripts/local_analytical.py",
                "--configure",
                "--config",
                str(STATE / "runtime-reviewed.json"),
                "--inspection-config",
                str(STATE / "parser-reviewed.json"),
            ]
        )
    elif action == "forward":
        result = run(
            ["colima", "ssh-config", "--profile", "outage-runtime"], capture_output=True
        )
        path = STATE / "ssh-config"
        with path.open("wb") as stream:
            os.chmod(path, 0o600)
            stream.write(result.stdout)
        run(
            [
                "ssh",
                "-F",
                str(path),
                "-o",
                "ExitOnForwardFailure=yes",
                "-N",
                "-L",
                "127.0.0.1:8000:127.0.0.1:8000",
                "colima-outage-runtime",
            ]
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "dependencies",
            "ca",
            "runtime",
            "candidate",
            "validate",
            "reports",
            "review",
            "configure",
            "forward",
        ],
    )
    parser.add_argument("--reviewer", default="")
    args = parser.parse_args(argv)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error(
            "Requires Apple Silicon macOS and the dedicated Colima outage-runtime VM"
        )
    if args.action == "review" and not args.reviewer.strip():
        parser.error('Read make local-reports first, then supply REVIEWER="Your name"')
    try:
        execute(args.action, args.reviewer.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(
            1, "Setup step failed; resolve the reported step before continuing.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
