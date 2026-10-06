"""One-request limited parser executable; receives no application capabilities."""

import os
import stat
import sys

from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    REQUEST_LIMIT,
    inspect_request,
)


def main() -> int:
    # setpriv applies the parent-death signal before interpreter startup. Verify
    # the parent identity afterward to close its setup race, before SQL reading.
    try:
        if len(sys.argv) != 3:
            return 1
        parent, lease = map(int, sys.argv[1:])
        info = os.fstat(lease)
        if (
            parent != os.getppid()
            or parent <= 1
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
        ):
            return 1
    except (ValueError, OSError):
        return 1
    response = inspect_request(sys.stdin.buffer.read(REQUEST_LIMIT + 1))
    sys.stdout.buffer.write(response)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
