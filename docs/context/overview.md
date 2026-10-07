# Project Overview

Outage Explorer lets users explore backend-stored U.S. nuclear outage data,
query datasets their role permits, and understand discrepancies between
national, facility, and generator observations.

## Core product promises

- **Availability:** browsing and querying work from the backend's own persistent data after ingestion, independently of EIA availability and individual client machines.
- **Trust:** metrics and discrepancies are explained using reproducible
  evidence from actual EIA records.
- **Access control:** Viewers can never retrieve facility or generator
  details through any product path.

## Problem

Today, people who track U.S. nuclear plant outages (analysts, traders,
journalists, industry watchers) pull data from the EIA (U.S. Energy
Information Administration) Open Data API and manually reshape it in
spreadsheets. This is slow, error-prone, and doesn't support the questions
they actually want to ask.

## What we're building

Current backend scope and implementation status:

The user clarified deployment scope: build realistic application development
and deployment, with ingested Parquet owned by our backend infrastructure and
served to all authorized clients through the API. A developer laptop is only
a development environment. The user selected one backend replica for now;
multiple replicas and horizontal autoscaling are deferred. The user accepted
a separate object-storage bucket as the durable home for Parquet and then
selected Amazon S3 with DuckDB as the query engine. Backend analytical disk is
disposable; [ADR-0008](../adr/0008-local-parquet-file-cache.md) selects a
bounded local disk cache of modeled Parquet for DuckDB scans.
Python/Flask, PostgreSQL on Amazon RDS, and EC2 deployment are accepted.
[ADR-0038](../adr/0038-ec2-deployment-local-development.md) replaces ECS and
keeps development local without an EC2 prerequisite. ADR-0032 replaces SQLite.
Cognito/RDS application integration is implemented, and subsequent local
authentication/web integration was accepted by the user; see the
[verification record](../specs/user-access/verification.md). EC2 deployment
configuration and full runtime acceptance remain open. Seeded challenge accounts
remain sufficient; registration and automatic refresh scheduling are excluded.

- **Data connector:** extract the three daily EIA nuclear outage routes
  (national, facility, generator) into local Parquet with pagination,
  validation, logging, and safe reruns.
  ADR-0023/0024 accept documentation-first required fields with collected-data
  fallback, invalid-row exclusion with visible accounting, identical-duplicate
  collapse and latest-valid-value replacement. Bounded field/key contracts are
  implemented; PostgreSQL stores refresh quality and publication metadata.
  ADR-0060 limits durable modeled output to three unified resource Parquet files. ADR-0025 accepts a visible quality
  summary in the Admin refresh outcome with counts and exclusion reasons.
  ADR-0026 keeps existing data when every incoming row is excluded and retains
  older valid rows when their replacements are invalid. ADR-0037 defines initial
  live loading for April 2–October 1, 2026 inclusive, requiring usable output in
  all three grains. Later refreshes retain absent keys and wholly excluded routes
  while publishing other valid updates; report each retention reason separately.
- **Data model:** define keys, relationships, and types; implement daily fleet
  capacity offline share; reconcile at least 30 days across the three grains
  and document at least three real anomalies with reproducible evidence.
- **Backend:** provide authentication, an authorized dataset catalog,
  date-filtered previews with backend pagination and optional exact facility
  selection on facility/generator datasets, read-only SQL,
  and Admin-only refresh with an outcome.

The technical challenge remains the requirements source for these three parts.
On October 4, the user requested a handoff for a separate UI repository using
React, Next.js, TypeScript, Tailwind, atomic components and an existing Figma
design ([ADR-0039](../adr/0039-separate-ui-client-atomic-design.md)). The
[Astra context pack](ui-client/README.md) captures expected behavior and
integration contracts. UI implementation exists in the separate
`outage-explorer-web` repository. Its presence does not establish full integrated
acceptance or completion of the challenge submission.
Outage-type classification and event reconstruction are unverified ideas,
not current requirements.

## Epic outcomes

The health scaffold, connector, analytical model, authentication, data API,
refresh and isolated analytical adapters are implemented with controlled tests.
Cross-grain findings are recorded in [challenge evidence](../challenge/README.md).
The table describes scope, not a declaration that every acceptance criterion is
closed. Local activation under ADR-0056 does not close full runtime/deployment
checkpoints.

| Epic | Outcome | Current scope |
|------|---------|---------------|
| E1 — Reliable local source data | Ingest all three routes, paginate, validate, store Parquet, and rerun safely | In scope |
| E2 — Analytical model and findings | Define keys and relationships, implement the fleet metric, reconcile grains, document three real anomalies | In scope |
| E3 — Authentication and authorization | Seed the three personas and enforce permissions before data access | In scope |
| E4 — Discovery and preview | Show permitted schemas and support filtered, backend-paginated previews | In scope |
| E5 — Read-only SQL | Support broad DuckDB analytical SQL with table authorization, result limits and documented compatibility exceptions | In scope |
| E6 — Controlled refresh | Let Admins refresh data and receive a clear outcome | In scope |
| E7 — Minimal web experience | Login, browse datasets, filter records, and run SQL through a web UI | Implemented in separate repository; full integrated acceptance separate |
| E8 — Reproducible delivery | Runnable setup, tests, required documentation, incremental commits, and live-session readiness | In scope from the beginning |

