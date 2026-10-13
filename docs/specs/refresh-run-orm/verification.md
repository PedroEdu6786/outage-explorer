# Refresh-run ORM pilot verification

Date: 2026-10-12

## Implemented scope

`PostgresqlResourcePublicationStore.get_run` reads a typed SQLAlchemy
`RefreshRunRecord` and returns the existing domain value. Other methods retain
their existing SQL. No schema migrations, dependency changes, deployed services
or application interfaces were changed.

The same bounded psycopg pool serves raw SQL and ORM sessions. SQLAlchemy uses
NullPool; `close_returns=True` and a row-factory reset allow safe checkout reuse.
The strict configuration model reads persisted JSON dates through its JSON
validation API. The original dictionary-to-domain mapper remains for raw queries.

## Checks actually run

- Ruff lint and format checks: PostgreSQL package and new integration tests pass.
- Strict mypy: all 164 source files pass.
- Architecture and refresh unit tests: 218 pass.
- PostgreSQL integration tests: 111 pass across `test_refresh_run_orm`,
  `test_data_api_postgresql`, `test_refresh_recovery`,
  `test_user_access_postgresql` and `test_postgresql_iam`.
- The database was a new disposable PostgreSQL 18 cluster under `/private/tmp`,
  listening only on loopback port 55449. It was stopped after verification.
  No RDS connection or live refresh was used.

New tests cover complete mapping for accepted/running/succeeded/failed/retained/
interrupted runs, use after pool closure, missing IDs, fresh committed state,
concurrent ORM/raw reads with the four-connection bound, sanitized query failures,
all slots reusable after errors, transaction rollback and inert construction with
closed/forked resource rejection.

## Assessment and limits

The pilot validates the read path and shared-pool integration. Typed attributes
and keyword-based conversion make the stored shape explicit, but require an
additional mapped model and session plumbing for a small query. Evaluate those
files before expanding. It does not establish performance improvements or ORM
write-path correctness for publication/lease/recovery. Those paths were exercised
as regression checks against their existing raw SQL implementations.

Changes remain uncommitted at the user's direction.

## Session decorator follow-up — 2026-10-12

The user selected a typed `@with_session` decorator instead of a Unit of Work
abstraction. `get_run` now receives an injected session and only queries/maps the
record. Its public call signature remains `get_run(run_id)`, including keyword
calls. The decorator delegates transaction completion, error translation and
cleanup to the existing pool session context; every invocation has its own scope.

Verification after this change: Ruff lint/format passed; strict mypy passed for
167 source files. An additional static call-site check confirmed positional and
keyword invocation, exact `RefreshRun | None` return typing and `RefreshStore`
compatibility. Decorator/refresh unit and architecture tests: 231 passed.
The same five PostgreSQL integration modules listed above: 111 passed, including
mapping, concurrent reads, failures, recovery and pool lifecycle checks. New unit
tests cover session injection, fresh scopes, argument forwarding and cleanup
before returning or propagating an exception. The disposable loopback cluster
was stopped after verification. Nothing committed.

## Dedicated repository follow-up — 2026-10-12

Moved the decorated ORM query into `PostgresqlRefreshRunRepository`, leaving
`RefreshRunRecord` focused on mapping. Bootstrap injects the repository into
`PostgresqlResourcePublicationStore` using the same pool; the store's `get_run`
delegates and keeps the existing application port unchanged. Integration fixtures
now supply the repository explicitly, including fault-injection compositions.
The mapping parity tests exercise the dedicated repository directly; other tests
continue exercising the store delegation. No additional queries were migrated.

Ruff lint/format and strict mypy (168 source files) passed. Unit/architecture
checks: 231 passed. The five PostgreSQL integration modules listed above:
111 passed. The disposable loopback PostgreSQL cluster was stopped afterward.
No commits.

## Latest-run read extension — 2026-10-12

User direction and ADR-0077 extend the repository/decorator approach to `latest`.
The publication store delegates the call. SQLAlchemy selects the run through a
join to the partial coordination record, preserving active-first, admission-time
and UUID descending ordering, and the missing-coordination empty result.
Shared read metadata moved to `orm_base.py`; migrations remain authoritative.

Added five PostgreSQL cases for no runs, older active-run priority, admission-time
priority, UUID tie-breaking, missing coordination and fresh pointer reads after
release. Existing mapping parity checks retain the original raw SQL baseline.
Ruff lint/format, strict mypy (170 source files), 231 unit/architecture tests and
116 PostgreSQL integration tests passed. The disposable cluster was stopped.
No commits, schema changes or live refresh.
