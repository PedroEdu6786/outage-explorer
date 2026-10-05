# Architecture

Status: **layered Flask monolith accepted; health and offline national/facility/generator verification implemented**.
The liveness endpoint and import-boundary checks exercise initial composition.
Product use cases, runtime, storage, and execution mechanisms retain their
explicit accepted/proposed status and are not proven by liveness.

The product HTTP refresh action uses a configured inclusive interval under
[ADR-0051](../adr/0051-configured-http-refresh-range.md), with no request date
overrides. Admission records that interval for the complete all-grain background
run; later configuration changes cannot change it. Initial-load policy and CLI
date overrides remain unchanged. The [data API contract](../specs/data-api/http-contract.md)
records implemented opt-in transport details. Phase 6 mounts seven HTTP
operations using injected use cases; transport enablement does not enable the
user-owned Linux runtime gate.

[ADR-0052](../adr/0052-interrupted-refresh-recovery.md) accepts continued work
through API-only restarts and publication reconciliation after worker loss.
Unpublished interrupted runs require explicit Admin retry; recovery mechanics
and ownership enforcement are implemented with controlled PostgreSQL/process
verification; live deployment remains separate.

User-access Phases 1–4 implement PostgreSQL users/roles, fixed sessions and
single-use browser-bound login attempts, explicit migrations, controlled seeding,
Cognito code exchange/access-token verification and current-session logout.
Controlled provider and disposable PostgreSQL checks verify identity binding,
current role lookup, immutable one-hour expiry, replay denial and committed
invalidation. Pure role policy and an application authorization seam now cover Viewer national-only,
Analyst/Admin all-grain and Admin-only refresh initiation/outcome/diagnostics.
Downstream spies verify fresh authorization before direct and later-page work;
Opt-in HTTP login/callback/session/logout composition now has host-only fixed-expiry
cookies, application-owned CSRF, exact origin/CORS checks and sanitized errors.
Configured construction is inert; process resources have explicit cleanup and
health remains dependency-independent. Analytical/refresh use cases and opt-in HTTP delivery are implemented with
controlled evidence. Configured-provider readiness and real browser reopening
remain separate acceptance work.
Read-only checks on October 5 verified the RDS schema and three seeded users
with their role and Cognito identity links; live login remains unverified.
The [updated auth plan](../specs/user-access/plan.md) records dated setup evidence
and the pending IAM, confidential-client and HTTP-helper work. See the
[Phase 2](../specs/user-access/tasks/phase-2.md) and
[Phase 3](../specs/user-access/tasks/phase-3.md) and
[Phase 4 checkpoints](../specs/user-access/tasks/phase-4.md), plus the
[HTTP contract](../specs/user-access/http-contract.md); ADR-0046/0047 remain
proposed integration/tooling records.

Connector implementation has started with pure, bounded per-grain modeling,
provenance-preserving merge and quality accounting in `domain/refresh.py`.
The local Parquet adapters now write/replay raw evidence, build date-partitioned
candidates and verify modeled rows and ledgers against source and prior-generation
evidence. Hash-addressed local files and persisted manifests are a test/staging
implementation; S3 remains the accepted authoritative store. The bounded EIA
source adapter is implemented with controlled HTTP transports, sanitization and
Parquet replay checks. A contributor CLI now joins source, evidence, candidate
verification and bounded reports through application ports. Explicit-prior reruns
verify all inherited local dependencies before retrieval; successful candidates
are reopened before the final report. Typed budget defaults accept optional
`--config` JSON overrides; run flags override file values and the EIA key stays
environment-only ([ADR-0041](../adr/0041-connector-defaults-and-json-configuration.md)).
[ADR-0048](../adr/0048-initial-interval-connector-defaults.md) increases bounded
contributor defaults to admit the 183-day initial interval with a 1,800-second
candidate budget and separate 1,800-second S3 transfer/replay budget. Full initial
verification and measured production limits remain open.
Configuration is validated before staging/transport construction and bootstrap
owns transport cleanup. Imports, help and HTTP construction start no
connector work. These local results never activate a generation. Live retrieval
validation remains pending. Refresh authorization and durable publication now
have controlled PostgreSQL/Parquet/S3 implementation evidence. See the
[implementation tasks](../specs/data-connector/tasks.md).

The [connector flow diagrams](../specs/data-connector/diagrams.md) distinguish
the planned publication workflow from the implemented local components and
show their calling sequence.

[ADR-0037](../adr/0037-connector-initial-load-and-retention.md) selects an initial
live load for April 2–October 1, 2026 inclusive through the refresh validation
pipeline. First publication requires usable output for all three grains. Later
refreshes retain absent keys and wholly excluded routes while other valid updates
proceed; an entirely excluded refresh leaves the active generation unchanged.

