# ADR-0080: Put refresh progress persistence in the coordination repository

Status: Accepted by user direction

Date: 2026-10-12

## Context

After claim and heartbeat moved under ADR-0079, `progress` still locked the
coordination row and updated `refresh_runs` with raw SQL in the publication
coordinator. That mixed persistence queries with orchestration and left a
separate ownership implementation to maintain.

## Decision

`PostgresqlRefreshCoordinationRepository.progress` owns the operation. It uses
one `@with_session` transaction to lock the coordination row, verify the run,
owner identity, epoch and database-time lease, then update the run stage and
optional quality JSON. It shares the same ownership check as heartbeat.

The publication store retains progress-stage and report validation before it
delegates. A missing report leaves the stored quality unchanged. Other refresh
write operations remain in their current transactions pending separate scope.

## Consequences

The caller sees the same `RefreshStore.progress` interface and error behavior.
No schema or publication history changes follow from this decision. Repository
queries stay outside process orchestration while ownership and progress remain
atomic.
