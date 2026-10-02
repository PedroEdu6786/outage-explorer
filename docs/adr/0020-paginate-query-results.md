# ADR-0020: Paginate query results without adding SQL clauses

Status: **Accepted direction; execution mechanism and pagination budgets pending**

Date: 2026-10-01

Supersedes [ADR-0019](0019-default-dataset-query-order.md).

## Context

The user corrected the default-ordering decision: the desired experience is
pagination for submitted SQL queries. Automatically adding ORDER BY or LIMIT
is not the requested behavior. Broad analytical queries can produce rows
without dataset natural keys, so query pagination cannot depend on those keys.

## Decision

- Preserve the submitted query's semantics. Do not inject ORDER BY, LIMIT or
  OFFSET to implement pagination. Honor clauses the user explicitly supplies.
- Execute against one authorized snapshot and page through the result of that
  execution. Continuations must not independently rerun the query with growing
  offsets or switch to a newly published snapshot.
- Without ORDER BY, no chronological order is promised. Preserve the sequence
  produced for that execution across its pages; a new execution may differ.
- Apply pagination to all supported result shapes, including joins, aggregates,
  DISTINCT, CTEs and window queries. Preserve duplicate result rows: result
  positions are not source natural keys and must not be deduplicated.
- The initial request carries SQL and a requested page size. Return column
  metadata, rows, query execution and snapshot identifiers, and an opaque
  continuation cursor when more retained results are available. Exact HTTP
  routes and response fields below are proposals, not implemented contracts.
- Bind continuation state to the caller, query execution, snapshot and result
  position. Authenticate and reauthorize current access on every page. Expired
  or lost state requires an explicit restart, never silent re-execution.
- Distinguish a page boundary from truncation of the entire result. A server
  resource cap must be explicit; pagination does not grant unbounded work or
  storage. A supplied LIMIT 100 remains a maximum of 100 query-result rows
  across all pages, not 100 rows per page.

Illustrative request bodies:

```json
{"sql": "SELECT * FROM generator_daily", "page_size": 100}
```

```json
{"cursor": "opaque-continuation-token"}
```

## Mechanism and limits still to select

A bounded result spool is the proposed mechanism: retain one execution's
result on private backend storage and serve pages by recorded result position.
This is temporary continuation state, not a cache that reuses results across
independent queries. A live database cursor is an alternative but must account
for worker occupancy, expiration and cleanup under the single-query limit.
Neither mechanism is selected by this decision.

The accepted 10-second execution deadline and worker isolation remain.
Query page defaults, byte/row ceilings, total retained-result budget, cursor
lifetime, first-page timing, oversized-row handling and restart behavior need
concrete design. ADR-0013's existing 1,000-row / 1-MiB total result cap remains
the baseline until explicitly revised; it must not silently become a per-page
allowance. ADR-0015's 15-minute lifetime and 100/500-row settings apply to
dataset previews and are not automatically SQL pagination settings.

## Consequences and verification

No default-order rewriting is required. Query execution now needs bounded
continuation state and lifecycle management; retaining only the input snapshot
does not guarantee the same sequence if an unordered query is executed again.

Verify page concatenation against the same execution's complete retained
result, including duplicate rows, explicit ORDER BY/LIMIT/OFFSET, joins and
aggregates. Cover retries of a continuation token, cross-user access, revoked
permissions, refresh between pages, expiry, lost state, disk exhaustion and
cleanup. Enforce worker deadlines independently of how slowly clients request
pages, and release pinned resources only when execution no longer needs them.

This records the corrected design; no backend executor exists yet.
