# Data API contract
> Status: v1 client contract implemented · Date: 2026-10-05 · HTTP endpoints implemented with explicit enablement

Phase 1 freezes the client vocabulary in [openapi.json](openapi.json), with
validated synthetic [fixtures.json](fixtures.json) and the
[client handoff](client-handoff.md). The OpenAPI version is 1.0.0; public schema
and tabular encoding versions are `1`. These files support fixture-backed web
client development. Phase 6 implements the seven transport operations with controlled HTTP/process
acceptance. Live resources and the user-owned Linux runtime validation remain
separate. Set `OUTAGE_DATA_HTTP_ENABLED=true` alongside configured authentication
and refresh dates to install them; this alone does not enable analytical execution.

The selected plan resolves the earlier draft recommendations below. Runtime
isolation, process ownership and measured resource/retention quotas remain open
in [runtime-evidence.md](runtime-evidence.md). The formal
[specification](spec.md) continues to govern behavior.

## Planned facility-filter extension

The user subsequently requested single-facility preview filtering for facility
and generator datasets. The [feature spec](../preview-facility-filter/spec.md)
and [implementation plan](../preview-facility-filter/plan.md) describe that planned
extension. It is not implemented yet; the current date-only contract below
remains accurate until the coordinated backend/worker/web change ships.

## Agreed behavior and selected routes

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
| `GET /api/refresh/latest` | Rediscover active/latest run without its ID | Admin | `200` |
| `GET /api/refresh/{run_id}` | Read run progress and outcome | Admin | `200` |

The POST/GET method split for `/api/query` is selected; the shared path and page
query parameter are user-selected. SQL execution is selected as a bounded
synchronous response; refresh admission is asynchronous.

## Shared transport and serialization

- Reuse the [browser authentication contract](../user-access/http-contract.md):
  opaque application session cookie, no browser provider tokens. Check current
  local roles before analytical access and again on every page.
- Selected: require exact permitted `Origin` and session-bound `X-CSRF-Token`
  on both POST routes. Add `Idempotency-Key` to allowed CORS request headers
  for refresh. These extensions are implemented in the shared auth transport.
- Responses use JSON and `Cache-Control: no-store`. Errors expose no storage
  paths, provider diagnostics, SQL fragments, or protected dataset metadata.
- Dates use `YYYY-MM-DD`; timestamps use RFC 3339 UTC; IDs are opaque strings.
  Facility/generator identifiers remain strings, including leading zeros.
- Represent tabular rows as arrays aligned with an ordered `columns` array.
  This preserves duplicate SQL column labels. Each column has `index`, `name`,
  logical `type`, `encoding`, `nullable`, and nullable `unit`; decimal descriptors additionally carry `precision`/`scale`, and nested descriptors carry ordered `children` (`name` plus recursive type/encoding). Query-expression
  nullability may be unknown. Decimal and SQL integer cells are encoded as
  strings to preserve precision. Bounded pagination counters remain JSON numbers.
  Booleans and nulls use native JSON values. The concrete proposal for floating,
  temporal, binary and nested values is in [design-notes.md](design-notes.md);
  representative adapter verification is required before claiming support.
- Reject duplicate query parameters, unknown request fields, malformed dates,
  invalid positive integers, and unsupported filter combinations with `400`.
  SQL text must encode as valid UTF-8 and fit within 65,536 bytes; unpaired
  surrogate escapes in JSON return `400 invalid_request` before SQL inspection.

## Catalog

`GET /api/datasets` returns `generation_id` and `datasets`.
Each dataset entry contains `id`, `sql_name`, `label`, `schema_version`,
`columns`, `supported_filters`, and `coverage` (`start_date`, `end_date`).
Coverage describes usable stored observations, not proof of upstream completeness.

Public IDs and SQL relation names: `national`, `facilities`,
`generators`. The public projection is frozen and tested against verified
modeled v1 schemas; do not expose provenance object keys or raw files.
Existing modeled field references are `period`, `capacity_mw`, `outage_mw`,
`reported_percentage`, `facility`, `facility_name`, and `generator` where
applicable; see the [connector schemas](../data-connector/plan.md).

