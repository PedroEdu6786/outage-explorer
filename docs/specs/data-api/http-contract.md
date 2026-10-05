# Data API contract
> Status: proposed · Date: 2026-10-04 · No product endpoint implementation claimed

This is the contract draft requested alongside the
[requirements discussion](requirements.md). It does not replace the existing
backend/connector specifications or accepted ADRs. Routes, JSON shapes, and
settings below remain proposed unless explicitly identified as user decisions
or existing accepted policies.

## Agreed behavior and proposed routes

User decisions: SQL comes from the frontend editor; SQL page selection belongs
on `/api/query` as a query parameter, without `/api/query/page`; refresh covers
all three datasets and runs in the background. Displaying tables is data
browsing, not account seeding. Initial table browsing has date-range filters
only; facility and generator identifier filters are excluded initially.
Refresh always uses the configured range, without caller-supplied dates
([ADR-0051](../../adr/0051-configured-http-refresh-range.md)).

| Method and path | Purpose | Access | Success |
| --- | --- | --- | --- |
| `GET /api/datasets` | Authorized catalog and schemas | Signed-in, filtered by role | `200` |
| `GET /api/datasets/{dataset}/preview` | Browse stored observations | Dataset authorized by role | `200` |
| `POST /api/query` | Execute submitted SQL once | Every referenced dataset authorized | `200` |
| `GET /api/query` | Read a retained numbered result page | Original user, access rechecked | `200` |
| `POST /api/refresh` | Admit one all-dataset background run | Admin | `202` for new admission |
| `GET /api/refresh/{run_id}` | Read run progress and outcome | Admin | `200` |

The POST/GET method split for `/api/query` is proposed; the shared path and page
query parameter are user-selected. SQL execution is proposed as a bounded
synchronous response; refresh admission is asynchronous.

## Shared transport and serialization

- Reuse the [browser authentication contract](../user-access/http-contract.md):
  opaque application session cookie, no browser provider tokens. Check current
  local roles before analytical access and again on every page.
- Proposed: require exact permitted `Origin` and session-bound `X-CSRF-Token`
  on both POST routes. Add `Idempotency-Key` to allowed CORS request headers
  for refresh. These extensions still need integration with auth transport.
- Responses use JSON and `Cache-Control: no-store`. Errors expose no storage
  paths, provider diagnostics, SQL fragments, or protected dataset metadata.
- Dates use `YYYY-MM-DD`; timestamps use RFC 3339 UTC; IDs are opaque strings.
  Facility/generator identifiers remain strings, including leading zeros.
- Represent tabular rows as arrays aligned with an ordered `columns` array.
  This preserves duplicate SQL column labels. Each column has `index`, `name`,
  logical `type`, `nullable`, and nullable `unit`.
- Encode decimal and 64-bit integer values as strings to preserve precision in
  browsers. Booleans are JSON booleans, nulls are JSON null, and floating-point
  values require an explicit non-finite-value policy before support. Complex
  SQL output types need a documented bounded encoding before implementation;
  their encoding is open, not a blanket exclusion of analytical SQL features.
- Reject duplicate query parameters, unknown request fields, malformed dates,
  invalid positive integers, and unsupported filter combinations with `400`.

## Catalog

`GET /api/datasets` returns `generation_id` and `datasets`.
Each dataset entry contains `id`, `sql_name`, `label`, `schema_version`,
`columns`, `supported_filters`, and `coverage` (`start_date`, `end_date`).
Coverage describes usable stored observations, not proof of upstream completeness.

Proposed public IDs and SQL relation names: `national`, `facilities`,
`generators`. Freeze the exact public column projection against the verified
modeled schemas during design; do not expose provenance object keys or raw files.
Existing modeled field references are `period`, `capacity_mw`, `outage_mw`,
`reported_percentage`, `facility`, `facility_name`, and `generator` where
applicable; see the [connector schemas](../data-connector/plan.md).

Viewer receives only national datasets. Analyst/Admin receive all three.
The accepted prepared fleet metric must be available through catalog/preview/
SQL; its relation name and whether to incorporate its fields in `national`
or expose another national-derived relation remain open. It does not require
a separate metric endpoint.

An unpublished S3 candidate is unavailable through this catalog. No active
generation yields `503 data_unavailable`, distinguishable from an empty
filtered result. The API serves only verified, published modeled data.

## Dataset preview

`GET /api/datasets/{dataset}/preview` first-page query parameters:

| Parameter | Meaning | Proposed behavior |
| --- | --- | --- |
| `start_date`, `end_date` | Inclusive date bounds | Optional; an omitted side is unbounded within stored coverage |
| `page_size` | Rows per page | Accepted default 100, initial configurable maximum 500 |

The initial filter set is date range only, as selected by the user. Reject
facility/generator filter parameters rather than ignoring them. Proposed continuation:
`GET /api/datasets/{dataset}/preview?cursor=<opaque-value>`, without repeating
filters or page size. Cursor binds user, dataset, generation, normalized filters,
fixed page size, and next position. Proposed deterministic ordering is ascending
`period`, then applicable string identifiers with a documented stable comparison.

