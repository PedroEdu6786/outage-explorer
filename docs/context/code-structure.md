# Code structure

Outage Explorer is one **layered Python/Flask monolith**, selected in
[ADR-0030](../adr/0030-layered-flask-monolith.md). HTTP, CLI, refresh and analytical
workers share the same backend codebase. Organize code by technical layer.

Use this page to decide **where code belongs and what it may depend on**.
For system behavior, see the [architecture overview](architecture.md) and
[module/endpoint diagrams](module-diagrams.md). For installation and commands,
use the [developer setup guide](../development/fresh-machine.md).
Implementation history and acceptance evidence live in the linked specifications,
ADRs and devlogs rather than in this directory guide.

## Directory layout

| Location | Responsibility | Examples |
| --- | --- | --- |
| `domain/` | Pure business rules and types; no I/O. | Roles, observation identity, retention and calculations. |
| `application/services/` | Use cases, authorization and transaction orchestration. | Login, preview, SQL, refresh and publication coordination. |
| `application/ports/` | Interfaces the application needs from external capabilities. | Published inputs, storage, SQL inspection and execution. |
| `infrastructure/` | Concrete implementations of those interfaces. | PostgreSQL, Cognito, EIA, S3, Parquet, cache and worker runtime. |
| `entrypoints/` | Translate HTTP, CLI and worker inputs/outputs. | Flask routes, command arguments and worker protocols. |
| `bootstrap.py` | Construct dependencies and inject them at explicit startup. | Connect a use case to PostgreSQL/S3/worker adapters. |
| `configuration/` | Read and validate startup configuration by consumer. | Connector, artifact, S3, database, auth, refresh and analytical settings. |
| `settings.py` | Preserve existing configuration imports while callers migrate. | Re-exports only; no validation or I/O. |

Selected existing files and packages:

```text
src/outage_explorer/
  bootstrap.py
  settings.py
  configuration/             # focused startup settings and loaders
  domain/
    access.py                  # roles and access policy
    datasets.py                # public dataset contracts
    national.py                # national observation/calculation rules
    observations.py            # facility/generator observation rules
    refresh.py                 # merge, retention and quality policies
  application/
    services/
      login.py                 # login orchestration
      access.py                # session/principal resolution and logout
      connector.py             # build a resource candidate
      resource_artifacts.py    # persist/recover exact resource files
      catalog.py               # authorized dataset descriptions
      preview.py               # approved snapshot reads and input lifecycle
      queries.py               # inspect, authorize and execute SQL once
      refresh.py               # refresh admission
      refresh_execution.py     # coordinate run lifecycle and final publication
      refresh_worker.py        # recover, claim and lease one run per tick
      refresh_baseline.py      # restore and verify the pinned generation
      refresh_candidate.py     # build candidates and validate their outcomes
      refresh_publication.py   # persist resources and prepare publication metadata
      refresh_recovery.py      # reconcile interrupted work
    pagination/                # reusable cursor and numbered page contracts
    ports/                     # application-owned interfaces
  infrastructure/
    postgresql/                # operational repositories and transactions
    cognito/                   # provider exchange/token verification
    eia/                       # bounded source retrieval
    parquet/                   # physical schemas, reads and writes
    s3/                        # exact resource transfer and readback
    sql_validation/            # bounded parser subprocess and inspection
    duckdb/                    # query engine adapter, used in workers
    local_cache/               # verified downloads, pins and eviction
    query_results/             # retained output and expiring metadata
    worker_runtime/            # isolation, quotas, ownership and cleanup
  entrypoints/
    http/
      app.py                   # register injected services and routes
      data_services.py         # injected HTTP service bundle
      requests/                # auth, data and query decoding/validation
      responses/               # shared and endpoint response DTOs
      transport/               # guards, cookies, errors and preflight
      routes/                  # health, auth, datasets, queries, refresh, docs
      openapi.json             # packaged HTTP contract
      analytical_startup.py    # explicit analytical API startup
    cli/                       # connector, setup, offline verification and analytical CLI parsing
    refresh_worker.py          # independent refresh worker loop
    query_worker.py            # restricted analytical worker protocol
    refresh_worker_startup.py  # refresh process composition seam
    query_worker_startup.py    # query process composition seam
```

