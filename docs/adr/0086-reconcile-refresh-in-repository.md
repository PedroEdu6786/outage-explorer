# ADR-0086: Reconcile refresh recovery in one repository transaction

Status: Accepted by user direction

Date: 2026-10-12

## Context

Recovery and uncertain publication-commit reconciliation still mixed raw SQL
with coordination in `PostgresqlResourcePublicationStore._reconcile`. The
coordination lock, publication lookup, run update and slot release must share
one transaction. A fresh checkout after an uncertain commit must serialize
with the original publication transaction before deciding its outcome.

## Decision

`PostgresqlPublishedGenerationRepository.reconcile` uses `@with_session` for
that complete transaction. It locks coordination, looks up the run and any
publication, then confirms a published run or interrupts an eligible
unpublished run. The pure domain rule
`publication_policy.should_interrupt_unpublished_run` decides interruption from
run status, active ownership, lease health and force mode. The repository
updates the run and releases the slot in the same session, returning a domain
`RefreshRun` after the writes are flushed.

The publication store delegates recovery and uncertain-commit handling to this
operation. Publication history is checked before lease expiration; a healthy
lease blocks ordinary interruption, while forced reconciliation may interrupt
an unpublished active run. Admission's psycopg transaction remains separate.

## Consequences

The recovery-only psycopg slot-release bridge is removed. The existing
publication-first behavior, fencing epoch and fail-closed unavailable outcome
remain unchanged. No schema or publication-pointer reset is involved.
