# Architecture

Status: **layered Flask monolith accepted; health scaffold implemented**.
The liveness endpoint and import-boundary checks exercise initial composition.
Product use cases, runtime, storage, and execution mechanisms retain their
explicit accepted/proposed status and are not proven by liveness.

## Accepted application structure

[ADR-0030](../adr/0030-layered-flask-monolith.md) selects a layer-first monolith:
`domain`, `application`, `infrastructure`, and `entrypoints`, wired by `bootstrap`.
Follow the [code structure guide](code-structure.md) and root
[AGENTS.md](../../AGENTS.md) for responsibilities, allowed imports, agent rules,
and automated import-boundary checks. This replaces the feature-first structure
proposed in ADR-0029.

Domain policies remain plain Python. Application services own authorization
and orchestration through small interfaces; infrastructure implements them.
Flask routes and job/CLI entry points invoke application use cases. Keep one
application and release with separately bounded execution workers.

The [architecture study](../specs/outage-explorer-backend/architecture-options.md)
compares alternatives and describes query/refresh flows, state ownership, and
an independent-services example. The latter is not selected for implementation.
Flask replaces FastAPI under [ADR-0028](../adr/0028-python-flask-backend.md).
One WSGI application process with threads and separately supervised refresh
remains a runtime proposal. Capacity, ECS storage, session mapping, and the
isolated query launcher still require decisions and feasibility evidence.

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
disposable. A bounded local Parquet file cache is selected in
[ADR-0008](../adr/0008-local-parquet-file-cache.md);
Batch-based Parquet scans with bounded memory, temporary disk, concurrency
and results are accepted in [ADR-0007](../adr/0007-bounded-parquet-query-execution.md).
Full-dataset in-memory import is not required. Workers scan only authorized
cached files without network or S3 credentials; exact isolation runtime and
cache/resource budgets remain open. Python/Flask and PostgreSQL on Amazon RDS
are accepted in ADR-0028 and ADR-0032. Amazon ECS remains selected in ADR-0011;
its SQLite-specific EC2/EBS storage proposal is replaced by RDS. ECS launch type,
RDS configuration and connectivity remain open. Refresh coordination, SQL isolation runtime
and availability target remain undecided.
Query worker/process counts are separate from API replicas. ADR-0013 accepts
one analytical query at a time initially, retryable busy responses, a 10-second
execution timeout and 1,000-row / 1-MiB results with explicit truncation.
Memory/disk sizes and the separate preparation deadline require measurement.

The user has confirmed seeded database accounts and broad read-only analytical
SQL, including joins, CTEs, subqueries, aggregations, and window functions.
OAuth2 and granular authorization remain required; ADR-0017 removes required
OIDC. ADR-0018 selects Cognito User Pools with managed login and OAuth2
Authorization Code with PKCE. Client configuration, token/session mapping and
concrete row/column policies remain open. ADR-0012 targets broad DuckDB analytical features, with evidence-led exclusions.
Engine version, reference authorization and execution boundaries need verification.

ADR-0020 supersedes ADR-0019: paginate the result of one SQL execution without
adding ORDER BY, LIMIT or OFFSET. Preserve explicit clauses and the execution’s
result sequence across pages, including joins and aggregates. ADR-0021 adds
`page` (1-based) and `page_size`, with subsequent page selection by opaque
`query_id`. Retained state binds to caller, execution, snapshot and fixed page
size; reauthorize each page. ADR-0022 selects bounded, expiring in-memory
query-ID metadata, separate from durable application records. Store loss or
expiry requires an explicit rerun with a new ID; never silently return page 1.
A bounded result spool remains proposed; cleanup must reclaim abandoned state
and any orphaned files. Store implementation, result format, TTL and budgets
remain open. Existing total output limits remain the baseline pending explicit
revision. This behavior is specified, not implemented.

The council's draft spec and design discussion are under
`docs/specs/outage-explorer-backend/`; only explicitly accepted decisions
(including current, nonsuperseded decisions through ADR-0032) are settled.
ADR-0030 replaces the proposed structure in ADR-0029; remaining implementation
mechanisms keep their documented proposal status.

