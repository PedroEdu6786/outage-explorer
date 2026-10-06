"""One-request limited parser executable; receives no application capabilities."""

import sys

from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    REQUEST_LIMIT,
    inspect_request,
)


def main() -> int:
    response = inspect_request(sys.stdin.buffer.read(REQUEST_LIMIT + 1))
    sys.stdout.buffer.write(response)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
