# ADR-0071: Share cursor pagination and declarative request validation

Status: **Accepted by explicit user direction** (October 10, 2026)

## Context

The user requested Pydantic validation and pagination reusable by future
endpoints, rejecting a preview-specific pagination service.

## Decision

`application/pagination/` owns `CursorPaginationRequest`, `CursorPage` and
`CursorPaginator`. It has no preview, dataset, storage, HTTP or authorization
dependency. The generic page contract accepts typed rows/keys, endpoint metadata
and a cursor callback. Pagination enforces row/key alignment, fixed page size,
progress and complete-row response byte limits. If a prefix is needed, its next
cursor uses the last returned key; rows are never skipped.

Preview supplies snapshot-bound bounded worker output, encoded rows and metadata.
It retains its generation selection, ownership, expiry and worker/pin lifecycle.
Bootstrap injects the reusable paginator and byte-measurement function.
SQL retained-result pagination remains unchanged: executing once and paging its
retained output is a different contract, not a cursor scan.

A strict frozen Pydantic `CursorPaginationRequest` declares shared size/cursor
constraints. `PreviewRequest` adds date/facility constraints. HTTP only translates
canonical transport strings and rejects malformed/duplicate/unknown parameters.
Direct callers construct the same validated DTO. No normalization of facility
identifiers is introduced.

Permit only these additional pure validation imports, enforced by architecture tests:

- `application/pagination/request.py`: `BaseModel`, `ConfigDict`, `Field`,
  `ValidationError`, `model_validator`.
- `application/preview_request.py`: `Field`, `field_validator`, `model_validator`.

This is a narrow extension to ADR-0030's inner-layer library restriction; it
permits no framework/I/O dependencies elsewhere.

## Consequences

New cursor endpoints reuse field validation and bounded page assembly by
supplying their own read, metadata and cursor codec. Pagination does not infer
ordering or alter queries. The existing preview HTTP response schema, bounds,
60-second nonrenewing expiry and cursor binding remain unchanged.