EIA observations are modeled as analytical datasets with versioned schema
contracts, as accepted in [ADR-0002](../adr/0002-analytical-dataset-contracts.md).
The contracts define row meaning, columns, types, units, nullability, verified
keys and source mappings. Raw and validated modeled Parquet live in S3;
DuckDB exposes authorized modeled data under stable SQL names. Exact EIA
schemas remain unverified. Operational entities have separate persistence.
The [integrity design](../specs/outage-explorer-backend/plan.md#duplicate-prevention-and-data-integrity)
records accepted invalid-row exclusion, identical-duplicate collapse and
latest-valid-value replacement (ADR-0023/0024). Required fields follow API
documentation, falling back to consistently recurring and identifying source
attributes. For national same-date conflicts within one retrieval, the last
valid record in recorded source order wins under
[ADR-0034](../adr/0034-last-national-record-wins.md); preserve source evidence
and its order for replay. Exact contracts, other-grain conflict rules and
report format/storage remain open.
ADR-0026 assumes initial analytical data is seeded: all-excluded refreshes keep
the active data unchanged; invalid replacements retain older valid rows with
original provenance, and the quality report explains both fallback outcomes. ADR-0025 accepts
a visible Admin refresh quality summary with row counts and exclusion reasons. Safe-publication mechanisms
remain proposed; S3 and DuckDB do not supply these application guarantees.

Designs must preserve the three [product promises](overview.md): browsing
and querying use local data after ingestion, findings are reproducible from
actual EIA records, and no product path exposes facility or generator details
to Viewers. Authorization must precede data access; read-only SQL syntax alone
does not establish that a query is safe.

The accepted ready-made fleet metric uses same-day national `outage / capacity`
(multiply by 100 for percent). Both fields are verified in MW; EIA's
`percentOutage` is shown alongside the calculated percentage from the same
stored observation, without agreement labels or discrepancy flags. Preserve
calculation precision and round to two decimals for presentation, with halfway
values rounded up ([ADR-0031](../adr/0031-show-national-percentages-without-discrepancy-flags.md)).
ADR-0027 requires usable national values and positive capacity. See
[ADR-0006](../adr/0006-daily-fleet-offline-share.md) for the accepted formula;
capacity-basis semantics, remaining validation details and historical checks
remain open.
The Admin starts a background refresh and checks its outcome. Successful
completion automatically makes the updated data active; current data stays
available while it runs or if it fails. There is no separate review or publish
action. See [ADR-0003](../adr/0003-admin-refresh-publication.md).
Scheduling and an Admin UI remain deferred; job execution details remain open.

## Required building blocks and open choices

| Concern | Status | Notes |
|---------|--------|-------|
| Data source | decided (de facto) | EIA Open Data API v2 |
| EIA datasets | required by brief | Daily `us-nuclear-outages`, `facility-nuclear-outages`, and `generator-nuclear-outages` |
| Backend | **Python/Flask health scaffold implemented** | Python >=3.12, Flask 3.1; pinned development dependencies in `requirements-dev.txt`; product integrations pending |
| Analytical model | **schema contracts confirmed** | See ADR-0002; source fields, keys and relationships await EIA investigation |
| Frontend | **deferred** | Outside current repository scope; no UI choice needed now |
| Analytical storage | **Amazon S3 + Parquet confirmed** | Separate persistent bucket; region/security configuration pending; retention/recovery policy deferred; see ADR-0001 |
| Query engine | **DuckDB with local Parquet cache confirmed** | ADR-0007/0008; broad analytical SQL selected in ADR-0012; budgets and isolation need verification |
| Operational storage | **PostgreSQL on Amazon RDS confirmed** | ADR-0032; sizing, connectivity and operational configuration remain open; recovery-policy work deferred |
| Deployment | **one replica on ECS confirmed** | ADR-0011; launch type, RDS connectivity and query runtime remain open |

## Key data-flow questions to resolve first

1. What do actual metadata and rows establish about natural keys, units,
   missing values, and relationships across the three daily routes?
2. Beyond ADR-0027's accepted missing-value and positive-capacity rules, what
   are the detailed capacity semantics and remaining validation rules, and what
   explains cross-grain differences?
3. What does "kept current" mean, and how should refresh handle failures
   and source revisions?
4. How do we authorize broad DuckDB analytical SQL, checking every referenced
   dataset before execution and documenting demonstrated limitations?

## Constraints

- Must remain grounded in EIA data — no hand-curated datasets.
- TODO: team size, timeline, and infra budget constraints.

## Related

- Decisions: [ADR-0001 — S3, Parquet and DuckDB](../adr/0001-s3-parquet-duckdb.md).
  [ADR-0002 — Analytical dataset contracts](../adr/0002-analytical-dataset-contracts.md).
  [ADR-0003 — Admin refresh publication](../adr/0003-admin-refresh-publication.md).
  [ADR-0028 — Python/Flask](../adr/0028-python-flask-backend.md).
  [ADR-0032 — PostgreSQL on RDS](../adr/0032-postgresql-on-rds.md).
  [ADR-0006 — Daily fleet offline share](../adr/0006-daily-fleet-offline-share.md).
  [ADR-0007 — Bounded queries](../adr/0007-bounded-parquet-query-execution.md).
  [ADR-0008 — Local Parquet cache](../adr/0008-local-parquet-file-cache.md).
  Add further numbered ADRs as the remaining choices are resolved.
- `AGENTS.md` at repo root tells AI agents how to work in this codebase.

Authentication experience is accepted in ADR-0014: one-hour application sessions,
re-login on expiry, no automatic renewal initially and current-session logout.
ADR-0015 accepts preview pages of 100 rows by default (initial maximum 500),
with snapshot-bound cursors expiring 15 minutes after the first page.

ADR-0016 makes our PostgreSQL authorization tables authoritative for roles,
permissions and policy attributes. The selected sign-in mechanism supplies verified identity; external
groups/roles do not independently confer product data access. ADR-0017 removes
the earlier OIDC-specific identity assumptions.

Cognito runs as a managed AWS service outside ECS. It owns login credentials
and token issuance; the Flask identity adapter validates access tokens, binds issuer/subject to
local users and applies PostgreSQL authorization tables. Configure seeded Cognito
accounts with public registration disabled. Application logout enforcement
and concrete OAuth client/session integration remain design work (ADR-0018).