Split an oversized module into a package **within its existing layer**. Related
features can be grouped inside each layer. Create files only when behavior needs
them; do not add a parallel `modules/<feature>/{domain,application}` hierarchy,
generic CRUD framework or repository for every analytical row type.

Within `entrypoints/http/`, `routes/` owns controllers, `requests/` owns
decoding and request DTOs, `responses/` owns public response mapping, and
`transport/` owns guards, browser cookies, errors and preflight. `app.py`,
startup files and the injected `DataServices` bundle stay at the HTTP root.
The analytical API's argument parser lives in
`entrypoints/cli/analytical_command.py`; its process startup stays in HTTP.
ADR-0092 relocates ADR-0076's exact request-model import allowances to the
`requests/` package without widening them.

For local Parquet restoration, `LocalConnectorEvidence` delegates to
`ResourceRestorer` in `infrastructure/parquet/resource_restoration.py`.
`ResourceDownload` owns one transfer's stream lifetime; `LocalParquetStore`
owns file lookup, capacity accounting and atomic installation. Baseline content
verification remains in `ParquetResourceBuilder`, supplied to restoration as a
callable. Restoration does not access the store's private locks or counters.

## Dependency matrix

Read each row as: “code in this location may import these internal modules.”
Runtime calls through a port do not permit importing its concrete implementation.

| Importing code | Allowed internal dependencies | Forbidden dependencies |
| --- | --- | --- |
| `domain` | Domain types/functions; pure standard-library operations. | Application, infrastructure, entrypoints, bootstrap and settings. |
| `application` | Domain; application services, DTOs, errors and ports. | Infrastructure, entrypoints, bootstrap and settings. |
| `infrastructure` | Domain; application ports/DTOs/errors; cohesive infrastructure helpers. | Entrypoints, bootstrap and application service orchestration. |
| `entrypoints` handlers | Application services/DTOs/errors; entrypoint schemas/helpers. | Concrete infrastructure, direct domain policy execution and runtime wiring. |
| `configuration` | Other focused configuration modules. | Application, infrastructure, entrypoints and bootstrap. |
| `settings.py` | Focused configuration modules for compatibility imports. | Validation logic and process I/O. |
| `bootstrap` | All layers and settings, for construction and injection. | Business rules and request orchestration. |

Database drivers, SDKs, engine calls and file/network I/O belong in infrastructure.
Under [ADR-0068](../adr/0068-declarative-refresh-configuration-validation.md),
`domain/refresh_configuration.py` alone may import Pydantic's model, configuration,
field and model-validator APIs for pure declarative validation. ADR-0071 also permits narrow Pydantic validation APIs in
`application/pagination/request.py` and `application/preview_request.py`.
ADR-0073 permits `BaseModel`, `ConfigDict`, `Field` and `ValidationError` in
`application/refresh_request.py`: the admission decorator injects a strict frozen
Pydantic DTO after CSRF and Admin guards. Other
domain and application dependencies retain the standard-library rule above.
Flask request context (`request`, `g`, `current_app`) stays out of domain and
application code. Relative imports, dynamic imports and re-exports must not bypass
the matrix. An allowed import alone does not prove the code is pure.

**Startup exception:** a small process startup wrapper may call its dedicated
bootstrap function. For example, `query_worker_startup.py` builds the restricted
worker and passes it to the protocol entrypoint. The architecture tests check
these wrappers against exact permitted structures. A handler cannot import a
wrapper or use bootstrap as a service locator. New wrappers need checker coverage.

## Responsibilities and examples

| You need to… | Put it in… | Keep out of… |
| --- | --- | --- |
| Parse `page_size`, reject malformed HTTP input or serialize JSON. | HTTP schemas/routes. | Domain rules and database repositories. |
| Resolve preview access and choose a pinned generation. | Controller guards call application AccessService; preview consumes approved access (ADR-0070). | Browser-supplied roles or reused access contexts. |
| Select public catalog datasets. | Controller guards call application AccessService; catalog consumes approved `CatalogAccess` (ADR-0083). | Token resolution or role policy inside `CatalogService`. |
| Decide whether capacity is valid and calculate the offline share. | Pure domain policy. | HTTP handlers or DuckDB SQL as the sole policy definition. |
| Verify a Cognito signature or exchange an authorization code. | Cognito adapter behind an application port. | Domain and route bodies. |
| Read role assignments or commit publication metadata. | PostgreSQL adapter through an application port. | Flask routes and analytical workers. |
| Inspect SQLGlot AST references. | SQL-validation adapter behind the inspection port. | Application code importing parser AST classes. |
| Download/checksum Parquet and manage cache pins. | S3/cache adapters. | Domain and caller-selected filesystem paths. |
| Register or start a concrete adapter. | Bootstrap and the explicit process lifecycle. | Imports, HTTP requests and `create_app`. |