Viewer receives only national data. Analyst/Admin receive all three datasets.
The user selected the prepared fleet metric as columns of `national`, alongside
the source-reported percentage, available through preview and SQL. No additional
metric dataset/endpoint is needed. Exact public column names and precision are encoded in [openapi.json](openapi.json)
and its validated catalog fixtures.

An unpublished S3 candidate is unavailable through this catalog. No active
generation yields `503 data_unavailable`, distinguishable from an empty
filtered result. The API serves only verified, published modeled data.

## Dataset preview

See the [preview flow diagrams](preview-flow.md) for the endpoint, S3 cache and
isolated DuckDB processing sequence.

`GET /api/datasets/{dataset}/preview` first-page query parameters:

| Parameter | Meaning | Selected behavior |
| --- | --- | --- |
| `start_date`, `end_date` | Inclusive date bounds | Optional; an omitted side is unbounded within stored coverage |
| `page_size` | Rows per page | Accepted default 100, initial configurable maximum 500 |

The initial filter set is date range only, as selected by the user. Reject
facility/generator filter parameters rather than ignoring them. Selected continuation:
`GET /api/datasets/{dataset}/preview?cursor=<opaque-value>`, without repeating
filters or page size. Cursor binds user, dataset, generation, normalized filters,
fixed page size, and next position. User-selected initial browsing covers all
available dates when dates are omitted, newest observations first. Use descending
`period`, then applicable identifiers with a stable tie-break order; exact
identifier comparison is binary UTF-8. This does not add ordering to user SQL.

Response fields: `dataset`, `generation_id`, `columns`, `rows`, `page_size`, `page_cursor`,
`has_more`, nullable `next_cursor`, and `expires_at`.
No matching records returns `200`, empty `rows`, and no next cursor.
`page_cursor` identifies the current page, including page 1; previous navigation
resubmits a visited cursor. Identifier ties use ascending binary UTF-8 order.

Accepted cursor lifetime is 60 seconds from first-page creation, without renewal.
Refresh never changes an existing browsing sequence. Expired/lost continuation
returns `410 preview_unavailable`; user explicitly starts browsing again.
An unknown or forbidden dataset returns selected generic `404 dataset_unavailable`
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

Common result envelope:

