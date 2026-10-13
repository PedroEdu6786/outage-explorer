# ADR-0089: Let the refresh service decide admission under one transaction

Status: Accepted by user direction

Date: 2026-10-12

## Context

ADR-0088 moved admission rules into pure domain policy, but the run repository
still invoked them. The application service should decide whether a request is
an idempotent replay, whether another run occupies the slot, and whether an
initial-load configuration is eligible. Those decisions need values read under
one coordination lock before the queued run and slot reservation commit.

## Decision

`RefreshService.admit` invokes the pure admission rules inside a focused
`RefreshAdmissionTransaction` application port. The port exposes only the
locked active run and base IDs, replay lookup, stored-base validation, and
queued-run creation. `PostgresqlRefreshRunRepository.admission_transaction`
owns the short-lived ORM session and coordination lock; its transaction object
only queries, validates stored descriptors, inserts the run, and reserves the
slot. The publication store delegates the port without receiving a session.

The service retains its fast replay read before resolving configuration, then
rechecks replay under the lock to handle races. It translates the pure domain
busy result to the existing `RefreshBusyError` and checks initial-load
eligibility before requesting the insert.

This transaction context spans multiple service decisions. It therefore uses
one explicit session context in the repository rather than independently
decorated calls; `@with_session` remains the standard for standalone repository
operations.

## Consequences

The service owns admission policy and ordering. The repository owns database
queries, mapping, the lock, and atomic run/slot writes. No ORM session or driver
type crosses the application port. Existing replay, busy, base-validation and
database-commit behavior remains unchanged. This supersedes ADR-0087/0088 only
on who invokes the admission rules and how its transaction is exposed.