For example, a preview request follows this flow:

```text
HTTP guards: resolve session and approve dataset through AccessService
  → request DTO: validate path dataset and query inputs together
  → application service: consume approved access and validated request
  → application ports: select published inputs and execute bounded preview
  ← application result
HTTP route: serialize response
```

The application calls interfaces; bootstrap provides the adapters. The same
business checks must hold when a use case is called directly, from a CLI or
from a worker. Pure functions stay lightweight; use narrow protocols for actual
external capabilities rather than adding a command bus or generic abstractions.

## State and execution rules

These are boundaries to preserve when changing code. The architecture overview
and linked ADRs explain the full behavior.

| Area | Rule |
| --- | --- |
| Authorization | Application use cases check the current session/role before analytical access, including continuation pages. Cognito supplies identity; seeded PostgreSQL users and exactly one role determine access. Registration, Admin user management, per-user grants and ABAC are excluded. |
| Operational storage | PostgreSQL on RDS owns users, sessions, refresh outcomes and publication descriptors. Local integration tests also use PostgreSQL; pure unit tests may use fakes. No implicit SQLite fallback. |
| Transactions | Application services choose transaction boundaries; adapters execute them through ports. Use bounded pools and short transactions. Do not hold database writes across EIA/S3 calls or analytical execution. |
| Durable data | Each generation has exactly three unified Parquet resources. Physical files preserve private provenance; analytical views project public columns. No daily modeled partitions, supporting S3 graph, manifest or duplicate public files. |
| Publication | Verify all three immutable uploads by full durable readback before committing exact descriptors and the active pointer in PostgreSQL. A receipt is not publication. Preserve the previous generation on failure and each reader's selected snapshot. Legacy rows without descriptors fail closed; do not convert/reset history implicitly. |
| Retention | Invalid replacements, absent keys and wholly excluded routes retain prior valid data. Initial loading requires usable output in all three grains. Pure merge/eligibility rules stay in domain. |
| Refresh | An independent worker executes admitted runs; HTTP/import/app-factory lifetimes never own it. Freeze configuration at admission. HTTP dates are configured start through today's UTC date, without caller overrides or a fixed 183-day ceiling. Requester/key idempotency replays the original configuration. |
| Recovery | Fence stale owners. A healthy refresh worker survives API restarts. After worker loss, reconcile publication before marking work interrupted; unpublished work requires explicit Admin retry, not an automatic source rerun. |
| SQL inspection | Parse and inspect user SQL in a separate bounded subprocess. Enforce admission, CPU, memory, wall time, transport and confirmed termination; no API-process parsing fallback. |
| SQL execution | Use only the isolated execution port with authorized exact staged inputs. Workers get no operational database, cloud credentials, unrestricted cache or network. No API-process DuckDB fallback or per-request input reconstruction. |
| Continuations | Execute SQL once and retain that result for pagination. Do not inject pagination SQL or silently rerun it. Query-ID/cursor metadata is bounded, expiring and process-owned, never PostgreSQL. |
| Analytical ownership | Local acceptance uses one threaded API process and one analytical slot. Preserve ownership/pins until termination and cleanup are confirmed. Reject reloaders, inherited/forked resources and multiple API owners. |
| Startup/shutdown | Imports and factories are inert: no live connections, migrations, jobs or threads. Start/close resources explicitly. API shutdown does not own the independent refresh worker. |

Related decisions:

- [RDS storage](../adr/0032-postgresql-on-rds.md),
  [retention](../adr/0037-connector-initial-load-and-retention.md),
  [seeded role-only access](../adr/0043-seeded-users-and-role-only-access.md).
- [Three resource files](../adr/0060-persist-only-three-resource-files-per-generation.md),
  [generation-prefixed keys](../adr/0061-generation-prefixed-resource-object-keys.md),
  [obsolete manifest removal](../adr/0064-remove-obsolete-manifest-publication-columns.md).
