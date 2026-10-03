"""Dedicated CLI composition wrapper; no work occurs on import."""

from outage_explorer.bootstrap import build_national_verifier
from outage_explorer.entrypoints.cli.command import run


def main() -> int:
    return run(build_national_verifier())


if __name__ == "__main__":
    raise SystemExit(main())
