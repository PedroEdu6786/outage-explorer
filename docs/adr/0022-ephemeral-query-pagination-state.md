# ADR-0022: Keep query pagination state in memory

Status: **Accepted direction; store implementation and budgets pending**

Date: 2026-10-01

Refines [ADR-0020](0020-paginate-query-results.md) and
[ADR-0021](0021-number-query-result-pages.md). Their single-execution semantics,
numbered pages, authorization checks and total-result limits still apply.

## Context

The user questioned keeping short-lived query records in the application
database because users can abandon results after the first page. Moving that
metadata to another durable database would not solve stale-state accumulation.
After discussing an in-memory store and the consequences of its loss, the user
accepted ephemeral pagination state and requested that the decision be recorded.

## Decision

- Keep the `query_id` mapping and pagination metadata in a bounded, expiring
  in-memory store, separate from durable application records. Do not require
  a SQLite insert for each query execution or durable query history.
- Associate each live ID with its caller, authorized snapshot, fixed page
  size, result location and expiration. Continue to authorize every page;
  possession of a query ID does not grant access.
- Accept loss of pagination state when an entry expires or the store loses
  its contents, including restart of the owning process for an in-process
  implementation. Pagination does not need to survive that loss.
- A page request using a lost or expired ID returns an explicit
  results-unavailable/expired error requiring a new query execution. It must
  not silently rerun SQL, substitute another execution or return page 1 in
  response to a later-page request. Exact HTTP status/error code remains open.
- An explicit rerun starts a new execution and ID. Its results can differ if
  data changed, and its ordering can differ without explicit ORDER BY. Rows
  already delivered remain available to the client; source datasets and
  durable application records are unaffected by loss of pagination state.
- Use a fixed expiration and enforce memory, retained-result storage and
  per-user/global execution budgets. Reclaim abandoned state without relying
  on the caller requesting another page. Numeric budgets remain open.
- Result payload placement is separate from metadata storage. A bounded
  temporary file spool remains proposed; choosing an in-memory metadata
  store does not require retaining all result rows in RAM.
- If result files are used, expiration and cleanup must reclaim them as well
  as their metadata. Recover from store loss by cleaning orphaned temporary
  results, without touching active results or durable source data. Losing an
  in-memory entry alone does not delete a file.

## Alternatives and consequences

- Durable SQLite query metadata could outlive the backend process, but would
  still require expiration and result-file lifecycle management. That
  durability is unnecessary for the accepted pagination behavior.
- An in-process mapping or a dedicated in-memory database can implement the
  selected lifecycle. No specific product, separate service or persistence
  mode is selected by this decision.
- A live DuckDB cursor alone does not provide the required numbered-page
  revisits. Retain one execution's addressable result under ADR-0021.

This fits the current single-backend scope. Multiple replicas would require
an explicit shared-state/result-access or ownership-routing design; an
in-memory store by itself does not solve that future deployment problem.

Exact TTL, page-size defaults/maximum, quotas, cleanup scheduling and concurrency,
store implementation, result format and first-page timing remain open. Query
execution deadlines and the existing 1,000-row / 1-MiB total-result baseline
remain unchanged. This decision does not change preview pagination in ADR-0015
or deferred retention policy for published datasets in ADR-0010.

## Verification

- Fetch page 1, remove the mapping or restart its store, then request page 2:
  receive an explicit unavailable response, with no SQL rerun or page-1 rows.
- Explicitly rerun and verify a new ID, independent of the invalid old ID.
- Expire an abandoned execution and verify reclamation of metadata and any
  result files even when no subsequent page request arrives.
- Exercise orphan-file cleanup after state loss and concurrent active reads;
  preserve durable datasets and application records.
- Enforce memory/storage and per-user/global quotas under many abandoned
  executions while maintaining API availability and authorization checks.

Documentation only; no store or query executor is implemented by this record.
