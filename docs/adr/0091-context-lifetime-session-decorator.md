# ADR-0091: Decorate repository transaction contexts with session lifetime

Status: Accepted by user direction

Date: 2026-10-12

## Context

`@with_session` opens and closes a session during one repository method call.
The admission transaction from ADR-0089 must keep its lock and session alive
while `RefreshService` makes decisions inside the returned context. Applying
`@with_session` to a method that returns a context manager would close the
session before the service enters that context.

## Decision

Add `@with_session_context` beside `@with_session` in `session_scope.py`. It
injects a session into a generator-based repository transaction operation and
keeps that session open from context entry through context exit. Apply it to
`PostgresqlRefreshRunRepository.admission_transaction`. Standalone repository
methods continue to use `@with_session`.

## Consequences

Admission keeps one locked transaction across service policy and the run/slot
write, while session boilerplate remains in one infrastructure decorator.
Exceptions from the service's `with` block propagate through the context and
roll back the session. No session type crosses the application port and no
database schema or outcome changes.
