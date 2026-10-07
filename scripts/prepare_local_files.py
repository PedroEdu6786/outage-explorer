"""Prepare ignored local settings without replacing an existing environment."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(root):
    state = root / ".local-runtime"
    state.mkdir(mode=0o700, exist_ok=True)
    state.chmod(0o700)
    environment = root / ".env"
    try:
        with environment.open("x") as stream:
            os.chmod(environment, 0o600)
            stream.write((root / ".env.example").read_text())
    except FileExistsError:
        pass
    environment.chmod(0o600)


if __name__ == "__main__":
    prepare(ROOT)
