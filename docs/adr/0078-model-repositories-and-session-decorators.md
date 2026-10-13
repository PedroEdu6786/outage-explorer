# ADR-0078: Centralize model queries in repositories with session decorators

Status: Accepted by user direction

Date: 2026-10-12

Extends ADR-0074 and ADR-0077: the validated read pattern is the project convention
for new and refactored operational persistence, not merely an experimental option.
The existing implementation remains limited to the migrated refresh reads.

## Context

The refresh pilot separates domain values, SQLAlchemy record mappings and a
dedicated query repository. The user selected this as the appropriate solution
and explicitly rejected raw queries mixed with process logic. Code that still
combines those responsibilities must not be treated as a pattern for new work.

## Decision

- Put operational PostgreSQL model queries in dedicated repositories under
  `infrastructure/postgresql/`, grouped by the model or cohesive model concern.
  ORM records declare storage mappings; domain objects express domain meaning.
- Use SQLAlchemy ORM and SQL expressions in repositories. Use `@with_session`
  on repository operation boundaries to inject a short-lived session, keeping
  lifecycle boilerplate out of the query method.
- Application services and process coordinators invoke application-owned ports
  or injected repositories as their layer permits. They do not construct SQL,
  manipulate ORM records or execute database calls inline with process logic.
  Moving a coordinator into infrastructure does not exempt it from this rule.
- Bootstrap constructs and injects concrete collaborators. Repositories return
  domain values/DTOs before the session closes; no ORM object or session escapes
  to the application/domain layers.
- Keep the existing bounded, process-owned pool, credential handling, timeouts,
  sanitized errors and explicit cleanup. Do not add generic CRUD hierarchies,
  implicit connections or a long-lived session shared between threads.
- Preserve atomicity. Each decorated call has its own transaction; a multi-table
  atomic operation must execute within one shared session/transaction boundary,
  not a sequence of independently decorated calls. Transaction-internal query
  helpers receive that session. Do not hold it across EIA/S3/analytical work.

## Scope and consequences

The reference is `PostgresqlRefreshRunRepository.get_run/latest` with
`RefreshRunRecord`, `RefreshCoordinationRecord` and `@with_session`.
Existing raw-SQL persistence in publication/access adapters is legacy to migrate
in explicitly scoped work. This decision documents the standard; it does not
claim those paths are migrated or authorize a bulk rewrite in this task.

Schema migrations and low-level connection configuration may still require SQL.
Isolated user SQL and analytical DuckDB/Parquet adapters have their own accepted
contracts; this operational-persistence convention does not replace them.
Do not use those cases as justification for raw model queries in process code.
Any necessary database-specific raw statement in future operational persistence
must be justified and isolated inside the responsible repository.

Mapped read metadata remains incomplete for DDL and must not drive schema
creation or migration autogeneration. Future write migrations must verify locks,
lease fencing, immutable history and uncertain-commit recovery on PostgreSQL.

## Reference

See [Required persistence repository pattern](../context/persistence-repositories.md).
