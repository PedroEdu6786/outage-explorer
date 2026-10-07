"""Private operator entry point installed by local_analytical --configure.

Settings/credentials belong to the trusted API. Product composition still owns
authorization, parser/worker isolation and analytical lifecycle enforcement.
"""

import json
import os
from pathlib import Path

RUNTIME = Path("/run/outage-api")
PYTHON = "/opt/outage-runtime-validation/.venv/bin/python"


def main():
    with (RUNTIME / "environment.json").open() as stream:
        environment = json.load(stream)
    os.execve(
        PYTHON,
        [
            PYTHON,
            "-m",
            "outage_explorer.entrypoints.http.analytical_startup",
            "--config",
            str(RUNTIME / "runtime.json"),
            "--inspection-config",
            str(RUNTIME / "parser.json"),
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        environment,
    )


if __name__ == "__main__":
    main()
