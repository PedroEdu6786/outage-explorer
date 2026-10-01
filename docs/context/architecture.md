# Architecture

Status: **early — most structure is undecided.** Each big choice below should
get an ADR in `docs/adr/` once decided; this doc records the *current shape*,
the ADRs record *why*.

## System context (C4 level 1)

```
[EIA Open Data API v2] ──▶ [Connector] ──▶ [Local extracts / data model]
                                                     ▲
                                                     │
[Authenticated API client] ──▶ [Backend API] ──────────┘
                                   │
                                   └── Admin refresh ──▶ [Connector]
```

The backend serves locally stored EIA data. The connector fetches upstream
data for the model. This repository currently covers these three parts;
frontend work is deferred by the user's instruction on 2026-10-01.

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
| Data storage | partly specified | Raw extracts as Parquet; model as Parquet or Delta; query engine and optional cache undecided |
| Deployment | **open** | TODO: ADR-0005 |

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

- Decisions: see `docs/adr/` (create ADR-0001..0005 as the open items above
  get resolved).
- `AGENTS.md` at repo root tells AI agents how to work in this codebase.