```json
{
  "query_id": "opaque-id",
  "generation_id": "opaque-generation",
  "columns": [
    {"index": 0, "name": "period", "type": "date", "encoding": "iso-date", "nullable": false, "unit": null}
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
not the full unbounded query result. `generation_id` is null for a
reference-free analytical expression, which reads no published relation. `total_pages` covers only retained rows,
with one empty page for an empty result. `has_more` concerns another retained
page; it does not indicate whether SQL was truncated. Truncation reasons are
selected `row_limit` or `byte_limit`; returned rows contain complete values.
The byte-cap accounting representation is frozen below.

Accepted total caps remain 1,000 rows or 1 MiB and the execution deadline is
10 seconds, with one isolated analytical worker at a time. Preparation/overall
deadlines and result-storage budgets remain open. The user selected a result
lifetime of 60 seconds from completion, fixed and unrenewed.

Empty result page 1 returns `200`; a positive page beyond the retained range
returns selected `400 page_out_of_range`, never an automatic rerun. A foreign or
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

Selected new-admission response: `202`, `Location: /api/refresh/{run_id}`,
`Retry-After: 3`, and JSON `run_id`, `status: accepted`,
`effective_interval: {start_date, end_date}`, and `status_url`.
Admission means the run has been durably recorded for supervised processing;
it does not mean retrieval or publication has succeeded. Failure to admit
durably returns an error rather than a success receipt.

Scope idempotency to local user and operation. Repeating the same key and empty
request returns the same run and its original resolved interval, even if backend
configuration has changed: selected `202` if active, `200` if terminal. A fresh
key resolves the current configuration. Never silently change a recorded run's
interval. Conflicting key reuse yields `409 idempotency_conflict`; caller date
overrides remain invalid input rather than a way to reconfigure a run.
Another run while refresh is occupied yields `409 refresh_busy`.
Keys are 16–128 ASCII letters/digits/hyphen/underscore. Keep the scoped key binding with durable run records; no independent key expiry is introduced. Accepted-but-unclaimed runs may be claimed after restart; claimed runs with lost owners must reconcile. The user selected
reconciliation followed by explicit Admin retry for an unpublished interrupted
run ([ADR-0052](../../adr/0052-interrupted-refresh-recovery.md)). An API-only
restart does not stop a healthy worker.

Background execution belongs outside the HTTP request and app factory. Closing
the browser does not cancel it. Supervision, ownership, and restart handling
must be established across processes; a thread tied to a request is insufficient.
No separate approval or publish endpoint is included.

`GET /api/refresh/{run_id}` returns selected fields:

- `run_id`, `status`: `accepted`, `running`, `succeeded`, `retained`, `failed`,
  `interrupted`; selected additional nonterminal state `publication_unknown`.
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
- Selected `publication`: `state` (`pending`, `published`, `not_published`,
  `unknown`), nullable `generation_id`, `previous_generation_id`, and nullable
  `no_publication_reason`. This replaces the insufficient boolean-only draft;
  see the uncertainty/reconciliation proposal in [design-notes.md](design-notes.md).
- Nullable `failure`: safe `code` and `message`, without raw upstream errors.

Unavailable counts are null, never guessed zeros. Final quality mapping must
reconcile with the connector's existing dispositions/ledger; overlapping reason
counts must not inflate the excluded-row count. Coverage does not certify that
all upstream observations exist.

Success may publish with row exclusions and retained data. The user selected
`retained` for all-three-excluded input with previous data, consistent with the
connector plan; `succeeded` means confirmed new publication. Selected publication
fields for retention are `state: not_published` and
`no_publication_reason: all_incoming_rows_excluded`. Some wholly excluded
datasets retain previous valid data while other valid changes can publish.
Empty routes, missing/failed pages, resource exhaustion or integrity failures
fail the run. Never publish only a subset of datasets. Unknown Admin run ID
returns `404 refresh_unavailable`; non-Admin access is denied before lookup.

The latest-run lookup capability is user-approved. Selected route:
`GET /api/refresh/latest`, with response `{"run": <same run object as by-ID>}`.
Return the active run when one exists, otherwise the most recently admitted run,
across Admin requesters; tie-break equal admission timestamps by run ID. When
there has been no run, return `200` with `{"run": null}`. It does not admit work
or provide a history list. Authorization precedes lookup. If PostgreSQL/session
resolution is unavailable, return `503`, not a fabricated empty response.

## Error contract

Use the existing HTTP error envelope shape:

```json
{"error": {"code": "invalid_request", "message": "Invalid request"}}
```

| HTTP status | Selected codes | Meaning |
| --- | --- | --- |
| `400` | `invalid_request`, `invalid_sql`, `unsupported_sql`, `page_out_of_range`, `page_size_mismatch` | Input/SQL rejected; correct before retry |
| `401` | `unauthenticated` | Sign in again |
| `403` | `forbidden` | Current access/origin/CSRF rejected |
| `404` | `dataset_unavailable`, `query_unavailable`, `refresh_unavailable` | Resource unavailable; no protected details |
| `409` | `refresh_busy`, `idempotency_conflict` | Refresh admission conflict |
| `410` | `preview_unavailable`, `query_unavailable` | Known continuation expired/lost; restart explicitly |
| `422` | `query_resource_limit` | Query exceeds execution resources |
| `429` | `result_capacity_exhausted` | Per-user retained-result admission exhausted |
| `503` | `query_busy`, `result_capacity_exhausted`, `data_unavailable`, `service_unavailable` | Busy worker or unavailable data/dependency |
| `504` | `query_timeout` | Execution deadline exceeded |

Busy responses include a bounded `Retry-After`; its value is a retry suggestion,
not a completion guarantee. Refresh execution failures are exposed in its status
resource, not as a retroactive failure of an already accepted POST response.

## Frozen representation and remaining runtime gates

Public projections are defined in `domain/datasets.py` and parity-tested against
physical modeled v1 schemas. All exposed modeled fields are non-nullable. Catalog,
preview and SQL use the same projection; arbitrary SQL columns are never expanded.
National adds calculated percentage decimal(38,2), exact fraction strings and two
display strings; capacity/outage/reported percentage are decimal(38,12). Storage,
source and provenance fields are not public.

Canonical retained bytes are compact UTF-8 JSON with insertion order
`encoding_version`, `columns`, `rows`, `retained_row_count`, `truncated`,
`truncation_reason`, `limits`. Count all fields once inside the 1,048,576-byte
budget. Reserve worst-case fixed metadata (`max_rows`, `byte_limit`, plus one byte
for boolean width) before adding complete rows. At the first non-fitting row stop;
never skip ahead. Offset indexes and HTTP envelopes need separately bounded storage.
The canonical document is an internal artifact, not a replacement HTTP envelope.

Integer/decimal values are strings; finite floats are numbers and nonfinite
values are `NaN`, `Infinity`, `-Infinity`. Date/time/local timestamp are ISO strings;
instants normalize to UTC. Binary is base64. Lists recurse; structs are ordered
field arrays; maps are key/value pair arrays. Engine compatibility is tested for
these types. Unsupported values fail explicitly. Nanosecond timestamps, calendar
intervals, time-with-timezone, unions/variants, BIGNUM, UUID/enum and fixed arrays are not
currently claimed: their lossless engine conversion requires further evidence.
DATE/TIMESTAMP min/max Python sentinels are rejected because engine infinities
convert to those same values; finite extremes cannot be distinguished.

Initial out-of-range POST errors include owned `query_id` and `expires_at` in
`error.details`, permitting GET page 1 without repeating execution. Optional
`error.retry_after_seconds` agrees with `Retry-After`. CSRF/origin failures preserve
the auth layer's generic `forbidden`. Per-user retention admission is 429; global
admission is 503. No unexpired result eviction is introduced.

Refresh dataset statuses are `pending`, `processing`, `succeeded`, `retained`,
`failed`. A run always contains all three public IDs. Unavailable quality and
coverage remain null. All run/publication combinations have synthetic fixtures;
status is not an invented completion percentage. Idempotency retry preserves the
recorded interval even after current settings change.

Runtime gates remain: verified Linux isolation/termination, parser/worker wall-clock
budgets, cold/warm preparation and combined refresh/query measurements, process
ownership, cache/spill/spool limits and reviewed result/preview quotas. The proposed
three-results/user and ten/global are not activated by default. Phase 6 implements
Idempotency-Key preflight and exposed Location/Retry-After headers. HTTP routes
are explicitly opt-in; real execution requires supervisor-supplied analytical
resources with reviewed evidence and bounded lifecycle ownership. No live
publication or deployment was performed.


## Implemented transport bounds and local composition

Requests are capped at 131,072 bytes; URL query strings at 8,192 bytes; SQL at
65,536 UTF-8 bytes. Duplicate JSON keys and query parameters, unknown fields,
GET bodies, non-JSON/encoded POST bodies, malformed dates, noncanonical positive
integers and cursor/filter mixtures return `400 invalid_request`. Positive page
numbers are bounded by 2,147,483,647; page sizes remain 1–500.

`create_app` accepts already-constructed `DataServices` and starts no jobs or
connections. Bootstrap uses the same lazy operational pool for access and durable
publication/refresh. Refresh remains an independently started `refresh-worker`.
Without reviewed analytical resources, authorized preview/submission receives
`503 service_unavailable`; retained GET IDs are unavailable rather than rerun.
The supervisor may supply `DataHttpResources` and explicitly call the
`outage_data_start` extension after establishing ownership; construction never
calls it. `outage_data_close` closes only API-owned resources and cannot cancel
an independently supervised refresh worker.

Migration `0003_refresh_timestamps` stores actual claim/terminal timestamps.
Historical timestamps remain null instead of being reconstructed. Coverage is
reported only from fully verified modeled partitions; unknown prior reports
remain null. Internal encoding versions, storage identities, ownership fencing
and provider diagnostics do not appear in responses.

The `query_row_limit` fixture shows page 1 of 1,000 retained rows with page size
1. It is a complete page, not a shortened retained result. Named duplicate-label
and reference-free fixtures cover those independent SQL behaviors.
