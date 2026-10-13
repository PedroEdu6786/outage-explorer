# ADR-0079: Move refresh ownership and base queries into repositories

Status: Accepted by user direction

Date: 2026-10-12

## Context

ADR-0078 makes repositories the home for operational model queries. Refresh
claim, heartbeat, and active-base validation still embedded their queries in
the publication coordinator. Claim changes both the coordination row and the
run; admission and publication validate the base within larger transactions.
Splitting any of those operations into independently decorated calls would
change their atomicity.

## Decision

- `PostgresqlRefreshCoordinationRepository` owns claim and heartbeat. Each is a
  single `@with_session` operation using SQLAlchemy expressions and the same
  bounded pool as the other refresh repositories. Claim locks the coordination
  row and changes it and the run in one transaction. Heartbeat locks that row,
  checks the owner and database-time lease, then extends it in one transaction.
- `PostgresqlPublishedGenerationRepository` owns active-base validation and
  related generation reads. Its validation helper receives the caller's current
  psycopg connection because admission and publication still use that
  transaction. This is a temporary raw-SQL bridge inside a repository, not a
  separately decorated operation. Moving the whole admission/publication
  transaction to ORM is outside this scope.
- The publication store delegates these operations to the repositories.
  Application ports, domain values, database schema, refresh outcomes, lease
  bounds, and publication recovery behavior stay the same.

## Consequences

The ownership writes now exercise the ORM transaction path. Integration tests
must verify claim/heartbeat fencing and that a failed claim does not leave a
partial coordination update. Base validation stays on the locked transaction's
connection; do not open another session for it. Other raw publication and
recovery operations remain to migrate in separate, explicitly scoped work.

This extends ADR-0074/0077's pilot scope without rewriting those historical
decisions. Partial ORM mappings remain unsuitable for schema generation.