- [Refresh recovery](../adr/0052-interrupted-refresh-recovery.md),
  [current-end refresh interval](../adr/0063-configured-start-current-end-refresh.md),
  [refresh idempotency](../adr/0065-simplify-refresh-run-idempotency-and-metadata.md).
- [Local API ownership](../adr/0053-local-single-owner-analytical-acceptance.md),
  [bounded SQL inspection](../adr/0054-bounded-subprocess-sql-inspection.md).

## Agent change checklist and automated enforcement

Before editing, identify the layer, affected use case, relevant ADRs and behavior
to verify. Read [AGENTS.md](../../AGENTS.md) and [conventions](conventions.md).

1. Check imports against the matrix, including wrappers and re-exports.
2. Preserve authorization before data access on all affected paths.
3. Verify pure behavior through domain/application APIs; use adapter tests for
   transactions, file formats, engine behavior and isolation where relevant.
4. Run the relevant available checks and report what actually passed or remains
   untested. See [testing](../development/testing.md) and the [README](../../README.md).
5. If changing an accepted boundary, record its user-authorized revision in a new
   ADR and update this guide and `AGENTS.md`; do not rewrite historical decisions.

[Architecture tests](../../tests/architecture/) enforce import directions,
relative imports/re-exports, cycles, inner-layer external dependencies and exact
startup exceptions. Negative fixtures prove forbidden patterns are rejected.
[CI](../../.github/workflows/ci.yml) runs these alongside behavior/static checks.
Narrow pure-library/transport exceptions are defined in the
[checker](../../tests/architecture/import_rules.py); they do not authorize general
JSON file I/O or process execution in inner layers.

Static checks cannot prove runtime authorization, publication integrity or
sandbox containment. Tests must establish those behaviors separately. Explicit
startup and fresh-interpreter tests also guard inert imports/factories.

## Runtime and implementation references

Local installation uses the dedicated Apple Silicon/Colima environment in the
[first-time guide](../development/fresh-machine.md). Operator helpers in
`scripts/` prepare/configure/supervise it; product layers do not import them.
The native Linux quota backend requires the controller on the Docker daemon host
and a dedicated bounded ext4 spill filesystem. Docker Desktop is unsupported by
that backend; see the [runtime runbook](../../infrastructure/analytical-worker/README.md).

Local preview/SQL readiness with refresh idle is separate from full capacity
acceptance ([ADR-0055](../adr/0055-scoped-local-analytical-readiness.md)).
[ADR-0056](../adr/0056-user-directed-local-api-activation.md) records the user's
local activation and instruction to stop further external-service/browser checks.
Keep normal authorization, actual-host profile matching, isolation and lifecycle
checks; those service assumptions do not establish new live evidence.

Full high-water/spill, S3 performance and API/refresh overlap evidence, measured
production budgets and final EC2 topology/storage/deployment remain separate open
checkpoints. Documentation changes grant no deployment, startup, refresh,
publication or reset authorization.

| Need more detail? | Read |
| --- | --- |
| Functional module and individual HTTP flows | [Module diagrams](module-diagrams.md). |
| Endpoint contracts and OpenAPI | [HTTP contract](../specs/data-api/http-contract.md) and [packaged OpenAPI](../../src/outage_explorer/entrypoints/http/openapi.json). |
| Entities, public schema and provenance | [Data model](data-model.md). |
| Connector/refresh implementation checkpoints | [Refresh persistence tasks](../specs/refresh-persistence/tasks.md). |
| Auth implementation and accepted/live evidence | [User-access verification](../specs/user-access/verification.md). |
| Analytical startup and evidence scope | [Runtime evidence map](../specs/data-api/runtime-evidence.md). |
| Recorded modeling findings and offline reproduction | [Challenge documentation](../challenge/README.md). |

## Reusing cursor pagination

New cursor endpoints can derive their request DTO from `CursorPaginationRequest`
and inject `CursorPaginator` with their response byte limit and byte counter.
Supply a `CursorPage` containing a bounded ordered read, one continuation key per
row, a cursor callback, fixed size, current position and endpoint metadata.
`paginate` returns the shared rows/page-size/current/next-cursor/has-more envelope.
The endpoint retains responsibility for authorization, filtering, stable ordering,
snapshot ownership and cleanup; the paginator never fetches data or alters SQL.
See [ADR-0071](../adr/0071-shared-cursor-pagination-and-request-validation.md).

