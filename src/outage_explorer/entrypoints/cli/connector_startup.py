"""Dedicated connector composition wrapper; help is parsed before construction."""

from outage_explorer.bootstrap import execute_connector
from outage_explorer.entrypoints.cli.connector import run


def main() -> int:
    return run(execute_connector)


if __name__ == "__main__":
    raise SystemExit(main())
