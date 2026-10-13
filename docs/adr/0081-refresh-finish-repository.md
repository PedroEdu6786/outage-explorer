# ADR-0081: Put unpublished refresh completion in the coordination repository

Status: Accepted by user direction

Date: 2026-10-12

## Context

After ADR-0080, `finish` still combined raw ownership, run, and coordination
queries in the publication coordinator. Finishing a failed or retained run must
update its outcome and release the active slot atomically. A retained outcome
also requires an existing base generation.

## Decision

`PostgresqlRefreshCoordinationRepository.finish` owns that whole database
operation in one `@with_session` transaction. It locks and verifies the fenced
owner, reads the run, enforces the retained-baseline rule, writes the final run
fields using database time, and releases the coordination slot by clearing the
run, owner and lease and incrementing the epoch. It returns a plain `RefreshRun`.

The publication store validates the requested status and bounded report before
delegating. An absent report preserves stored quality. Successful publication
remains in its existing transaction until migrated as a whole.

## Consequences

The `RefreshStore.finish` interface, failure/retention outcomes, stale-owner
fencing, and publication pointer behavior stay the same. The run update and slot
release cannot commit separately. No schema or publication-history change.