Response fields: `dataset`, `generation_id`, `columns`, `rows`, `page_size`,
`has_more`, nullable `next_cursor`, and `expires_at`.
No matching records returns `200`, empty `rows`, and no next cursor.

Accepted cursor lifetime is 15 minutes from first-page creation, without renewal.
Refresh never changes an existing browsing sequence. Expired/lost continuation
returns `410 preview_unavailable`; user explicitly starts browsing again.
An unknown or forbidden dataset returns proposed generic `404 dataset_unavailable`
without schema details, avoiding disclosure through direct ID guesses.

## Submit SQL and read pages on the same path

Initial request:

```http
POST /api/query?page=1&page_size=100
Content-Type: application/json
```

```json
{"sql": "SELECT period, capacity_mw FROM national ORDER BY period"}
```

Only `sql` belongs in the body. `page` and `page_size` belong in query parameters.
Default page is 1. The user selected a default SQL page size of 100 and an
initial maximum of 500, independent of preview's separately accepted settings.
Accept a requested initial page greater than 1 against the
same execution's retained result; no injected pagination clauses.

Continuation:

```http
GET /api/query?query_id=<opaque-id>&page=2
```

`query_id` and `page` are required for GET. An optional `page_size` must match
the execution's stored size. GET accepts neither SQL nor a replacement body.
It never starts a worker or silently reruns the query.

Proposed common result envelope:

```json
{
  "query_id": "opaque-id",
  "generation_id": "opaque-generation",
  "columns": [
    {"index": 0, "name": "period", "type": "date", "nullable": false, "unit": null}
  ],
  "rows": [["2026-09-01"]],
  "page": 1,
  "page_size": 100,
  "has_more": false,
  "retained_row_count": 1,
  "total_pages": 1,
  "truncated": false,
  "truncation_reason": null,
  "limits": {"max_rows": 1000, "max_bytes": 1048576},
  "expires_at": "2026-10-04T23:15:00Z"
}
```

Example values are illustrative. `retained_row_count` counts retained rows,
not the full unbounded query result. `total_pages` covers only retained rows,
with one empty page for an empty result. `has_more` concerns another retained
page; it does not indicate whether SQL was truncated. Truncation reasons are
proposed `row_limit` or `byte_limit`; returned rows contain complete values.
The byte-cap accounting representation must be frozen during design.

Accepted total caps remain 1,000 rows or 1 MiB and the execution deadline is
10 seconds, with one isolated analytical worker at a time. Preparation/overall
deadlines and result-storage budgets remain open. The user selected a result
lifetime of 15 minutes from completion, fixed and unrenewed.

Empty result page 1 returns `200`; a positive page beyond the retained range
returns proposed `400 page_out_of_range`, never an automatic rerun. A foreign or
unknown query ID returns generic `404 query_unavailable`. Known expiry returns
`410 query_unavailable`; after metadata loss, the backend cannot necessarily
distinguish an expired ID from an unknown one. Both require explicit resubmission.
Revoked session/access denies continuation. Repeat visits preserve page contents.
Repeated POST requests are separate executions; no automatic SQL retry is promised.

## Background refresh

New admission:

```http
POST /api/refresh
Content-Type: application/json
Idempotency-Key: <client-generated-key>
```

```json
{}
```

Accept an empty JSON object. Resolve configured inclusive start/end dates at
admission and persist the resolved interval with the run. Reject caller date
fields and dataset selectors. Invalid/missing/reversed/excessive configured
intervals prevent admission with a safe configuration/service error before
source work. Maximum interval comes from validated configuration, not a
fabricated measured production limit.
Initial live publication follows the accepted April 2–October 1, 2026 interval
and requires usable output in all three grains; other first-run dates require
an explicit policy decision.

Proposed new-admission response: `202`, `Location: /api/refresh/{run_id}`,
`Retry-After: 3`, and JSON `run_id`, `status: accepted`,
`effective_interval: {start_date, end_date}`, and `status_url`.
Admission means the run has been durably recorded for supervised processing;
it does not mean retrieval or publication has succeeded. Failure to admit
durably returns an error rather than a success receipt.

Scope idempotency to local user and operation. Repeating the same key and empty
request returns the same run and its original resolved interval, even if backend
configuration has changed: proposed `202` if active, `200` if terminal. A fresh
key resolves the current configuration. Never silently change a recorded run's
interval. Conflicting key reuse yields `409 idempotency_conflict`; caller date
overrides remain invalid input rather than a way to reconfigure a run.
Another run while refresh is occupied yields `409 refresh_busy`.
Idempotency retention/expiry and interruption recovery need design.

Background execution belongs outside the HTTP request and app factory. Closing
the browser does not cancel it. Supervision, ownership, and restart handling
must be established across processes; a thread tied to a request is insufficient.
No separate approval or publish endpoint is included.

`GET /api/refresh/{run_id}` returns proposed fields:

