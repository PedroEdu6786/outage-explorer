"""Exact startup seam; explicit invocation owns analytical start and close."""

from outage_explorer.bootstrap import execute_analytical_http
from outage_explorer.entrypoints.http.analytical_command import run


def main() -> int:
    return run(execute_analytical_http)


if __name__ == "__main__":
    raise SystemExit(main())
