"""Explicit operational setup transport; help is inert."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from outage_explorer.application.dto import AccessSetupInput, SeedIdentity
from outage_explorer.application.errors import (
    AccessConfigurationError,
    AccessStoreError,
    SeedConflictError,
)


def read_manifest(path: str) -> tuple[SeedIdentity, ...]:
    try:
        file = Path(path)
        if file.stat().st_size > 1024 * 1024:
            raise ValueError
        records = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not 1 <= len(records) <= 1000:
            raise ValueError
        keys = {"identity_issuer", "identity_subject", "email", "role"}
        if any(
            not isinstance(record, dict)
            or set(record) != keys
            or any(not isinstance(value, str) for value in record.values())
            for record in records
        ):
            raise ValueError
        return tuple(SeedIdentity(**record) for record in records)
    except (OSError, ValueError, TypeError):
        raise AccessConfigurationError("Invalid seed manifest") from None


def run(
    execute: Callable[[AccessSetupInput], int | tuple[int, int] | None],
    argv: Sequence[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit PostgreSQL migration, trusted identity seeding, or expired-state cleanup"
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("migrate")
    seed = commands.add_parser("seed")
    seed.add_argument("--manifest", required=True)
    commands.add_parser("cleanup")
    args = parser.parse_args(argv)
    try:
        execute(AccessSetupInput(args.operation, getattr(args, "manifest", None)))
    except (AccessConfigurationError, AccessStoreError, SeedConflictError):
        print(
            "Access setup failed; verify configuration, schema and trusted manifest.",
            file=sys.stderr,
        )
        return 1
    print("Access setup completed.")
    return 0
