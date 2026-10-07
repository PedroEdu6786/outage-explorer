"""Explicit paired-protocol image startup; parent must match its validated limits."""

import sys

from outage_explorer.bootstrap import build_query_worker
from outage_explorer.entrypoints.query_worker import run


def main() -> int:
    return run(build_query_worker(), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
