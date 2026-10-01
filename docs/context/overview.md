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

Current repository scope, confirmed by the user on 2026-10-01:

The user clarified deployment scope: build realistic application development
and deployment, with ingested Parquet owned by our backend infrastructure and
served to all authorized clients through the API. A developer laptop is only
a development environment. The user selected one backend replica for now;
multiple replicas and horizontal autoscaling are deferred. The user accepted
a separate object-storage bucket as the durable home for Parquet and then
selected Amazon S3 with DuckDB as the query engine. Backend analytical disk is
disposable; direct remote reads versus temporary staging remains open.
Operational database persistence and backend hosting are separate open concerns. Seeded
challenge accounts remain sufficient; this clarification does not request
registration, a frontend, an automatic refresh schedule, or a compute provider.

- **Data connector:** extract the three daily EIA nuclear outage routes
  (national, facility, generator) into local Parquet with pagination,
  validation, logging, and safe reruns.
- **Data model:** define keys, relationships, and types; implement daily fleet
  capacity offline share; reconcile at least 30 days across the three grains
  and document at least three real anomalies with reproducible evidence.
- **Backend:** provide authentication, an authorized dataset catalog,
  date/facility-filtered previews with backend pagination, read-only SQL,
  and Admin-only refresh with an outcome.

The technical challenge remains the requirements source for these three parts.
Frontend work is deferred by the user's instruction. It remains part of the
original challenge, so this scope does not represent the complete submission.
Outage-type classification and event reconstruction are unverified ideas,
not current requirements.

## Epic outcomes

"In scope" identifies planned work, not completed implementation. E7 is
retained for traceability to the original challenge and remains deferred.

| Epic | Outcome | Current scope |
|------|---------|---------------|
| E1 — Reliable local source data | Ingest all three routes, paginate, validate, store Parquet, and rerun safely | In scope |
| E2 — Analytical model and findings | Define keys and relationships, implement the fleet metric, reconcile grains, document three real anomalies | In scope |
| E3 — Authentication and authorization | Seed the three personas and enforce permissions before data access | In scope |
| E4 — Discovery and preview | Show permitted schemas and support filtered, backend-paginated previews | In scope |
| E5 — Read-only SQL | Support a documented SQL subset with table authorization and result limits | In scope |
| E6 — Controlled refresh | Let Admins refresh data and receive a clear outcome | In scope |
| E7 — Minimal web experience | Login, browse datasets, filter records, and run SQL through a web UI | Deferred |
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
- This is a challenge with seeded database users; registration, password
  recovery, and external identity integration are outside the current scope.
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
choices. This acceptance does not extend to the remaining proposed stack.

### Proposed choices

- **Fleet metric:** same-day national offline capacity divided by national
  total capacity (multiply by 100 when expressing it as a percentage).
  This is the user's proposal, subject to verification of source fields,
  units, and denominator meaning; it is not yet a finalized definition.

### Decisions requiring real-data investigation

- Natural keys, required fields, types, and relationships for each grain.
- Metric field mapping and units, including missing or zero denominator
  handling.
- Missing parent facilities, mismatched sums, actual anomalies, and evidence
  supporting explanations for discrepancies.
- Source revisions and available periods that inform refresh semantics.

Frameworks, exact SQL dialect/function surface and reference discovery, refresh execution mode, and
the definition of "kept current" also remain open design choices. Document
the accepted choice, rejected alternative, and rationale in `docs/adr/`;
do not infer a choice from the epic list.

### Deferred extras

- Scheduled refresh and an Admin screen.
- Caching and other unselected challenge extras. Broad analytical SQL was
  separately selected by the user and is now required. The mandatory
  access-control promise applies to every supported query path.
- Frontend work, including the challenge's core E7 web experience, remains
  deferred under the current repository scope. E7 is required by the full
  challenge, rather than being an optional challenge extra.

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

- **Analyst:** access all analytical datasets, preview by date/facility,
  and run read-only SQL.
- **Viewer:** national trends only; no facility or generator detail through
  any backend path.
- **Admin:** Analyst capabilities plus data refresh.

## Out of scope (for now)

- Frontend implementation, UI framework selection, login screens, browser
  tables, SQL editor UI, and visualizations are deferred for now.
- Backend authentication, authorization, preview pagination, SQL execution,
  and refresh remain in scope independently of any future frontend.

## Related docs

- [architecture.md](architecture.md) — system design and key structures.
- [conventions.md](conventions.md) — coding and process good practices.
- [../adr/](../adr/) — architecture decision records (the "why" behind choices).
