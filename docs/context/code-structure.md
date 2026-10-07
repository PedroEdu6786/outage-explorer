# Layered Flask monolith structure

Status: **accepted structure**, [ADR-0030](../adr/0030-layered-flask-monolith.md).

Refresh persistence is implemented under accepted
[ADR-0060](../adr/0060-persist-only-three-resource-files-per-generation.md).
The application ports describe exactly three resource files, baseline identity,
interval, versions and bounded transient quality; Parquet infrastructure preserves
private provenance/source strings and exact arithmetic in the unified physical
codec. Analytical views project only existing public columns. PostgreSQL publication
owns exact file descriptors; S3 verifies every file by bounded full readback.
Supporting graph writes and duplicate public files have been removed through
[phase checkpoints](../specs/refresh-persistence/tasks.md). Existing legacy bases fail closed.
[ADR-0061](../adr/0061-generation-prefixed-resource-object-keys.md) selects exact
generation-prefixed physical keys, distinct from local checksum identities;
[ADR-0062](../adr/0062-fail-closed-legacy-publication-layout.md) fixes fail-closed
behavior for an existing manifest-format publication.

Phase 1 now supplies `CreateResourceCandidate`, `ParquetResourceBuilder` and
`LocalConnectorEvidence.collect_resources` for explicit local composition.
The collector validates bounded copied input and discards page/transport metadata;
the builder reuses pure merge policies and the existing exact codec, streams prior
resource files, writes three unified files and compares them with the transient
merge before releasing inputs. Both bounded partition facts and streaming candidate
eligibility use `domain.refresh.refresh_facts_from_counts` after aggregating complete
route counts; the adapter maps those facts to candidate/retention outcomes.
Shared CLI/refresh/bootstrap composition now uses this pipeline. No new candidate writes both layouts
and no graph conversion or fallback is implemented. New behavior is covered in
`tests/integration/test_resource_candidates.py` and pure connector service tests.
The health scaffold and offline national/facility/generator verification are implemented; product
data HTTP delivery is implemented with explicit enablement and controlled
verification; actual analytical runtime readiness remains separate. This guide governs application code and refactors;
[AGENTS.md](../../AGENTS.md) makes its rules discoverable to agents.

Phase 2 adds explicitly injected `PersistResourceArtifacts`,
`RecoverResourceArtifacts` and `S3ResourceStore`. Exact physical descriptors carry
the generation-prefixed keys, while local files retain checksum identity. Durable
receipts copy admitted interval, versions and baseline identity. Conditional writes
and full streamed readback share locked transfer bounds; recovery reserves missing
file bytes, verifies schema/rows, joins workers and cleans only recovery-owned files
on failure. `ResourceWorkerSettings` defaults new S3 consumers to three workers;
shared CLI/refresh/bootstrap use these settings. Controlled tests live in
`tests/integration/test_resource_artifacts.py`; publication, exact analytical cache
reads and the composed end-to-end flow passed the phase-4 checkpoint.

Under [ADR-0051](../adr/0051-configured-http-refresh-range.md), HTTP refresh
admission resolves a configured inclusive interval and records it for background
execution; routes accept no caller date overrides. Configuration wiring belongs
in bootstrap/settings and admission orchestration in the application layer.

[ADR-0052](../adr/0052-interrupted-refresh-recovery.md) requires publication
reconciliation before marking lost-worker runs interrupted, followed by explicit
Admin retry for unpublished work. Supervision/recovery belongs outside HTTP
request lifetimes; application ports own the durable transitions.

