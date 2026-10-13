# ADR-0072: Retrieve complete preview pages through a repository

Status: **Reverted by explicit user direction** (October 11, 2026)

The user rejected the implemented abstraction as added complexity and requested
restoring the prior service. The repository implementation and its ports were
removed; `PreviewService` again owns retrieval and lifecycle orchestration under
ADR-0070/0071. Earlier DTO validation and parser improvements remain. The text
below records the reverted experiment, not the current implementation.

## Context

The user requested a repository boundary for cursor decisions and rejected moving
them into a second application service. Preview retrieval spans publication metadata,
verified Parquet inputs, temporary sequence state and isolated execution rather
than a single database query.

The user accepted a complete-page repository contract. Response byte limits may
reduce the number of returned rows, so cursor finalization must occur after page
sizing to avoid skipping rows on continuation.

## Decision

`application/ports/preview_repository.py` declares `PreviewRepository.read_page`.
It accepts freshly approved `PreviewAccess` and validated selection values and
returns the complete encoded page with finalized current/next cursors and metadata.
`PreviewService.read` only forwards the approved access and DTO fields to this port.

`infrastructure/preview/repository.py` implements `PublishedPreviewRepository`.
It owns initial/continuation selection, snapshot preparation, cursor ownership,
execution reservation, worker reads, page assembly and resource cleanup through
the existing narrow ports. It never executes DuckDB in the API process.

The existing reusable `CursorPaginator` remains in application pagination.
`CursorPage` and the `CursorPagination` protocol live in application ports, allowing
the repository to use an injected paginator without importing application services
or widening import-boundary exceptions. Bootstrap constructs and injects the adapter.

Authorization and DTO validation still precede repository access. Non-HTTP callers
obtain fresh approved access and construct a validated DTO before using the service.
Cursor contents and ordering decisions do not escape into the controller/service.

## Preserved behavior

- Continuation validation precedes execution admission; initial admission precedes
  publication lookup or file preparation.
- Snapshot, filters, size, user/dataset binding and fixed 60-second expiry remain.
- Encoding and byte fitting finish before the next cursor is returned; that cursor
  advances from the last row actually returned.
- Failure discards newly created browsing state while preserving existing sequences
  for valid retries. Input pins and execution capacity remain owned until worker
  termination is confirmed, including recovery handoff.
- HTTP fields/errors, three-resource publication, cache verification, isolated
  execution and SQL retained-result pagination are unchanged.

This refines the preview ownership described in ADR-0071. It introduces a dedicated
analytical read repository, not a generic CRUD framework or a new storage stack.
