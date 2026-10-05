"""Narrow controlled setup composition wrapper."""

from outage_explorer.bootstrap import execute_access_setup
from outage_explorer.entrypoints.cli.access_setup import run


def main() -> int:
    return run(execute_access_setup)


if __name__ == "__main__":
    raise SystemExit(main())