## Reusing numbered pagination

`domain/pagination.py` owns pure numbered-page bounds; `application/dto.py`
provides `NumberedPage`, and `application/pagination/numbered.py` assembles the
common numbered-page fields around rows and caller-supplied metadata.
The query controller validates HTTP page fields through its request DTO before
execution. Non-HTTP entrypoints must validate before invoking `QueryService`.
The service authorizes the inspected SQL scope once and passes that approval to
`QueryResultPager` for the first page. Later page requests reauthorize current
access to the retained grains. The pager owns fixed-size checks, reader cleanup
and assembly; `QueryService` has no page method. The query-result adapter
computes the pure window, reads verified
spool rows, and returns query identity, generation and expiry metadata. The
generic paginator owns no storage, authorization, lifetime or SQL execution.
Future services must provide those boundaries and enforce their own response
byte budgets. See [ADR-0090](../adr/0090-shared-numbered-pagination.md).

`PreviewRequest` requires the dataset ID alongside query inputs. Its Pydantic
model validators reject unsupported dataset/filter combinations during construction;
`PreviewService.read` does not perform DTO validation. The HTTP validation guard
forwards the named dataset route parameter after authorization. Non-HTTP callers
construct the DTO with the dataset ID from their freshly approved `PreviewAccess`.


## Mandatory controller convention

Before controller work, read [Required HTTP controller pattern](http-controllers.md)
and [ADR-0075](../adr/0075-decorator-driven-http-controllers.md). Its required
decorator order and must-do/must-not-do examples govern new controllers and
controller refactors; existing legacy route code is not a precedent.

## HTTP response DTOs

Use `@respond_with(ResponseDto)` inside authorization and request-validation
guards. The handler returns its service result. The generic decorator in
`entrypoints/http/responses/base.py` passes it to `ResponseDto.from_result`, calls
`build()` for `ResponseData`, and serializes the body, status (default `200`)
and optional headers. Exceptions reach existing error handlers; transport
finalization still applies shared security and CORS headers. This contract is
for JSON endpoints; redirects, streaming and bodyless responses retain their
existing transport handling.

Refresh uses `RefreshAdmissionResponse`, `RefreshLatestResponse` and
`RefreshStatusResponse` in `entrypoints/http/responses/refresh.py`. These DTOs
specify public envelopes, status codes, headers and missing-run responses without
constructing Flask responses. Application result bases in
`application/refresh_responses.py` map runs to public data without Flask.
Existing public quality projections remain in `application/data_payloads.py`.

Refresh GET validation also runs through `validated_request`: `empty_request`
rejects query/body inputs for latest, and `refresh_status_request` additionally
validates the route run ID before status lookup. Refresh handlers contain only
service calls; role guards run before all request validation.

## Shared HTTP error and preflight handling

`create_app` registers `register_error_handlers` and `register_preflight_handler`
once when authentication transport is configured. Controllers do not register
local exception or preflight hooks. `errors.py` retains the data/auth mappings,
login/callback error semantics and callback attempt-cookie cleanup. Routing
errors on API paths remain sanitized; unrelated routing errors retain their HTTP
status. Shared response finalization still runs for successes and failures.

`preflight.py` maps registered endpoint names to explicit methods and header
allowances. OPTIONS requests are handled before guards or service invocation;
unmatched URLs proceed to routing error handling. Preserve current compatibility:
auth preflight permits GET/POST, query permits GET/POST, datasets permit GET, and
refresh permits POST for admission and GET for reads. All refresh endpoints
currently allow Idempotency-Key. Update policies explicitly when adding endpoints.

## Required model repositories and current ORM implementation

[ADR-0078](../adr/0078-model-repositories-and-session-decorators.md) establishes
dedicated SQLAlchemy model repositories and `@with_session` as the required
pattern for new and refactored operational persistence. Read the
[repository guide](persistence-repositories.md) before adding model queries.
Process coordinators invoke persistence operations; they must not mix raw SQL
or inline ORM queries into workflow logic. Existing raw-SQL adapters are legacy
implementation, not examples for new code.

