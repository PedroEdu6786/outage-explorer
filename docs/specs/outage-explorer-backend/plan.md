# Plan: Outage Explorer data and backend
> Status: current implementation map; deployment and full acceptance remain open · Slug: outage-explorer-backend · Spec: ./spec.md

This living plan replaces obsolete implementation proposals with the code now in
this repository. It does not alter historical ADRs, mark all acceptance criteria
complete or authorize runtime changes. Detailed feature plans/checkpoints remain
the evidence sources linked below.

## Approach

Use the accepted layer-first Python/Flask monolith (ADR-0030), one backend replica,
PostgreSQL on RDS (ADR-0032), Cognito Authorization Code with PKCE (ADR-0018), S3
resource Parquet and isolated DuckDB analytical execution. EC2 is the deployment
target; local development needs no EC2 instance (ADR-0038). No microservice split,
new persistence stack or distributed broker is selected.

Concrete adapters are injected in `bootstrap.py`. Domain owns pure policies;
application owns use cases and authorization; infrastructure owns I/O; entrypoints
translate transport. Follow [AGENTS.md](../../../AGENTS.md) and the
[structure guide](../../context/code-structure.md). HTTPX, PyArrow, PyJWT,
cryptography, SQLGlot, DuckDB, Psycopg and Alembic are declared dependencies in
`pyproject.toml`; Authlib and `joserfc` were removed as unused.

## Components affected

| Area | Current implementation | Evidence and remaining scope |
| --- | --- | --- |
| Connector/model | Bounded EIA pages, pure selection/merge, three unified resource files | [Connector plan](../data-connector/plan.md); historical source completeness remains bounded by evidence |
| Persistence | Conditional S3 writes, exact readback, explicit retry/recovery receipts | [Refresh-persistence checkpoints](../refresh-persistence/tasks.md); receipts do not publish |
| Identity/policy | Seeded PostgreSQL users/roles, fixed sessions, Cognito verification, application authorization | [User-access plan](../user-access/plan.md) and [verification](../user-access/verification.md); user-accepted web auth is distinct from complete live-case evidence |
| Catalog/preview/SQL | Seven opt-in data operations, pinned inputs, isolated inspection/execution, finite continuations | [Data API plan](../data-api/plan.md), [HTTP contract](../data-api/http-contract.md), [runtime evidence](../data-api/runtime-evidence.md) |
| Refresh | Frozen admission, independent lease-owning worker, fenced atomic publication/recovery | [Refresh execution](../../../src/outage_explorer/application/services/refresh_execution.py), ADR-0051/0052 |
| Delivery | Backend setup, tests, recorded findings; separate implemented web client | [Local setup](../../development/local-setup.md), [challenge findings](../../challenge/README.md), [UI handoff](../../context/ui-client/README.md) |
| Deployment | One EC2 backend replica selected | Ingress/TLS, supervision, provisioning and measured production capacity remain open |

## Data model changes

Exactly three unified Parquet resources are durable per generation (ADR-0060):
national, facilities and generators. Each includes original numeric strings,
units, natural identity, private provenance and exact calculation evidence.
Analytical views expose only public columns. Raw/pages/dispositions/ledgers are
bounded transient candidate inputs; there is no durable supporting graph,
S3 manifest, daily modeled partition layout or second public-only file set.

Physical S3 keys are
`<configured-prefix>generations/<generation-id>/{national,facilities,generators}.parquet`
(ADR-0061). Local storage uses content hashes. PostgreSQL owns publication
identity, exact descriptors, active pointer, refresh status and quality. Legacy
manifest-format publications fail closed without conversion/reset (ADR-0062).

Public dataset/SQL names are `national`, `facilities`, `generators`. Natural keys
are date, date/facility and date/facility/generator. The national public columns
include both calculated and source percentages; no separate fleet metric relation
is required. Public schema and source contracts are in
[domain datasets](../../../src/outage_explorer/domain/datasets.py),
[national verification](../national-data-verification/contract.md) and
[detail verification](../facility-generator-verification/verification.md).
Historical contract guarantees and capacity-data vintage remain evidence limits.

## Duplicate prevention and data integrity

Invalid rows are excluded with visible quality counts. Identical duplicates
collapse; within one retrieval, the last valid source observation wins under
ADR-0034/0036. Retained rows preserve original provenance and calculation evidence.
Complete route counts use the shared domain eligibility policy.

Initial loading uses April 2–October 1, 2026 inclusive and requires usable output
in every grain (ADR-0037). Later refreshes preserve invalid replacements' prior
valid rows, absent keys and wholly excluded routes while other valid changes
proceed. An entirely excluded refresh retains the active generation. Empty
required routes and failed retrieval/storage are failures, not retention success.
No interval deletion or mandatory seeded analytical base is selected.

The fleet metric uses reported national outage/capacity in MW, preserves exact
arithmetic and presents percentages to two decimals with halfway-up rounding.
It includes partial reductions and is not duration, lost energy or cause.
Reconciliation and the three real findings have recorded inputs and commands in
[challenge evidence](../../challenge/README.md). Do not equate source discrepancy
with a proven cause or silently replace reported national totals with detail sums.

## Interfaces and contracts

### Authentication and shared authorization