## Requirements and decision status

Keep explicit requirements, proposed choices, decisions requiring real-data
investigation, and deferred extras distinct in subsequent specs and plans.
The challenge deliberately leaves design decisions open; a proposal becomes
a decision only when it is explicitly accepted and its evidence is recorded.

### Explicit requirements

- Findings must include reconciliation over at least 30 days and at least
  three concrete anomalies from actual EIA records, with reproducible queries
  or code. Hypothetical edge cases cannot substitute for these findings.
- Authorize every supported SQL reference before execution. A `SELECT` can
  still access forbidden data or engine functions; read-only syntax alone
  does not establish safety.
- The user confirmed broad read-only analytical SQL: joins, CTEs, subqueries,
  aggregations, and window functions over authorized product datasets.
  Analysts need open-ended exploration rather than predefined investigations.
- This is a challenge with seeded personas and local operational identities;
  registration and password recovery remain outside scope. OAuth2
  remains required; OIDC is no longer required under ADR-0017. Cognito managed login and
  OAuth2 Authorization Code with PKCE are selected in ADR-0018.
- Define and document the daily share of total fleet capacity offline.
- Provide Admin-only refresh and a clear outcome. A documented endpoint
  satisfies the core capability; a scheduler or Admin screen is not required.
- Maintain incremental commits and Engineering Notes from the beginning.
  Notes must identify AI contributions, a concrete AI mistake and how it was
  caught, and verification beyond simply running generated code.
- Keep the implementation explainable and ready for live debugging and
  extension: the live session accounts for 60% of the evaluation.

### Accepted storage and engine

Accepted storage/engine decision: [ADR-0001](../adr/0001-s3-parquet-duckdb.md)
records Amazon S3 + Parquet + DuckDB, alternatives, rationale and open loading
choices. [ADR-0028](../adr/0028-python-flask-backend.md) accepts Python/Flask, and [ADR-0032](../adr/0032-postgresql-on-rds.md) accepts PostgreSQL operational storage on Amazon RDS.

### Accepted fleet metric

“As an Analyst, I want the share of total fleet capacity offline per day,
ready-made” means the backend provides the daily U.S. nuclear capacity
offline percentage without requiring the Analyst to derive it. Use national
`outage / capacity` as a fraction, or `100 * outage / capacity` as a
percentage; both source fields are in MW. Show the calculated percentage and
EIA's `percentOutage` from the same stored observation without match/mismatch
labels or discrepancy flags ([ADR-0031](../adr/0031-show-national-percentages-without-discrepancy-flags.md)).
Preserve calculation precision; present percentages to two decimals with
halfway values rounded up. The accepted meaning is the daily share of
EIA-reported nuclear capacity out of service, including full outages and
partial output reductions ([ADR-0035](../adr/0035-national-outage-capacity-meaning.md)).
It describes daily reported status; it does not establish reactor shutdown
counts, full-day average output, lost energy, outage duration or cause.
The public `national` dataset includes the calculated and source percentages
under the existing national-data role policy; no separate metric dataset is required.

[ADR-0006](../adr/0006-daily-fleet-offline-share.md) records the accepted
meaning and calculation, verified fields and three actual sample dates.
ADR-0027 resolves required national values and positive-capacity handling;
ADR-0031 resolves percentage presentation. Broader validation remains open.

The implemented offline national verification uses the fixed recorded interval
September 1–30, 2026, inclusive ([ADR-0033](../adr/0033-fixed-national-verification-period.md)).
Account for every date's usable result or coverage gap without live retrieval
or invented values. Capacity is constant in this sample, limiting historical
claims. This baseline does not set the product's supported dates or the later
live ingestion/refresh window.

EIA is authoritative for reported national values. If otherwise valid records
for one date conflict within a retrieval, the last record in recorded source
order wins; retain one modeled row and the source evidence
([ADR-0034](../adr/0034-last-national-record-wins.md)). Invalid records remain
excluded under ADR-0027. This fallback does not assert source revision timing.

### Decisions requiring real-data investigation

- Broader historical validation beyond the implemented bounded grain contracts.
- Remaining value validation rules and historical metric checks. National
  partial-output meaning is accepted in ADR-0035; exact historical capacity-data
  vintage remains an evidence limitation, and reported national capacity is used.
- Generalizing the recorded parent/sum discrepancies and three real findings
  beyond their identified evidence intervals.
- Source revisions and available periods that inform refresh semantics.