Operational storage uses [PostgreSQL on Amazon RDS](../adr/0032-postgresql-on-rds.md).
Use PostgreSQL for local development and integration tests as well; pure unit
tests may substitute application ports with fakes. User-access Phase 1 now has
PostgreSQL repositories, explicit Alembic migrations and controlled local seeding
using Psycopg 3. Disposable PostgreSQL 18.6 tests verify storage/setup. October 5
read-only checks verified Aurora PostgreSQL 17.9, the application schema and three
seeded identity/role links; live login and pooled IAM signing remain pending.
The [auth plan](../specs/user-access/plan.md) separates that dated evidence from
the remaining phase 5 implementation and acceptance work. Integration and tooling
records remain proposed in ADR-0046/0047. See the
[Phase 1 checkpoint](../specs/user-access/tasks/phase-1.md).
Phase 2 adds injected login/access services, cryptographic material and bounded
Cognito access-token/JWKS adapters. Atomic attempt consumption precedes provider
exchange; sessions resolve current local roles and invalidate only their own digest.
Controlled provider and real PostgreSQL tests prove fixed expiry and committed
logout without connector access; live provider readiness remains pending. See the [Phase 2 checkpoint](../specs/user-access/tasks/phase-2.md).
Phase 3 adds trusted authorization operation/grain enums and a pure role matrix.
The access service returns a local principal and exact approved grain set only after
fresh session/role checks. Downstream harnesses verify denial before data/execution
on direct and later pages; actual SQL reference extraction, result ownership and
catalog/SQL/refresh integration remain downstream responsibilities. See the
[Phase 3 checkpoint](../specs/user-access/tasks/phase-3.md).
Phase 4 registers opt-in thin auth routes with injected login/access services,
HTTP schemas and host-only cookie/origin transport. Cryptographic CSRF checks stay
in the application/security seam. Bootstrap owns lazy process-bound PostgreSQL
and Cognito resources with explicit shutdown; imports/factories start no requests,
connections, migrations or threads. Health remains independent. The
[HTTP contract](../specs/user-access/http-contract.md) and
[Phase 4 checkpoint](../specs/user-access/tasks/phase-4.md) distinguish controlled
verification from pending browser/live-provider readiness.


Use one application organized by technical layer. Keep business policies
independent of Flask and storage through small application-owned interfaces.
This provides a simple layered layout with testable dependencies. HTTP,
background refresh, and verification commands reuse the same use cases.

## Directory layout

The HTTP entry point also serves public Swagger UI at `/api/docs` and the full
OpenAPI 3.1 contract at `/api/openapi.json`. Its packaged transport contract lives
in `entrypoints/http/openapi.json`; locally served assets come from the pinned
flask-swagger-ui dependency. Documentation requires no external services and does
not enable optional auth/data operations. Route coverage and data-contract parity
tests guard its coverage; the architecture check admits only the documentation
module's JSON and Swagger rendering imports.

```text
src/outage_explorer/
  bootstrap.py                  # concrete wiring and process composition
  settings.py                   # environment/configuration at startup
  domain/
    access.py                   # permission rules and policy types
    datasets.py                 # schema and generation contracts
    validation.py               # observation validity and exclusion rules
    refresh.py                  # bounded connector modeling/merge and provenance
    metrics.py                  # national offline share
  application/
    services/
      access.py                 # principal/session resolution and logout
      catalog.py                # permitted dataset descriptions
      preview.py                # authorized snapshot-bound browsing
      queries.py                # inspect, authorize, prepare, execute, page
      refresh.py                # admission, execution, outcome, publication
      evidence.py               # reconciliation and reproducible findings
    ports/                      # contracts for external capabilities
    dto.py                      # transport-independent inputs and results
    errors.py                   # application failures, without HTTP codes
  infrastructure/
    postgresql/                     # operational repositories and transactions
    cognito/                    # trusted access-token validation
    eia/                        # upstream metadata/pages and HTTP retries
    parquet/                    # bounded read/write and model transformations
    s3/                         # immutable exact resource transfers/readback
    sql_validation/             # parser-specific AST inspection
    duckdb/                     # engine setup and execution in worker only
    local_cache/                # downloads, checksums, pinning, eviction
    query_results/              # expiring metadata and bounded retained output
    worker_runtime/             # sandbox launch, limits, termination, reaping
  entrypoints/
    http/
      app.py                    # create_app and Blueprint registration
      routes/                   # access, datasets, queries, refresh
      schemas.py                # HTTP validation and serialization
      errors.py                 # application errors to HTTP responses
    cli.py                      # controlled operations and verification
    refresh_worker.py           # supervised refresh entry point
    query_worker.py             # restricted analytical entry point
tests/
  unit/
  integration/
  architecture/
  acceptance/
```

Names illustrate ownership; create files only when behavior needs them.
Split an oversized file into a package within its existing layer. Group related
features within each layer as needed; do not introduce a second feature-first
hierarchy alongside this one. No framework package, ORM, or interface base class
is required merely because a directory exists.

## Dependency matrix

Rows describe the importing code. This matrix concerns internal imports;
external I/O libraries belong in infrastructure or the relevant entry point.