The offline national, facility and generator contributor commands replay their
versioned September 2026 evidence through domain policies and an application service, with local evidence
and report adapters wired at startup. They verify per-grain processing and
arithmetic without live retrieval, product endpoints or database changes. See
the [national findings](../specs/national-data-verification/verification.md) and
[facility/generator findings](../specs/facility-generator-verification/verification.md).

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
remains a runtime proposal. Capacity, EC2 deployment storage, session mapping, and the
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
data for the model. This repository currently covers these three parts.
On October 4, the user selected a separate React/Next.js, TypeScript and
Tailwind client repository with atomic components and an existing Figma design
([ADR-0039](../adr/0039-separate-ui-client-atomic-design.md)). The
[UI handoff](ui-client/README.md) records the context; client implementation
and concrete API/session integration remain pending.

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
are accepted in ADR-0028 and ADR-0032. EC2 deployment is selected in
[ADR-0038](../adr/0038-ec2-deployment-local-development.md), replacing ECS.
Development runs locally without an EC2 instance. The user confirmed Cognito
setup and the RDS connection completed; application integration and EC2
deployment configuration remain open. Refresh coordination, SQL isolation runtime
and availability target remain undecided.
Query worker/process counts are separate from API replicas. ADR-0013 accepts
one analytical query at a time initially, retryable busy responses, a 10-second
execution timeout and 1,000-row / 1-MiB results with explicit truncation.
Memory/disk sizes and the separate preparation deadline require measurement.

The user requires seeded database accounts; provisioning is not yet verified.
Accepted analytical SQL includes joins, CTEs, subqueries, aggregations, and
window functions.
OAuth2 and role-based authorization remain required; ADR-0043 excludes granular
permissions, registration and Admin user management for current implementation; ADR-0017 removes required
OIDC. ADR-0018 selects Cognito User Pools with managed login and OAuth2
Authorization Code with PKCE. Setup is user-confirmed complete; token/session mapping and
essential user fields remain open; each user has exactly one role (ADR-0044). ADR-0012 targets broad DuckDB analytical features, with evidence-led exclusions.
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
(including current, nonsuperseded decisions through ADR-0038) are settled.
ADR-0030 replaces the proposed structure in ADR-0029; remaining implementation
mechanisms keep their documented proposal status.

