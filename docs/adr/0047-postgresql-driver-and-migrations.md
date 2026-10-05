# ADR-0047: Psycopg repositories and explicit Alembic migrations

Status: **Proposed — requires human approval**

Date: 2026-10-04

## Context

ADR-0032 selects PostgreSQL on RDS. The user-access plan requires short explicit
transactions, bounded process-owned connections and repeatable schema setup.
Driver and migration tooling were previously unresolved.

## Proposed decision

Use Psycopg 3 parameterized repositories with a bounded process-owned pool.
Use Alembic and SQLAlchemy only for schema migration infrastructure; domain and
application types remain independent of database libraries and ORM entities.

Run migrations only through explicit setup. A dedicated bounded Psycopg
connection is shared with SQLAlchemy/Alembic in one transaction. A transaction
advisory lock serializes migration runs before reading revision state. Imports,
CLI help and the HTTP factory never connect or migrate. Require verified TLS
for RDS; local PostgreSQL integration tests use an explicitly disposable target.

This recommendation supports FR1, FR12 and TR1–TR4. Dependency compatibility
and actual database execution are implementation verification, not proof of
configured resources. PostgreSQL engine-version selection remains separate.

## Alternatives and consequences

- An ORM for product entities adds mapping and lifecycle behavior without a
  present need; SQLAlchemy is limited to migrations.
- Hand-maintained revision bookkeeping duplicates established tooling.
- Import/startup migrations introduce uncontrolled I/O and concurrent changes.

Serialized explicit migrations need operator execution before seeding. Runtime
transactions stay short and never span provider or analytical work. No SQLite
fallback or cloud database mutation is authorized by this record.