The read implementation from [ADR-0074](../adr/0074-refresh-run-orm-pilot.md)
and [ADR-0077](../adr/0077-latest-refresh-run-orm-read.md) covers
`PostgresqlResourcePublicationStore.get_run` and `latest`, which delegate to an injected
`PostgresqlRefreshRunRepository` in `refresh_run_repository.py`. Bootstrap
constructs both with the same bounded pool. Its typed `RefreshRunRecord` lives
in `infrastructure/postgresql/refresh_run_record.py` and converts to the existing
plain domain `RefreshRun` before the session closes. Application ports and
callers remain independent of ORM types.

The typed `@with_session` decorator in `session_scope.py` injects the session
into the repository's reads, so their bodies only query and map records.
`latest` joins the partial `RefreshCoordinationRecord` mapping to prioritize the
active run before admission time and UUID descending. Both record types share
`orm_base.py` metadata. Callers still pass only `run_id` to `get_run` and no
arguments to `latest`. Each decorated invocation owns a separate transaction; the
decorator does not compose multiple calls into a shared Unit of Work.

[ADR-0079](../adr/0079-refresh-ownership-and-base-repositories.md) extends this
pattern to claim and heartbeat in `PostgresqlRefreshCoordinationRepository`.
Each locks the coordination row and completes its updates in one decorated
transaction. [ADR-0080](../adr/0080-refresh-progress-repository.md) places
progress in that repository with the same ownership check and transaction
boundary. [ADR-0081](../adr/0081-refresh-finish-repository.md) places
unpublished finish there too, including the run outcome and slot release in one
transaction. `PostgresqlPublishedGenerationRepository` contains the active-base
validation and generation reads. Admission's base validation takes its existing
ORM session; opening another session would lose admission atomicity.

[ADR-0082](../adr/0082-atomic-published-generation-repository.md) moves the
whole successful publication transaction into `PostgresqlPublishedGenerationRepository`.
Its `PublishedGenerationRecord` maps the immutable descriptors; the ORM base
check shares the publication session. Admission's base check shares its own
locked ORM session. The publication store retains uncertain-commit
reconciliation outside the repository operation.
[ADR-0087](../adr/0087-atomic-refresh-admission-repository.md) established the
atomic queued-run and slot write. [ADR-0088](../adr/0088-pure-refresh-admission-policy.md)
places replay priority, busy-slot rejection and initial-load start eligibility
in pure domain policy. [ADR-0089](../adr/0089-service-owned-refresh-admission.md)
makes `RefreshService` evaluate those rules with values obtained through the
locked admission transaction port. The run repository owns the session, reads
and atomic run/slot writes.
[ADR-0091](../adr/0091-context-lifetime-session-decorator.md) injects that
session with `@with_session_context`, which keeps it open for the service's
`with` block. Ordinary repository methods still use `@with_session`.
[ADR-0084](../adr/0084-pure-publication-base-policy.md) puts the publication
base and initial-load eligibility rule in `domain/publication_policy.py`; the
repository supplies freshly locked values and retains the atomic writes.
[ADR-0085](../adr/0085-active-generation-orm-read.md) moves the active-generation
join into a decorated repository read; the publication store only delegates.
[ADR-0086](../adr/0086-reconcile-refresh-in-repository.md) puts recovery and
uncertain-commit reconciliation into one decorated generation-repository
transaction. The domain policy decides interruption eligibility; the repository
checks publication history and applies the run/slot changes under its lock.

`BoundedPostgresqlPool.session()` provides a short-lived transaction over the
same process-owned psycopg pool used by handwritten SQL. SQLAlchemy NullPool
avoids a second physical pool; ORM connections use tuple rows and the pool reset
restores dictionary rows before reuse. Construction remains free of database
connections. The read mapping is not complete schema metadata: Alembic remains
the schema authority and is not configured for ORM autogeneration.

Access persistence remains outside this migration. Continue only within requested
work, preserving atomicity and recovery contracts.
Read-path acceptance is defined in the [pilot specification](../specs/refresh-run-orm/spec.md).


Auth and query request DTOs also use narrowly allowed Pydantic APIs in the HTTP
layer under [ADR-0076](../adr/0076-auth-and-query-transport-request-models.md),
with request module locations updated by
[ADR-0092](../adr/0092-group-http-transport-by-responsibility.md).
Query services retain their existing scalar arguments and fresh authorization.
Catalog uses a typed `CatalogResult` with `CatalogResponse` to build its public
dataset envelope. Preview/query public payloads use `JsonPayloadResponse`; auth
redirects and cookie/bodyless results use dedicated `respond_with_auth` DTOs.