EIA observations are modeled as analytical datasets with versioned schema
contracts, as accepted in [ADR-0002](../adr/0002-analytical-dataset-contracts.md).
The contracts define row meaning, columns, types, units, nullability, verified
keys and source mappings. Raw and validated modeled Parquet live in S3;
DuckDB exposes authorized modeled data under stable SQL names. Bounded September 2026 verification contracts are implemented for all three
grains; historical schemas remain unverified. Operational entities have separate persistence.
The [integrity design](../specs/outage-explorer-backend/plan.md#duplicate-prevention-and-data-integrity)
records accepted invalid-row exclusion, identical-duplicate collapse and
latest-valid-value replacement (ADR-0023/0024). Required fields follow API
documentation, falling back to consistently recurring and identifying source
attributes. For national same-date conflicts within one retrieval, the last
valid record in recorded source order wins under
[ADR-0034](../adr/0034-last-national-record-wins.md); preserve source evidence
and its order for replay. ADR-0036 extends this fallback to facility/date and
facility/generator/date keys in the detail verification contracts. Historical
contracts and product quality-report storage remain open.
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
ADR-0035 defines the measure as the daily share of EIA-reported nuclear capacity
out of service, including full outages and partial output reductions. Use the
reported national MW values without reconstructing the historical capacity
basis. Exact capacity-data vintage remains an evidence limitation. The bounded
[national contract v1](../specs/national-data-verification/contract.md) implements
the accepted validation rules; broader historical checks remain open. This is not a full-day
average, lost-energy, outage-duration or cause measure.
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
| Backend | **Layered Python/Flask auth/data HTTP implemented** | Python >=3.12, Flask 3.1; pinned dependencies; opt-in data delivery with controlled verification, real analytical runtime still gated |
| Analytical model | **schema contracts confirmed** | See ADR-0002; source fields, keys and relationships await EIA investigation |
| Frontend | **separate repository selected; implementation pending** | React/Next.js, TypeScript, Tailwind, Figma and atomic components; see ADR-0039 and the UI handoff |
| Analytical storage | **Amazon S3 + Parquet confirmed** | Development bucket access verified; deployed-role verification pending; retention/recovery policy deferred; see ADR-0001 |
| Query engine | **DuckDB with local Parquet cache confirmed** | ADR-0007/0008; broad analytical SQL selected in ADR-0012; budgets and isolation need verification |
| Operational storage | **PostgreSQL on Amazon RDS confirmed** | ADR-0032; connection completed per user; application integration and deployed connectivity remain open; recovery-policy work deferred |
| Deployment | **one replica on EC2 confirmed** | ADR-0038; no EC2 instance needed for local development; deployment configuration and query runtime remain open |

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
  [ADR-0038 — EC2 deployment and local development](../adr/0038-ec2-deployment-local-development.md).
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
seeded users and role assignments under ADR-0043. The selected sign-in mechanism supplies verified identity; external
groups/roles do not independently confer product data access. ADR-0017 removes
the earlier OIDC-specific identity assumptions.

Cognito runs as a managed AWS service outside the EC2 application host. It owns login credentials
and token issuance; the Flask identity adapter validates access tokens, binds issuer/subject to
local users and applies PostgreSQL authorization tables. Configure seeded Cognito
accounts with public registration disabled. Application logout enforcement
and concrete OAuth client/session integration remain design work (ADR-0018).

Connector Phase 5 now implements configured S3 persistence and fresh local
recovery of complete immutable contributor graphs, including inherited evidence
and ancestor manifests. Controlled SDK/Parquet tests verify integrity and replay;
configured-bucket and deployed-role checks remain separate authorized work.
The returned exact manifest receipt does not activate a backend generation or
persist refresh outcomes. Under [ADR-0042](../adr/0042-connector-cli-default-s3-persistence.md),
the default connector CLI now composes local candidate creation and complete S3
persistence/readback verification. `--local-only` preserves AWS-independent
creation. S3 configuration is checked before EIA; persistence failures preserve
local artifacts and return a failed durable outcome for explicit retry.


Phase 6 implements injected bounded scheduling in `application/ports/connector_workers.py`
and `infrastructure/connector_workers.py`. Canonical endpoint page consumption remains ordered;
independent collection/evidence and S3 dependency PUT/GET operations can overlap
with separately configurable 1–3 workers (sequential defaults). Application
coordinators own reports, deterministic combined models/manifests and receipts.
Source/store/SDK accounting is shared; failure stops admission and joins workers.
Cooperative storage checks cover cancellation/deadlines during repeated replay.
Controlled overlap/equivalence and configured-bucket inherited reconstruction
passed. All six connector phases are complete: the full initial live candidate
and its exact configured-S3 source-disabled reconstruction verified successfully.
Earlier interrupted attempts remain historical evidence. Product authorization,
activation and operational outcomes remain separate backend obligations. See [resource evidence](../specs/data-connector/resource-evidence.md).


ADR-0049 adds independently configured1–3 page fetch workers within a route.
Bounded speculative windows preserve every sanitized response as an immutable
transport JSON dependency, including unused lookahead; canonical raw/page
Parquet keeps received-count offsets and one terminal. Exact graph export,
recovery and bounded-window replay verify those dependencies and their canonical
raw values. CLI/Make fetch/S3 overrides win JSON, with endpoint default1 unchanged.
Shared source bounds count all fetched rows/pages, including unused lookahead;
logical admission includes endpoint*page buffers. Modeling stays coordinated.


Data API Phase 1 adds shared v1 public projections in `domain/datasets.py`,
parser reference inspection behind an application port, and bounded canonical
encoding/type adapters in infrastructure. Portable OpenAPI and synthetic fixtures
are in `docs/specs/data-api/`; real DuckDB compatibility runs only in a controlled
test subprocess. Product catalog/preview/SQL/refresh routes and the isolated Linux
launcher remain pending. See the [Phase 1 evidence](../specs/data-api/runtime-evidence.md)
and [client handoff](../specs/data-api/client-handoff.md).

User-access Phase 5 implements fresh per-physical-connection IAM signing with
bounded credential lookup in runtime-only disposable signing subprocesses;
construction remains inert. HTTP and explicit setup share typed database modes.
Optional confidential Cognito client authentication retains public PKCE behavior
and fixed application leases without provider renewal. Typed HTTP guards pass
credentials/current identity and parsed inputs explicitly; protected application
use cases still independently check session validity and current roles. Controlled
PostgreSQL/provider/persistent-browser acceptance is available independently of
connector, analytical data and the separate UI. The required real-provider login,
logout and browser gate remains open; see [verification](../specs/user-access/verification.md).


## Data API HTTP integration

Phase 6 registers strict catalog, preview, query submission/paging and durable
refresh admission/latest/by-ID routes when `OUTAGE_DATA_HTTP_ENABLED=true`.
Application use cases enforce current roles and retained ownership; shared
transport adds exact Origin/CSRF, credentialed CORS, no-store and safe errors.
The factory starts no refresh, cleanup thread, migration, SDK or database query.

Bootstrap can accept reviewed `DataHttpResources` with explicit start/close hooks,
resource bounds and evidence reference. With none, analytical ports fail closed;
catalog and durable refresh remain independent. API shutdown never closes the
independent refresh worker. Controlled overlap/restart/retention tests establish
application behavior, not OS isolation or measured production capacity. T1.7
validation belongs to the user and was skipped by instruction.
