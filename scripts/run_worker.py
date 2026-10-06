"""Start the independent refresh worker using the local .env.

Explicit operator entry point, never imported by the product. The worker reads only
its process environment (no dotenv in product code), so this loads .env values
without echoing them and defaults the private per-run staging directory.
"""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGING = ROOT / "data" / "refresh-local"


def environment() -> dict[str, str]:
    values = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
    merged = {**values, **os.environ}
    merged.setdefault("OUTAGE_REFRESH_STAGING", str(DEFAULT_STAGING))
    return merged


def main() -> int:
    env = environment()
    Path(env["OUTAGE_REFRESH_STAGING"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chdir(ROOT)
    print("Refresh worker polling for admitted runs. Ctrl+C stops it.", flush=True)
    os.execve(
        sys.executable,
        [sys.executable, "-m", "outage_explorer.entrypoints.refresh_worker_startup"],
        env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
