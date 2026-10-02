# ADR-0021: Select query results by page number and page size

Status: **Accepted direction; storage mechanism and budgets pending**

Date: 2026-10-01

Refines [ADR-0020](0020-paginate-query-results.md), replacing its proposed
cursor-only request shape with numbered pages. Its execution, authorization,
SQL semantics and total-result limits still apply.

## Context

After reviewing SQL-client behavior, the user confirmed that query pagination
needs both a page limit and a page selector. A page size alone cannot express
which portion of a result the caller wants.

## Decision

- Accept `page` (a positive integer, starting at 1) and `page_size` (a positive
  integer defining the row limit per page). Keep `page_size` as the API name
  for the page limit so it is distinct from a SQL `LIMIT`.
- Address pages within one retained query execution. Return an opaque
  `query_id` on execution; later page requests identify that execution and the
  requested page, without resubmitting SQL or silently re-executing it.
- Bind the execution to its principal, authorized snapshot and effective
  `page_size`. Later requests use that same size; reject a mismatched size.
  Recheck authorization on every page, including previously visited pages.
- Page `p` starts at zero-based result position `(p - 1) * page_size`. This
  indexes the retained result; it does not inject SQL `OFFSET` or `LIMIT`.
  Support revisiting and selecting numbered pages in the available retained
  result. Reject invalid page/size values and explicitly report expired or
  lost executions.
- Return the effective `page`, `page_size`, `query_id`, rows and an indication
  of whether another retained page exists, alongside the column, snapshot and
  total-result truncation metadata required by ADR-0020.
- A supplied SQL `LIMIT` continues to cap the whole query result. With 250
  result rows and `page_size: 100`, pages contain 100, 100 and 50 rows. With
  `LIMIT 100` and `page_size: 25`, there are at most four nonempty pages.
- Dataset preview pagination remains governed by ADR-0015.

Illustrative request bodies (route names remain proposed):

```json
{"sql": "SELECT * FROM generator_daily LIMIT 250", "page": 1, "page_size": 100}
```

```json
{"query_id": "opaque-execution-id", "page": 2, "page_size": 100}
```

## Options and consequences

- Cursor-only navigation naturally expresses the next segment, but does not
  expose the requested numbered-page selector.
- Numbered pages over retained results support explicit page selection and
  repeat visits while preserving one execution's order and duplicate rows.
  They require retained, addressable results; a forward-only live cursor alone
  is insufficient for revisiting pages.
- Rerunning SQL with different offsets would avoid retained result storage,
  but violates ADR-0020's same-execution guarantee and is rejected.

A bounded result spool remains proposed. Format, quotas, expiry, page-size
defaults/maximum, first-page timing, unavailable/out-of-range page responses,
and byte ceilings/oversized-row handling remain to be finalized. Byte ceilings
must not silently shift numbered page boundaries or skip rows. The existing
1,000-row / 1-MiB total-result cap remains the baseline, not a per-page budget.

## Verification

Check first/middle/final pages, empty results, invalid and out-of-range pages,
page-size mismatches, direct page selection and repeat visits. Concatenated
pages must match the same retained execution, including duplicates, unordered
queries, joins, aggregates and explicit SQL LIMIT/OFFSET. Verify refresh,
revoked access, another caller's query ID, expiry/lost state and explicit
total-result truncation. Page selection must not rerun SQL.

This records the API design direction; no query executor is implemented yet.