- `run_id`, `status`: `accepted`, `running`, `succeeded`, `failed`, `interrupted`.
- `stage`: `queued`, `retrieving`, `modeling`, `persisting`, `verifying`,
  `publishing`, `finished`; use stage/per-dataset progress rather than an invented
  completion percentage or promised completion time.
- `effective_interval`, `accepted_at`, nullable `started_at`, `finished_at`.
- `datasets`: entries for all three public IDs, each with `status`, observed
  `coverage`, and nullable `quality` until accurate counts are available.
- `quality`: `received_rows`, `selected_rows`, `excluded_rows`,
  `duplicates_collapsed`, `superseded_rows`, `retained_invalid_rows`,
  `retained_absent_rows`, `carried_outside_interval_rows`, `modeled_rows`,
  `retained_entire_dataset`, and `exclusion_reasons` (`code`, `count`).
- `publication`: `published`, nullable `generation_id`, `previous_generation_id`,
  and nullable `no_publication_reason`.
- Nullable `failure`: safe `code` and `message`, without raw upstream errors.

Unavailable counts are null, never guessed zeros. Final quality mapping must
reconcile with the connector's existing dispositions/ledger; overlapping reason
counts must not inflate the excluded-row count. Coverage does not certify that
all upstream observations exist.

Success may publish with row exclusions and retained data. All-three-excluded
input with previous data is proposed as `succeeded`, `published: false`,
`no_publication_reason: all_incoming_rows_excluded`. Some wholly excluded
datasets retain previous valid data while other valid changes can publish.
Empty routes, missing/failed pages, resource exhaustion or integrity failures
fail the run. Never publish only a subset of datasets. Unknown Admin run ID
returns `404 refresh_unavailable`; non-Admin access is denied before lookup.

## Proposed error contract

Use the existing HTTP error envelope shape:

```json
{"error": {"code": "invalid_request", "message": "Invalid request"}}
```

| HTTP status | Proposed codes | Meaning |
| --- | --- | --- |
| `400` | `invalid_request`, `invalid_sql`, `unsupported_sql`, `page_out_of_range`, `page_size_mismatch` | Input/SQL rejected; correct before retry |
| `401` | `unauthenticated` | Sign in again |
| `403` | `forbidden`, `csrf_failed` | Current access/origin/CSRF rejected |
| `404` | `dataset_unavailable`, `query_unavailable`, `refresh_unavailable` | Resource unavailable; no protected details |
| `409` | `refresh_busy`, `idempotency_conflict` | Refresh admission conflict |
| `410` | `preview_unavailable`, `query_unavailable` | Known continuation expired/lost; restart explicitly |
| `422` | `query_resource_limit` | Query exceeds execution resources |
| `503` | `query_busy`, `data_unavailable`, `service_unavailable` | Busy worker or unavailable data/dependency |
| `504` | `query_timeout` | Execution deadline exceeded |

Busy responses include a bounded `Retry-After`; its value is a retry suggestion,
not a completion guarantee. Refresh execution failures are exposed in its status
resource, not as a retroactive failure of an already accepted POST response.

## Open contract decisions and verification gates

Review found that the draft is not yet a complete integration contract:

- **Initial browsing view:** optional dates and ascending order above are
  proposals. Confirm the desired default interval/order; date-only filter scope
  and cursor pagination are already accepted. Specify previous-page navigation
  without silently restarting on a newer generation.
- **Refresh rediscovery:** only lookup by known run ID exists. Define whether
  Admin can retrieve the current/latest run without retaining its ID; a latest
  lookup or bounded run list would be an additional proposed route.
- **Refresh status consistency:** the connector plan's `retained` state means
  all input excluded and no publication, while this draft uses `succeeded` plus
  `published: false`. Resolve this before freezing status enums; prefer the
  connector's distinct outcome to avoid a misleading success label.
- **Uncertain publication:** a boolean `published` is insufficient when a commit
  cannot be confirmed. The connector plan already calls for `publication_unknown`
  and reconciliation. Define an explicit pending/unknown representation; do not
  label uncertain publication as failed or claim that a commit was rolled back.
- **Restart behavior:** distinguish durable accepted-but-unclaimed work from
  interrupted running work. The connector proposes claiming queued work after
  restart, reconciling running work, then requiring an explicit retry for an
  unpublished interrupted run. Browser disconnection alone never cancels it.
- **Lifetime versus capacity:** the SQL result's accepted 15-minute expiry is
  subject to already accepted process/store loss. Bound per-user/global result
  admission and cleanup; do not silently evict valid results under pressure while
  presenting an unconditional lifetime guarantee. Budgets require measurements.

The points below are remaining design choices, not additional accepted scope:

- Refresh configuration field names/change mechanism; no per-request date input.
- Final public dataset/SQL names and complete column projection/metric exposure.
- Complex/non-finite value encoding, byte-cap representation, and
  retained-result budgets.
- Proposed error statuses, empty/out-of-range behavior, and idempotency policy.
- Polling suggestion, stages, and quality-field mapping to existing connector DTOs.
- Auth transport extensions, isolated query runtime, background supervision,
  complete-generation activation, and measured resources remain implementation
  gates. This document is not evidence that they work.