Cognito supplies identity; PostgreSQL seeded issuer/subject mappings and one role
per user determine permissions. Viewer is national-only; Analyst/Admin can read
all grains; only Admin can initiate/read refresh. No registration, Admin user
management, per-user grants or row/column authorization is in scope (ADR-0043/0044).

The implemented HTTPX/PyJWT adapter verifies access tokens and bounded JWKS
rotation, supports public/confidential PKCE and discards provider tokens. Sessions
are opaque, digest-backed, fixed one-hour leases by default without automatic
renewal. Logout invalidates only the current session. Browser-bound attempts are
single-use; expired attempts are reclaimed transactionally before admission caps.
Application use cases recheck current roles before analytical inputs and on pages.

Cookie/Origin/CSRF/CORS and sanitized errors follow the
[user-access contract](../user-access/http-contract.md). IAM signing on each new
physical PostgreSQL connection, migrations, typed configuration and bounded pools
are implemented. No connection may cross a process fork. See the dated auth
verification for user acceptance and still-open comprehensive live-persona cases.

### Catalog, previews and SQL

The implemented [contract](../data-api/http-contract.md) selects:

- `GET /api/datasets`: authorized catalog metadata.
- `GET /api/datasets/{dataset}/preview`: date-only filters and snapshot cursor.
- `POST /api/query`: one SQL execution; `page` and `page_size` are query parameters.
- `GET /api/query?query_id=...&page=...`: another page of that retained execution.
- `POST /api/refresh`, `GET /api/refresh/latest`, `GET /api/refresh/{run_id}`:
  Admin admission and durable outcomes.

Page size defaults to 100 and is at most 500. Preview sequences expire 60 seconds
after creation; SQL results expire 60 seconds after completion, without renewal
(ADR-0059 supersedes the earlier 15-minute lifetimes). Query metadata is bounded
in memory; private result spools and reader leases preserve one execution's
sequence. No SQL pagination clauses or silent reruns are allowed. Process/store
loss or expiry returns explicit unavailability. SQL output caps remain 1,000 rows
or 1 MiB with truncation. See OpenAPI for implemented error codes.

SQL reference inspection runs in a bounded separate subprocess (ADR-0054).
Authentication precedes inspection and role authorization precedes analytical
inputs. Preparation resolves exact PostgreSQL descriptors, downloads permitted
files into a verified pinned disk cache and stages only approved inputs. DuckDB
views project public columns over exact unified resource files. Workers receive
no operational database or cloud credentials and no unrestricted cache mount.
No API-process parser/engine fallback or direct S3 query fallback is selected.

### Refresh and publication

HTTP admission freezes the configured inclusive date range and resource settings
(ADR-0051); callers supply no date overrides. An independent worker claims and
renews database-time ownership, restores the pinned base, models/verifies all
grains, persists/reads back exact files, then publishes descriptors/quality and
active pointer atomically. Previous data remains available during work and on
failure; existing analytical sequences keep their pinned generation.

Recovery reconciles committed publication after worker loss and fences stale
owners. Healthy workers survive API-only restarts. Interrupted unpublished runs
require explicit Admin retry, not automatic source work (ADR-0052). No review
queue, second publish action or reset CLI exists. Explicit connector persistence
retry is separate from publication authority. CLI defaults to S3 unless
`--local-only`; S3 configuration is validated before source work (ADR-0041/0042).

### Runtime lifecycle and deployment

Imports and factories start no services. Explicit startup owns analytical recovery,
cleanup, parser/execution admission, private staged files and worker termination.
Ownership is recorded before allocation; unresolved termination prevents capacity
or pin release. Linux quota-disk checks and exact profile/image/evidence identity
are implemented; actual containment/capacity claims require matching host evidence.

ADR-0053 defines one threaded API owner, one analytical slot and independent
refresh for local acceptance. ADR-0055 permits scoped local preview/SQL readiness
with refresh idle. ADR-0056 records subsequent user-directed activation and the
instruction to stop external validation. Keep unperformed checks as evidence
gaps; do not invent a new activation blocker or claim full production acceptance.
Final EC2 topology, provisioning, ingress/TLS, backup/recovery policy and complete
capacity/overlap measurements remain open. Multiple backend replicas, generic
CRUD/service hierarchies, scheduling and cross-execution query caching are deferred.

## Verification strategy and open work

Feature checkpoints record controlled source/model, role, continuation, persistence,
publication/recovery and lifecycle tests. The runtime evidence map distinguishes
portable/mock tests, actual host reports and open full acceptance. Static checks
and liveness never establish production isolation. Dated evidence is not rewritten
by this plan.

- Run documented Ruff, mypy, architecture and relevant behavioral checks for code
  changes. Run PostgreSQL tests only against an explicit disposable local database.
  The five review-added login cleanup cases remain unexecuted without that DSN.
- Preserve live-user acceptance already recorded; detailed missing live cases and
  original high-water/spill, S3 performance and API/refresh overlap evidence stay
  open. No further service/browser validation is authorized by documentation.
- Preserve challenge acceptance criteria and delivery obligations. A clean-checkout
  rehearsal and complete integrated/production acceptance are separate from code
  presence and historical test results.
- Broader historical source contracts/completeness, general snapshot deletion and
  infrastructure backup/recovery policy remain open. Current code and resource
  defaults do not establish measured production budgets.
