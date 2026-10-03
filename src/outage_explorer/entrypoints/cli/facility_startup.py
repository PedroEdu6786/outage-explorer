"""Dedicated facility verification composition wrapper."""

from outage_explorer.bootstrap import build_facility_verifier
from outage_explorer.entrypoints.cli.command import run


def main() -> int:
    return run(build_facility_verifier())


if __name__ == "__main__":
    raise SystemExit(main())
