# Architecture

Status: **early — most structure is undecided.** Each big choice below should
get an ADR in `docs/adr/` once decided; this doc records the *current shape*,
the ADRs record *why*.

## System context (C4 level 1)

```
[EIA Open Data API v2] ──▶ [Connector] ──▶ [Backend-owned persistent data]
                                                     ▲
                                                     │
[Authenticated API client] ──▶ [Backend API] ──────────┘
                                   │
                                   └── Admin refresh ──▶ [Connector]
```

The deployed backend serves its own persistently stored EIA data to all
authorized clients. “Local” is relative to the application, not the Admin's
computer. The connector fetches upstream
data for the model. This repository currently covers these three parts;
frontend work is deferred by the user's instruction on 2026-10-01.

The user explicitly corrected the earlier laptop-only deployment assumption.
Development must reproduce a realistic shared backend deployment. Data and
operational state must survive application/query container replacement.
The user selected one active backend replica, serving all authorized users.
Multiple replicas and horizontal autoscaling are deferred. The user accepted
Amazon S3 for durable raw/modeled Parquet and DuckDB for analytical SQL;
see [ADR-0001](../adr/0001-s3-parquet-duckdb.md). Backend analytical disk is
disposable. Direct S3 reads versus temporary staging remains open;
staged in-memory execution is the current security proposal. SQLite operational metadata and one application-owned refresh
task remain proposals; operational state still needs its own durable storage.
Backend hosting, SQL isolation runtime and availability target remain undecided.
Query worker/process counts are separate from API replicas.

The user has confirmed seeded database accounts and broad read-only analytical
SQL, including joins, CTEs, subqueries, aggregations, and window functions.
An independent auth service is not a requirement. Exact engine version, SQL surface,
reference authorization, and execution boundaries remain design choices.

The council's draft spec and design discussion are under
`docs/specs/outage-explorer-backend/`; only explicitly accepted decisions
(including ADR-0001) are settled. The remaining mechanisms are proposals.

Designs must preserve the three [product promises](overview.md): browsing
and querying use local data after ingestion, findings are reproducible from
actual EIA records, and no product path exposes facility or generator details
to Viewers. Authorization must precede data access; read-only SQL syntax alone
does not establish that a query is safe.

The proposed fleet metric is same-day national offline capacity divided by
national total capacity, pending verification of source fields and units.
An Admin-only refresh endpoint with a clear outcome meets the core refresh
capability; scheduling and an Admin UI are deferred. Sync versus async refresh
remains undecided.

## Required building blocks and open choices

| Concern | Status | Notes |
|---------|--------|-------|
| Data source | decided (de facto) | EIA Open Data API v2 |
| EIA datasets | required by brief | Daily `us-nuclear-outages`, `facility-nuclear-outages`, and `generator-nuclear-outages` |
| Backend | **open** | TODO: ADR-0002 — language/framework |
| Frontend | **deferred** | Outside current repository scope; no UI choice needed now |
| Analytical storage | **Amazon S3 + Parquet confirmed** | Separate persistent bucket; region and bucket lifecycle/security configuration pending; see ADR-0001 |
| Query engine | **DuckDB confirmed** | Remote reads versus staging, exact SQL surface and isolated execution still require validation |
| Operational storage | **open** | Users, sessions, publication/run/cursor metadata require persistence separately from Parquet objects; SQLite remains proposed |
| Deployment | **one replica confirmed** | Shared service for all authorized users, persistent data/state, reproducible development; hosting/operational persistence/runtime choices pending |

## Key data-flow questions to resolve first

1. What do actual metadata and rows establish about natural keys, units,
   missing values, and relationships across the three daily routes?
2. Which fields define daily fleet capacity offline share, and what explains
   disagreements across grains?
3. What does "kept current" mean, and how should refresh handle failures
   and source revisions?
4. What SQL subset can we authorize reliably, checking every referenced
   dataset before any query executes?

## Constraints

- Must remain grounded in EIA data — no hand-curated datasets.
- TODO: team size, timeline, and infra budget constraints.

## Related

- Decisions: [ADR-0001 — S3, Parquet and DuckDB](../adr/0001-s3-parquet-duckdb.md).
  Add further numbered ADRs as the remaining choices are resolved.
- `AGENTS.md` at repo root tells AI agents how to work in this codebase.
