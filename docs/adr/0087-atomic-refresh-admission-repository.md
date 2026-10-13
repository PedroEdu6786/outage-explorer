# ADR-0087: Admit queued refresh runs in one ORM repository transaction

Status: Accepted by user direction

Date: 2026-10-12

## Context

`PostgresqlResourcePublicationStore._create_queued_run` inserted a run with raw
SQL. That insert is part of admission: replay after locking, busy-slot check,
active-base validation, run creation and slot reservation must commit together.
A separately decorated insert would break this atomicity.

## Decision

`PostgresqlRefreshRunRepository.admit` owns the full admission transaction with
`@with_session`. It locks coordination, checks for a requester/key replay before
the busy slot, validates the active base in the same session, inserts a mapped
`RefreshRunRecord`, reserves the slot and returns a domain `RefreshRun`.
`replay` also becomes a decorated run-repository read. The publication store
delegates both operations and no longer contains the raw admission helpers.

The record mapping declares the table's existing `admitted_at` database default
so ORM insertion does not send `NULL`. Alembic remains the schema authority;
this mapping change creates no migration.

## Consequences

Admission and publication each retain their own atomic transaction. The
admission-only psycopg base-validation bridge is removed. The existing replay,
busy, frozen-base, initial-load and fail-closed legacy-base behavior remains.
No schema, publication pointer or history changes are required.