Broad DuckDB analytical feature support is selected in ADR-0012; compatibility
and reference discovery have controlled tests, with full runtime evidence separate. EC2 deployment configuration, deployed RDS connectivity
and exact memory/disk budgets remain open. ADR-0013 accepts initial query
controls: one analytical worker, retryable busy responses, 10-second execution
timeout and 1,000-row / 1-MiB output caps with explicit truncation.
[ADR-0020](../adr/0020-paginate-query-results.md) adds pagination of a single
SQL execution’s result without injecting ORDER BY, LIMIT or OFFSET, replacing
ADR-0019’s default ordering. [ADR-0021](../adr/0021-number-query-result-pages.md)
adds `page` (1-based) and `page_size`, with subsequent pages selected by
`query_id` using the same execution and page size.
[ADR-0022](../adr/0022-ephemeral-query-pagination-state.md) keeps query-ID metadata
in a bounded, expiring in-memory store. Store loss or expiration requires an
explicit rerun with a new ID; it never silently restarts pagination at page 1.
Abandoned state and any orphaned result files must be reclaimed. The store
uses process-owned metadata and private result spools. Pages default to 100 rows
with a maximum of 500; ADR-0059 fixes preview/result lifetime at 60 seconds.
The existing total result cap remains unchanged. Recent coverage is selected in ADR-0009;
the initial load interval is April 2–October 1, 2026 under ADR-0037, and HTTP
refresh freezes configured dates at admission under ADR-0051. Broader source
completeness remains an evidence question. Retention/recovery policy is deferred
under ADR-0010.
Admin-triggered background refresh with automatic publication is accepted in
[ADR-0003](../adr/0003-admin-refresh-publication.md). Document
the accepted choice, rejected alternative, and rationale in `docs/adr/`;
do not infer a choice from the epic list.

### Deferred extras

- Scheduled refresh and an Admin screen.
- Query-result caching and other unselected challenge extras. Local Parquet
  file caching is selected in ADR-0008. Broad analytical SQL was
  separately selected by the user and is now required. The mandatory
  access-control promise applies to every supported query path.
- Frontend implementation, including the challenge's core E7 web experience,
  belongs to the separate client repository under ADR-0039. E7 is required by
  the full challenge; implementation exists separately and full acceptance is distinct.

## Domain glossary

| Term | Meaning |
|------|---------|
| EIA | U.S. Energy Information Administration; publishes the Open Data API (v2) |
| NRC | U.S. Nuclear Regulatory Commission; licenses reactors |
| Outage | A period when a reactor unit is offline (planned refueling, forced, maintenance) |
| Outage type | Classification of why the unit is offline (e.g. refueling, forced) |
| Unit | An individual reactor at a plant; a plant can have multiple units |
| Refueling outage | Scheduled outage to replace fuel, typically every 18–24 months |
| Capacity factor | Actual generation vs. maximum possible; affected by outages |
| Fleet | The full set of U.S. commercial nuclear reactors (~94 units at ~54 plants) |

## Users

- **Analyst:** access all analytical datasets, preview by date and facility on
  detail datasets,
  and run read-only SQL.
- **Viewer:** national trends only; no facility or generator detail through
  any backend path.
- **Admin:** Analyst capabilities plus data refresh.

## Out of scope (for now)

- Frontend implementation, login screens, browser tables, SQL editor UI and
  any scoped visualizations belong to the separate UI repository. Its framework
  and atomic component direction are selected in ADR-0039.
- Backend authentication, authorization, preview pagination, SQL execution,
  and refresh remain in scope independently of any future frontend.

## Related docs

- [architecture.md](architecture.md) — system design and key structures.
- [code-structure.md](code-structure.md) — accepted layered monolith layout and agent dependency rules (ADR-0030).
- [conventions.md](conventions.md) — coding and process good practices.
- [../adr/](../adr/) — architecture decision records (the "why" behind choices).

### Authentication and browsing refinement

ADR-0017 retains OAuth2 and removes required OIDC. ADR-0043 narrows authorization to
role-based access with seeded users; registration, Admin user management and
separate read/write/delete permissions are excluded. ADR-0018 selects Cognito
managed login and OAuth2 Authorization Code with PKCE. Client configuration,
identity/session mapping and essential local user fields are implemented; each
user has exactly one role (ADR-0044). Seeded personas retain local operational records. The accepted experience
uses one-hour application sessions, re-login on expiry, no automatic renewal
initially and current-session logout. ADR-0015 accepts preview pages of 100 rows
by default (initial configurable maximum 500), snapshot-bound cursors and a
fixed 60-second browsing expiry under ADR-0059, superseding the earlier
15-minute value. Cognito handles login and OAuth2 token issuance (ADR-0018);
local authentication/web integration acceptance and remaining live evidence are
recorded in the [verification record](../specs/user-access/verification.md).

ADR-0016 confirms application-owned authorization tables: identity comes from
the selected sign-in mechanism, while seeded local users, roles and assignments are controlled
by our operational database. ADR-0043 supersedes the earlier granular-policy scope.

## Facility and generator verification

The user's 2026-10-02 extension is implemented alongside national verification:
separate offline commands replay the fixed recorded baselines, use per-entity
natural keys, apply the shared policies, and write deterministic reports. See
[the contracts and findings](../specs/facility-generator-verification/verification.md).
Facility's advertised total differs from received rows; observed-entity date
coverage is explicit and does not prove upstream completeness. HTTP delivery is
implemented and cross-grain reconciliation is recorded in
[challenge evidence](../challenge/README.md); full runtime acceptance remains separate.