| From | Allowed internal dependencies | Forbidden dependencies |
| --- | --- | --- |
| `domain` | Domain types/functions; standard library without I/O | Application, infrastructure, entry points, bootstrap, runtime settings |
| `application` | Domain, application DTOs/errors/ports and explicit services | Infrastructure, entry points, bootstrap, runtime settings |
| `infrastructure` | Domain, application ports/DTOs/errors; cohesive infrastructure helpers | Entry points, bootstrap, application service orchestration |
| `entrypoints` handlers | Application services/DTOs/errors; entry-point schemas/helpers | Concrete infrastructure, direct domain policy execution, runtime wiring |
| `bootstrap` | All layers and settings for construction only | Business policy or request orchestration |

Database drivers and standard-library file/network calls are infrastructure: an import
check alone cannot prove a function is pure. No relative import, dynamic import,
or re-export may circumvent a forbidden dependency.

A process startup wrapper may call a dedicated bootstrap function. For example,
the query-worker executable calls `build_query_worker`, which constructs only
its restricted execution dependencies. This is a narrow startup exception, not
permission for handlers to use bootstrap as a service locator. The same applies
to starting HTTP, CLI, and refresh processes. Factories and imports do not start
jobs or perform source retrieval.

## Responsibilities and examples

| Change | Put it here | Keep out of |
| --- | --- | --- |
| Validate `page_size` HTTP input and serialize JSON | HTTP schema/route | Domain and repositories |
| Authorize preview and choose a pinned generation | Application preview service | Route decorators as sole enforcement |
| Decide whether positive capacity permits an offline-share calculation | Domain metric/validation policy | DuckDB SQL or HTTP handlers as the sole policy definition |
| Verify a Cognito signature and translate verified claims | Cognito adapter | Domain and HTTP route body |
| Read application roles or commit publication metadata | PostgreSQL adapter through application ports | Flask routes and SQL worker |
| Extract referenced datasets from a SQLGlot tree | SQL-validation adapter | Application code importing SQLGlot AST classes |
| Download verified Parquet and manage cache pins | Cache/S3 adapters | Domain and user-controlled filesystem paths |

An HTTP preview follows this runtime flow:

```text
HTTP schema/route
  → preview application service
    → session and access checks
    → published-generation and input ports
    → bounded execution port
  ← plain application result
← JSON response
```

