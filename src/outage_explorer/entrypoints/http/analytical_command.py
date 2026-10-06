"""Nonsecret local serving arguments; help never constructs runtime resources."""

import argparse
from collections.abc import Callable

from outage_explorer.application.errors import RuntimeUnavailableError


def run(execute: Callable[[str, str, int], int], argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit reviewed local analytical API"
    )
    parser.add_argument(
        "--config", required=True, help="Nonsecret profile/evidence JSON"
    )
    parser.add_argument(
        "--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1"
    )
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        return execute(args.config, args.host, args.port)
    except (RuntimeUnavailableError, ValueError, OSError):
        parser.exit(1, "Reviewed analytical runtime unavailable\n")
