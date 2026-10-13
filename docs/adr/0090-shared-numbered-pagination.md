# ADR-0090: Share numbered pagination over retained results

Status: **Accepted by explicit user direction** (October 12, 2026)

## Context

ADR-0071 introduced reusable cursor pagination for preview but left SQL result
pagination in query-specific code because SQL pages address one retained result
by number. The user requested the same opportunity for reuse in other services
without changing SQL's page-number contract.

## Decision

Add a pure page-window policy in `domain/pagination.py`, a transport-independent
`NumberedPage` in `application/dto.py`, and `NumberedPaginator` in
`application/pagination/numbered.py`. The policy validates positive page numbers
and bounded sizes and calculates a window over a fixed row count. The paginator
assembles common `rows`, `page`, `page_size`, `total_pages`, and `has_more` fields
around caller-supplied metadata. Empty results have one addressable empty page,
as before.

The query controller's validated request DTO checks HTTP pagination inputs before
SQL execution. `QueryService` consumes those validated values without repeating
the bounds check. A future non-HTTP execution entrypoint must validate its own
inputs before calling the use case. `QueryResultPager` still checks bounds on
direct retained-page reads and owns reader lifetime, fixed-size enforcement and
response assembly. Bootstrap injects the same pager into query execution and
the GET route; `QueryService` has no page method.

SQL's referenced grains are known only after bounded inspection. The application
service authorizes that inspected scope before execution and passes its approved
access and result identity to the pager for the initial response. The pager
checks that the retained result matches this approval without repeating the
authorization lookup. Each later GET is a new request and must resolve current
identity and authorize the retained grains afresh; possession of a query ID is
never sufficient. A controller guard cannot authorize raw SQL's unknown scope.

The retained-result adapter uses the pure window policy to read its private
verified spool and returns a `NumberedPage` value through its application port.
Infrastructure does not import application pagination orchestration.
`ResultIdentity` retains query ownership, snapshot and lifetime metadata; its
existing page helpers delegate to the shared pure policy. Query-specific
`page_size_mismatch` and `page_out_of_range` errors stay at their current
boundaries.

This refines ADR-0071's separation: cursor and numbered pagination share a
package, not an algorithm or response shape. Authorization, result ownership,
expiry, spool verification and cleanup remain with their existing owners. No
SQL text is rewritten or re-executed, and no new Pydantic exception is added.

## Consequences

Future services with addressable, stable numbered results can reuse the
paginator by supplying rows, a total count and endpoint metadata. They must
still own their own read, authorization, retention and response byte limits.
Cursor endpoints continue to use `CursorPaginator`.