The application calls interfaces; bootstrap supplies concrete adapters. Source
imports therefore stay inward even when execution calls outward to storage.
This use of a Flask service layer is supported by
[Cosmic Python's worked example](https://www.cosmicpython.com/book/chapter_04_service_layer).
The concrete package layout and rules above are this project's design.

Business checks must also run when the use case is invoked by a CLI or worker.
A refresh worker executes an admitted run under a trusted internal identity;
it does not accept a caller-supplied role string as authorization. Keep pure
functions lightweight and use narrow protocols for meaningful external seams.
Avoid a command bus or one repository per analytical row type.

## State and execution rules

[ADR-0053](../adr/0053-local-single-owner-analytical-acceptance.md) accepts a single
API serving process with threads, one analytical slot and independently supervised
refresh for local endpoint acceptance. Process-owned continuations remain ephemeral;
reloader/fork/multiple-process rejection remains required. This does not settle
EC2 topology or grant runtime startup/enablement permission.

[ADR-0054](../adr/0054-bounded-subprocess-sql-inspection.md) accepts subprocess
SQL inspection behind the application port, with concrete launch/transport in
infrastructure and wiring in bootstrap. Admission, time/CPU/memory/output and
termination must be bounded before SQL enablement; no API-process fallback.
The bounded Linux subprocess implementation and native owner-loss/resource checks
are delivered. The user accepted initial 4-second wall, 1 CPU-second, 256-MiB
address-space and 1-second termination caps; full parser/report readiness remains
pending. Bootstrap supplies no API-process parsing fallback.

[ADR-0055](../adr/0055-scoped-local-analytical-readiness.md) separates local
preview/SQL readiness with refresh idle from complete capacity evidence. Local
review retains actual-host/auth, isolation, bounds and lifecycle gates; original
full checkpoints stay open. Explicit local-scope evidence cannot satisfy generic
runtime readiness and grants no implicit activation.

[ADR-0056](../adr/0056-user-directed-local-api-activation.md) records explicit
user authorization for local activation using accepted service assumptions.
Additional external-service/browser checks no longer block this local startup;
normal authorization, isolation, bounded execution and cleanup remain enforced.

Under [ADR-0043](../adr/0043-seeded-users-and-role-only-access.md), seed local
users, roles and assignments with essential Cognito identity linkage. Keep
credentials in Cognito. Registration and Admin user management are excluded
throughout implementation; access is role-only, without separate read/write/delete
permissions, per-user grants, ABAC or row/column restrictions for current scope.

Keep operational PostgreSQL on Amazon RDS (ADR-0032) separate from analytical Parquet and from ephemeral
query-ID state. PostgreSQL owns permissions, application-session state, refresh
outcomes, and the active publication reference. Query metadata stays bounded,
expiring, and in-memory; result placement remains a separate implementation choice.

The application defines transaction boundaries; infrastructure performs the
transaction through a port. Use bounded connection pools and short transactions;
do not hold PostgreSQL writes across EIA/S3 calls or
analytical execution. Complete and verify immutable uploads before committing
the publication reference. Readers retain their selected generation.

User SQL runs behind the isolated execution port. A worker gets only authorized
inputs and enforced limits, without application secrets or operational data.
HTTP request lifetime cannot own refresh. Import-time jobs, global database
connections, and implicit worker startup in `create_app` are forbidden.

Development runs locally without an EC2 instance under
[ADR-0038](../adr/0038-ec2-deployment-local-development.md); deployment choices
do not block independent local implementation or testing.

These rules implement existing requirements. WSGI process count, worker launcher,
EC2 deployment/storage, session integration, and resource sizes still require their
own decisions and feasibility evidence. Do not treat the earlier topology
recommendation as a settled implementation contract.

## Agent change checklist and automated enforcement

Before a change, identify its layer, the affected use case, applicable ADRs,
and the behavior to verify. After the change:

1. Check added imports against the matrix, including transitive wrappers.
2. Verify authorization precedes data access on every affected entry point.
3. Test business behavior through application/domain APIs without Flask or AWS;
   use real-adapter tests where transactions, file formats, or engine behavior matter.
4. Run available checks and document unresolved runtime limitations honestly.
5. If changing an accepted boundary, record the user-authorized revision in a
   new ADR and synchronize this guide and `AGENTS.md` in the same change.

With the first application scaffold, add automated tests under
`tests/architecture/` for the forbidden import directions and startup exception,
then run them in CI. The checks must detect both absolute and relative imports;
include negative fixtures to prove they reject violations. Supplement them with
behavior tests for permissions, publication, and isolated execution: package
placement cannot prove those guarantees.

**Enforcement status:** the health scaffold, AST dependency checks and negative
fixtures in `tests/architecture/`, and CI in `.github/workflows/ci.yml` are
implemented. Checks resolve absolute/relative imports, inspect re-exports,
reject wildcard/dynamic loading patterns, constrain inner-layer external imports,
and detect module cycles. The HTTP startup exception is
`entrypoints/http/startup.py`, structurally restricted to a factory forwarding
to `bootstrap.build_http_app`. The additional `entrypoints/cli/startup.py`
exception is structurally restricted to passing `build_national_verifier()` to
the CLI command and its executable guard. `facility_startup.py` and
`generator_startup.py` have the same exact-AST restriction for their dedicated
bootstrap builders. Other modules cannot import these wrappers. Further startup wrappers require explicit checker coverage.

`GET /health` follows HTTP route → application service → clock port, with a UTC
clock adapter injected by bootstrap. There is no domain rule or persistence in
this use case, so domain/storage packages and runtime settings are created when
needed. The factory registers services without executing them. Fresh-interpreter
tests guard against import-time app construction, network/process/thread startup,
and factory-time probe execution. These checks do not establish runtime purity,
authorization, publication correctness, or analytical isolation; their behavior
tests are still required as the corresponding use cases are implemented.

Offline national verification follows CLI → application evidence service →
pure national policies and recorded-evidence/report ports. Infrastructure reads
the hashed local evidence bundle and writes deterministic JSON/Markdown.
`Fraction` is a reviewed pure dependency; CLI transport imports (`argparse`,
`sys`) are allowed only in its command module. The baseline verifier is a
contributor command, with no product-data authorization claim. See its
[contract](../specs/national-data-verification/contract.md).

The connector foundation in `domain/refresh.py` reuses the observation policies
for explicitly bounded groups with caller-supplied limits. It models source
positions, preserves origin references during valid replacement/invalid retention,
and reports quality and transformation eligibility. Under
[ADR-0037](../adr/0037-connector-initial-load-and-retention.md), absent keys retain
their prior rows, wholly excluded routes retain prior data during refresh, and
initial loading requires usable output in all three grains. It accepts sanitized input and
performs no I/O, authorization or publication.

`application/ports/artifacts.py` and `candidates.py` define exact three-resource
contracts without Arrow types. `ParquetResourceBuilder` evaluates bounded transient
source input and merges sorted prior resource rows, writes one unified file per
grain and compares its exact values/quality before releasing transient inputs.
Private provenance and original numeric strings remain in the physical codec;
DuckDB views project only the existing public columns. There is no graph-writing
candidate or manifest serializer. Bounded source adapters and `collect_resources`
validate canonical page/source order and lookahead without persisting supporting
artifacts. Finding 001 and source anomaly fixtures remain in repository tests.

`bootstrap.execute_connector` composes local source/candidate/report ports;
`execute_connector_to_s3` validates S3 configuration before source work and uses
`PersistResourceArtifacts`. Explicit retry takes a bounded local report path;
recovery takes a bounded exact receipt and reads only the three supplied objects.
Default S3 concurrency is 3 (configurable1–3), sharing aggregate transfer/staging
bounds. Every admitted worker joins before cleanup. Reports/receipts are local
transport metadata, with no publication authority.

`RefreshExecution` restores the admitted resource base, validates candidate and
receipt identity/coverage, and atomically publishes exact descriptors and quality
through `PostgresqlResourcePublicationStore`. Its per-run composition checks the
lease during I/O and uses separate frozen candidate/persistence deadlines.
`VerifiedResourceCache` downloads only the approved dataset file. Local immutable
storage streams incoming chunks to a temporary file while counting and hashing,
checks exact identity and session admission bounds, then links it atomically.
Failed transfers remove their temporary file; independent source reads remain
outside the admission lock. Worker input checksums also use bounded reads.
Analytical workers scan public-only views over the exact staged resource. Factories/imports
remain inert and API shutdown never owns the independent refresh worker.
Legacy publication rows remain immutable and fail closed under ADR-0062.

Facility and generator verification reuse `domain/observations.py` (national's
API remains in `domain/national.py`) and the shared evidence service/adapters,
with explicit grain contracts and entity/date coverage. Their separate commands
remain offline contributor tools. The source-total difference is reported as
unresolved evidence; this does not establish live pagination completeness or
product authorization. See the [detail contract](../specs/facility-generator-verification/contract.md).

The earlier connector graph implementation and its authorized historical live
measurements are recorded in the [resource evidence](../specs/data-connector/resource-evidence.md).
They describe the superseded layout; current resource persistence claims rely on
the refresh-persistence controlled checkpoints, not those earlier measurements.

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

User-access Phase 5 now adds shared explicit DSN/local/password/IAM settings,
bounded runtime-only IAM signing for each physical PostgreSQL connection,
confidential Cognito HTTP Basic token exchange with PKCE, and reusable typed HTTP
authentication/CSRF/query-and-JSON guards. These guards pass values explicitly and
do not replace fresh authorization in application use cases. Controlled acceptance
uses disposable PostgreSQL, provider transports and persistent Chromium profiles;
CI provisions its database/browser dependencies without cloud credentials.
See the [operator runbook](../specs/user-access/setup.md) and
[verification record](../specs/user-access/verification.md). Real managed-login
and browser validation remain pending, so Phase 5's live checkpoint stays open.

Data API Phase 3 adds admitted-run execution and quality mapping in
`application/services/refresh_execution.py` and `application/refresh_outcomes.py`.
A separate explicit `entrypoints/refresh_worker_startup.py` executable composes
per-run EIA/Parquet/S3 dependencies in bootstrap, commits ownership before source
work, renews database-time leases independently, and closes its resources.
`application/services/refresh_recovery.py` reuses serialized PostgreSQL history
reconciliation; interrupted unpublished work requires explicit Admin retry.
The worker restores and replays the pinned base, verifies all-grain identity,
persists/replays the full durable graph before publication, and reports retained
all-excluded input without moving the pointer. Exact-AST startup checks constrain
the new wrapper. Inner layers permit only the pure `json.dumps` status encoder
and the `contextlib.AbstractContextManager` type contract, with negative fixtures
rejecting file decoding and execution helpers. Controlled process restart,
PostgreSQL/Parquet/S3 and commit-loss evidence is recorded in the
[Phase 3 checkpoint](../specs/data-api/tasks/phase-3.md); product HTTP and actual
preview/SQL continuations remain downstream work.


Data API Phase 4 adds application catalog/preview services, published-input and
isolated-execution ports, a modeled-only verified projection cache, and bounded
snapshot cursor metadata. Workers receive exact public-column Parquet projections;
raw/provenance dependencies never enter the analytical input grant. Preview
metadata holds generation pins until fixed expiry and supervised cleanup; active
reads and unproven reaping prevent premature pin release. Controlled worker
fixtures exercise real DuckDB in a separate process, without asserting OS
isolation. The product launcher remains fail-closed until the reviewed T1.7
runtime is supplied. HTTP integration and explicit runtime lifecycle composition
remain Phase 6; see the [Phase 4 checkpoint](../specs/data-api/tasks/phase-4.md).


Data API Phase 5 adds `application/services/queries.py`, explicit reference-free
expression authorization, bounded process-owned query metadata/private spools,
reader leases and autonomous cleanup lifecycle. Query output is materialized
once through the isolated port, then arbitrary/revisited numbered pages read
immutable row offsets with current roles and original-owner checks. SQL input
pins release after confirmed reaping; query metadata never enters PostgreSQL.
Bootstrap constructs inert lifecycle resources for explicit start/close. This
store rejects incompatible multiple-process ownership without selecting the
final WSGI topology. Controlled integration evidence is in the
[Phase 5 checkpoint](../specs/data-api/tasks/phase-5.md); product execution stays
fail-closed pending T1.7 Linux launcher evidence and HTTP remains Phase 6.


### Data HTTP integration (Phase 6)

`entrypoints/http/data_schemas.py` owns strict bounded transport parsing;
`data_services.py` groups already-constructed application services for the inert
factory. Dataset/query/refresh routes invoke those services. Public catalog and
refresh projections remain in application code; the latter decodes bounded
operational JSON using a narrowly allowed pure `json.loads` import. Architecture
negative fixtures still reject JSON file readers there.

Bootstrap controls `OUTAGE_DATA_HTTP_ENABLED`, configured refresh dates and
optional supervisor-supplied `DataHttpResources`. Analytical ports fail closed
when no reviewed resources are supplied. Process lifecycle extensions are explicit:
the factory never invokes start, and API close does not stop refresh supervision.
Migration 0003 records actual start/finish times; historical unknown values remain
null. Verified modeled partitions supply reported refresh coverage.
See the [Phase 6 checkpoint](../specs/data-api/tasks/phase-6.md) and
[evidence map](../specs/data-api/runtime-evidence.md).

Analytical-runtime Phase 3 adds inert forwarding ports built in `bootstrap.py`
and explicit ownership in `infrastructure/worker_runtime/supervisor.py`.
`QueryCleanup` runs recovery and preview expiry before result expiry; strong
leases preserve active readers and unresolved execution. The exact-AST
`entrypoints/http/analytical_startup.py` exception only passes the dedicated
bootstrap callable to its argument parser. Imports, HTTP factories and help
perform no runtime startup. One local owner, explicit lifecycle and ephemeral
restart loss are adapter constraints; real quota storage/readiness and deployment
remain open. No refresh ownership is added to analytical HTTP shutdown.

The analytical corrective storage pass implements native Linux `quota-disk` in
`infrastructure/worker_runtime/quota.py`: a separately provisioned finite ext4
filesystem, strict mount/identity/capacity checks, private request directories and
one retained filesystem lock. Bootstrap probes these prerequisites only at
explicit start. The ownership ledger persists spill paths and preparing/creating/
removed phases; cleanup retains ownership until confirmed worker removal and
complete reclamation. Docker Desktop is unsupported by this backend. Controlled
verification is complete; Linux host provisioning, real runtime enforcement and
reviewed readiness remain open. See the
[storage checklist](../../infrastructure/analytical-worker/README.md).

The committed `worker.json` record is authoritative during analytical restart.
After acquiring the exclusive owner lock, the ledger discards an abandoned
private regular `worker.partial` file; incomplete writes never authorize a worker
transition. A committed record still requires normal worker reconciliation before
new admission, and invalid temporary file types or permissions fail closed.

Input preparation plans a fresh staging path and commits its `preparing` intent,
including the exact spill path when configured, before creating either directory
or copying input bytes. Recovery accepts a missing staging directory in that
phase and reclaims only recorded paths. Copying retains the existing size,
checksum, source-identity, row-count, deadline and sealing checks. Ordinary cleanup
also handles a planned directory that was never created or was already reclaimed.

The DuckDB query adapter translates specific binding, syntax, type and value
errors during submitted SQL execution or row fetching into safe `invalid_sql`
responses. Engine out-of-memory errors become `query_resource_limit`. Internal
view setup, I/O and unexpected engine failures retain unavailable responses;
engine diagnostic text never crosses the worker protocol. Connections close on
each path, and application cleanup still proves worker termination before
releasing execution capacity or retaining a successful result.
