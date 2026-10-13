# ADR-0074: Pilot SQLAlchemy ORM for refresh-run reads

Status: Accepted for a scoped pilot by user direction

Date: 2026-10-12

## Context

The user selected the proposed ORM/repository pattern but requested a limited
scenario to evaluate its suitability. Existing application-owned store protocols
already provide repository boundaries. SQLAlchemy and Alembic are installed;
runtime adapters currently use psycopg and handwritten SQL.

## Decision

Pilot synchronous SQLAlchemy ORM only in `RefreshStore.get_run`, implemented by
`PostgresqlResourcePublicationStore`. Keep ORM mappings and sessions within
`infrastructure/postgresql/`; return the existing domain `RefreshRun` value.
Use short-lived sessions backed by the existing bounded psycopg pool with
SQLAlchemy pooling disabled. Preserve credentials, timeouts, process ownership,
lazy connection creation and explicit close. Retain current schema/migrations.

## Consequences

Typed database attributes and explicit domain mapping can be evaluated against
the existing SQL implementation. The temporary mix of ORM reads and raw SQL
requires row-format and connection-reuse tests. Mapping metadata is incomplete
for schema management and must not become Alembic's autogeneration source.

No other repository method is migrated by this decision. Approval to expand to
refresh writes or access persistence is not implied. The pilot leaves all
publication locking, lease fencing and uncertain-commit recovery contracts intact.
