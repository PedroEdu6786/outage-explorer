"""Dedicated connector composition wrapper; help is parsed before construction."""

from outage_explorer.bootstrap import (
    execute_connector,
    execute_connector_artifacts,
    execute_connector_to_s3,
)
from outage_explorer.entrypoints.cli.connector import run


def main() -> int:
    return run(
        execute_connector,
        execute_artifacts=execute_connector_artifacts,
        execute_durable=execute_connector_to_s3,
    )


if __name__ == "__main__":
    raise SystemExit(main())
