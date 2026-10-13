# ADR-0077: Extend the refresh ORM read pilot to latest

Status: Accepted by user direction

Date: 2026-10-12

## Context and decision

The user requested the same repository and session-decorator pattern for
`latest()`. Extend ADR-0074's read pilot to `get_run` and `latest` only.
`PostgresqlRefreshRunRepository` owns both ORM queries; the existing publication
store delegates to it. Keep the injected shared pool, per-call session scope and
plain domain results.

Preserve the existing latest-run contract: active run first, admission timestamp
descending next, then UUID descending. A missing coordination row or no run rows
returns `None`, matching the original join. Do not retain ORM state across calls.

The coordination mapping contains only the singleton key and active run ID needed
for this read. Both read mappings share infrastructure metadata, which remains
unsuitable for schema creation or Alembic autogeneration. No schema change or
ORM migration of admission, ownership, publication or recovery writes is selected.
