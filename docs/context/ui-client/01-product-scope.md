# Product scope

Outage Explorer helps people explore U.S. nuclear outage data without manually
reshaping EIA records in spreadsheets. It serves authenticated users from a
shared, backend-owned dataset and supports open-ended analytical questions.
This repository handoff covers the web client; the backend remains separately
implemented in Python/Flask.

## Product promises

- **Availability:** after ingestion, browsing and querying use backend-owned
  data independently of EIA availability. This is not browser-offline support;
  the browser still needs the application backend.
- **Trust:** metrics and findings are grounded in actual, reproducible EIA
  observations. Clearly distinguish missing data, retained older data and zero.
- **Access control:** no product path exposes facility or generator details to
  Viewers. Filtering already-downloaded unauthorized rows is insufficient.

## Personas and permissions

| Capability | Viewer | Analyst | Admin |
| --- | --- | --- | --- |
| National catalog, schema, previews and metric | Yes | Yes | Yes |
| Facility/generator catalog, schemas and records | No | Yes | Yes |
| Read-only SQL | National datasets only | All permitted analytical datasets | Same as Analyst |
| Start/check refresh | No | No | Yes, backend capability; UI conditional |
| Identity/session tables or engine internals through SQL | No | No | No |

The backend's PostgreSQL authorization tables determine permissions. Cognito
supplies verified identity; client-side role flags, Cognito groups and OAuth
scopes do not independently grant product access. Granular policies must also
apply when configured; no tenant model, facility assignment or hidden-column
policy has been selected. Use server-provided capabilities when the contract
exists, and handle denied requests even after a screen was initially allowed.

## Expected initial web capabilities

1. Sign in through Cognito managed login, display session state and sign out.
2. Discover only permitted datasets and inspect their available schema.
3. Preview authorized records with date filters and facility filters where
   applicable, using backend pagination.
4. Present the ready-made national daily offline-capacity metric within the
   relevant Figma screen. A separate dashboard/chart page is not mandated.
5. Compose and run read-only SQL, then inspect column metadata and numbered
   result pages. Support open-ended exploration rather than preset questions.
6. Explain loading, empty, unavailable, denied, expired, busy and truncated
   states with a clear next action.

Backend Admin refresh is required, but a dedicated Admin screen remains
deferred unless included in the agreed UI scope. Its semantics are documented
in this pack so a future screen does not invent an approval workflow.

## Data meaning

The three daily EIA routes are `us-nuclear-outages`,
`facility-nuclear-outages` and `generator-nuclear-outages`. Source route names
are not promised SQL table names or client API routes.

| Grain | Row identity in the verified sample | Meaning |
| --- | --- | --- |
| National | `period` | One selected national observation per date |
| Facility | `period`, `facility` | One selected observation per facility/date |
| Generator | `period`, `facility`, `generator` | One selected observation per generator within its facility/date |

The recorded source fields include `period`, `capacity`, `outage`,
`percentOutage` and unit attributes. Detail records add `facility`,
`facilityName` and, for generators, `generator`. These describe source evidence,
not a finalized JSON response schema. Identifiers are opaque strings; preserve
leading zeros and alphanumeric values. Generator IDs are scoped to a facility,
and a facility's name is an attribute rather than its identifier.

`capacity` and `outage` are MW. The accepted national metric is
`100 × outage / capacity`, alongside EIA's reported `percentOutage` from the
same observation. Present both percentages to two decimals with decimal
half-up rounding. Prefer backend-supplied display/exact values under an agreed
contract; do not silently approximate decimal data through JavaScript numbers.

Label this as the daily share of EIA-reported nuclear capacity out of service,
including full outages and partial output reductions. It is not a reactor
shutdown count, lost-energy estimate, full-day average, outage duration or cause.
Do not average facility percentages to recreate the national metric. Do not
add match/mismatch badges or discrepancy flags between the two percentages.
Source-percentage differences alone do not invalidate an observation.

Use observation dates as calendar dates, without timezone shifts. Missing or
excluded observations are unavailable, not zero. A valid zero outage displays
as `0.00%`. Never interpolate missing observations and present them as measured.

## Coverage and evidence limits

The offline verification baseline is September 1–30, 2026. The accepted initial
live-ingestion interval is April 2–October 1, 2026 inclusive. Neither is proof
of currently published product coverage. Date controls should use coverage
metadata supplied by the backend; do not hardcode a rolling 30-day assumption.

The baseline contains 30 national, 1,650 facility and 2,850 generator records.
The facility response advertises 2,850 despite returning 1,650. This is an
unresolved upstream completeness diagnostic; do not invent the difference as
missing observations or use that upstream total as the UI's pagination count.
Matching aggregate values do not prove source completeness. These historical
sample counts are not live product totals.

The overall project requires reproducible reconciliation and at least three
real anomalies. That obligation does not require a new findings UI. Display
findings only from verified material, within the caller's permissions; do not
create synthetic anomalies to fill a design.

## Explicit non-goals

- Registration, password-recovery and role/user-management screens.
- A custom credential store or authorization server.
- Direct browser/Next.js access to EIA, Parquet, S3, RDS or an analytical engine.
- SQL writes, schema/admin commands, external file/network access or extensions.
- Scheduled refresh, manual candidate approval or a separate publish button.
- Durable query history, saved queries, exports, collaboration, alerts, maps,
  outage classification or event reconstruction without a new requirement.
- New dashboards, charts or navigation unrelated to the supplied Figma and
  agreed workflows; redesigning the product from a generic admin template.
- Frontend deployment/provider selection as an implicit consequence of the
  backend's EC2 choice. Client hosting remains open.
