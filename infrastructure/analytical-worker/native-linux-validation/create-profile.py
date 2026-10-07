"""Create a nonsecret candidate from the dedicated guest's actual identities."""

import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from outage_explorer.infrastructure.sql_validation.configuration import (
    InspectionProfile,
)
from outage_explorer.infrastructure.sql_validation.subprocess_inspection import (
    InspectionBounds,
)
from outage_explorer.infrastructure.worker_runtime.configuration import (
    WORKER_PROTOCOL_VERSION,
    RuntimeProfile,
)

root = Path("/var/lib/outage-runtime-validation")
spill = Path("/var/lib/outage-analytical/spill")
info = spill.stat()
capacity = os.statvfs(spill)
image = subprocess.check_output(
    [
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        "outage-analytical-worker:validation",
    ],
    text=True,
).strip()
version = subprocess.check_output(
    ["docker", "version", "--format", "{{.Server.Version}}"], text=True
).strip()
platform = subprocess.check_output(
    ["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], text=True
).strip()
profile = RuntimeProfile(
    protocol_version=WORKER_PROTOCOL_VERSION,
    image_id=image,
    daemon_endpoint="unix:///run/docker.sock",
    docker_executable="/usr/bin/docker",
    platform=platform,
    daemon_version=version,
    filesystem_identity="outage-runtime-private-linux-validation",
    staging_root=str(root / "owned/staging"),
    cache_root=str(root / "owned/cache"),
    result_root=str(root / "owned/results"),
    temporary_backend="quota-disk",
    temporary_root=str(spill),
    temporary_filesystem_identity=f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}:{capacity.f_fsid}",
)
path = root / "candidate.json"


def executable_digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


python = "/opt/outage-runtime-validation/.venv/bin/python"
parser = InspectionProfile(
    bounds=InspectionBounds(4, 1, 268435456, 1, 1024, 65536, 10000, 64),
    python=python,
    prlimit="/usr/bin/prlimit",
    setpriv="/usr/bin/setpriv",
    ownership_root=str(root / "parser-ownership"),
    python_sha256=executable_digest(python),
    prlimit_sha256=executable_digest("/usr/bin/prlimit"),
    setpriv_sha256=executable_digest("/usr/bin/setpriv"),
)
parser_path = root / "parser-candidate.json"
if path.exists() or parser_path.exists():
    raise SystemExit("Candidate output exists; preserve previous host evidence")
with path.open("x") as stream:
    json.dump({"profile": asdict(profile), "evidence": None}, stream, indent=2)
os.chmod(path, 0o600)
with parser_path.open("x") as stream:
    json.dump({"profile": asdict(parser), "evidence": None}, stream, indent=2)
os.chmod(parser_path, 0o600)
print(
    json.dumps(
        {
            "protocol_version": profile.protocol_version,
            "image_id": image,
            "profile_identity": profile.identity,
            "platform": profile.platform,
            "daemon_version": version,
            "parser_profile_identity": parser.identity,
            "spill_capacity_bytes": capacity.f_blocks * capacity.f_frsize,
            "spill_inodes": capacity.f_files,
        },
        sort_keys=True,
    )
)
