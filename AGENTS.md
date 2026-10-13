# Outage Explorer agent instructions

## Read before changing this project

Read [code structure](docs/context/code-structure.md),
[architecture](docs/context/architecture.md), and
[conventions](docs/context/conventions.md), then the relevant specification
under `docs/specs/` and accepted ADRs. Read `CLAUDE.md` and
`.claude/CLAUDE.md` if present. Current user instructions take precedence.

Do not apply another project's conventions to this repository.

## Accepted structure

This is a **layered Python/Flask monolith**, accepted in
[ADR-0030](docs/adr/0030-layered-flask-monolith.md). Use the layer-first layout
in the structure guide. Keep one product codebase and release; separately
supervised refresh and isolated analytical workers do not change that choice.

Operational storage is **PostgreSQL on Amazon RDS**, accepted in
[ADR-0032](docs/adr/0032-postgresql-on-rds.md). It replaces SQLite and the
SQLite-specific EC2/EBS proposal. Use `infrastructure/postgresql/`; local
development and integration tests use PostgreSQL, while unit tests may use
fakes. Do not reintroduce SQLite as an implicit development fallback. RDS does
not change the one-replica limit or make query-ID metadata durable.

Under [ADR-0078](docs/adr/0078-model-repositories-and-session-decorators.md),
dedicated model repositories using SQLAlchemy and `@with_session` are the required
pattern for new and refactored operational persistence. `RefreshStore.get_run`
and `latest` follow it under ADR-0074/ADR-0077; claim and heartbeat follow
[ADR-0079](docs/adr/0079-refresh-ownership-and-base-repositories.md). Base
validation stays on its caller's transaction through a generation repository.
Progress follows [ADR-0080](docs/adr/0080-refresh-progress-repository.md), and
unpublished finish follows [ADR-0081](docs/adr/0081-refresh-finish-repository.md).
Atomic generation publication follows
[ADR-0082](docs/adr/0082-atomic-published-generation-repository.md); uncertain
commits still require fresh locked reconciliation. Publication-base eligibility
is pure domain policy under
[ADR-0084](docs/adr/0084-pure-publication-base-policy.md).
[ADR-0085](docs/adr/0085-active-generation-orm-read.md) moves the active
generation read to the decorated ORM repository.
[ADR-0086](docs/adr/0086-reconcile-refresh-in-repository.md) places recovery
and uncertain-commit reconciliation in one decorated repository transaction.
[ADR-0087](docs/adr/0087-atomic-refresh-admission-repository.md) moves queued
run creation and the full atomic admission operation to the run repository.
[ADR-0088](docs/adr/0088-pure-refresh-admission-policy.md) keeps replay priority
and initial-load eligibility in pure domain policy.
[ADR-0089](docs/adr/0089-service-owned-refresh-admission.md) makes
`RefreshService` invoke those rules inside a focused admission transaction port.
[ADR-0091](docs/adr/0091-context-lifetime-session-decorator.md) uses
`@with_session_context` for that port's repository session lifetime.
Keep records and sessions in `infrastructure/postgresql/`, return domain values and share the existing
bounded psycopg pool. Remaining raw-SQL paths are legacy to migrate within the
requested scope. Do not use partial ORM metadata to generate schema migrations.

Deployment targets **Amazon EC2**, replacing ECS under
[ADR-0038](docs/adr/0038-ec2-deployment-local-development.md). Development runs
locally with configured RDS, Cognito and S3 resources as needed. An EC2 instance
is not required for local development; provisioning and deployment decisions
must not block independent local implementation or testing.

Local connector configuration follows [ADR-0041](docs/adr/0041-connector-defaults-and-json-configuration.md):
typed resource defaults with optional `--config PATH` JSON overrides; explicit
run flags take precedence over file values. `EIA_API_KEY` remains environment-only;
do not reintroduce mandatory `OUTAGE_CONNECTOR_*` budget variables. Defaults are
initial limits, not measured live/production budgets.

Connector CLI candidate runs persist to S3 by default under
[ADR-0042](docs/adr/0042-connector-cli-default-s3-persistence.md), with its complete
evidence-graph requirement superseded by
[ADR-0060](docs/adr/0060-persist-only-three-resource-files-per-generation.md).
Explicit `--local-only` (Make: `LOCAL_ONLY=1`) remains AWS-independent. Validate
S3 target configuration before source work; default success requires full durable
readback of all three exact resource files, with no local-only fallback after S3 failure. Preserve local
artifacts for explicit persistence retries; a durable receipt is not publication.

Modeled data follows [ADR-0060](docs/adr/0060-persist-only-three-resource-files-per-generation.md),
superseding the six-file and audit-preservation clauses of ADR-0057: exactly three
unified resource Parquet files per generation, one per grain. Each preserves
private provenance, original numeric strings, units, natural identity and exact
calculation evidence for faithful baseline retention. Analytical views explicitly
project only the existing public columns. Raw/pages/dispositions/ledgers remain
bounded transient candidate inputs; quality and exact publication descriptors
belong in PostgreSQL. No durable supporting artifacts or S3 manifest are required.
The implementation proceeds through the refresh-persistence phase checkpoints;
existing-generation cutover follows
[ADR-0064](docs/adr/0064-remove-obsolete-manifest-publication-columns.md): obsolete
manifest columns and the old publication adapter are removed; an active base
without exact resource descriptors fails closed and moving past it needs explicit
user direction. Physical S3 keys follow
[ADR-0061](docs/adr/0061-generation-prefixed-resource-object-keys.md):
`<configured-prefix>generations/<generation-id>/{national,facilities,generators}.parquet`,
with local checksum identity distinct from exact durable descriptors.
Do not write or read daily modeled partitions, or add old-layout compatibility
code. Readers never rebuild inputs per request; workers scan views over exact
staged files, without whole-input table imports. No reset CLI exists:
[ADR-0058](docs/adr/0058-user-directed-publication-reset.md) records that the
one-time pointer reset was user-directed SQL. Do not clear the active generation
pointer or alter publication history without explicit user direction.

- `domain/`: pure policies and types; no framework, engine, SDK, database, or I/O.
  ADR-0068 permits only the reviewed Pydantic validation APIs in
  `domain/refresh_configuration.py`; this does not permit other framework imports.
- `application/`: use cases, authorization, transaction orchestration, DTOs,
  and ports; depends on domain, not concrete infrastructure or Flask.
- `infrastructure/`: PostgreSQL, Cognito, EIA, S3, Parquet, SQL inspection, cache,
  result storage, and execution adapters; implements application ports.
- `entrypoints/`: thin HTTP, CLI, and worker entry points; invoke application
  use cases and translate transport inputs/outputs.
- `bootstrap.py`: construct and inject dependencies. Concrete wiring belongs
  here; the HTTP application factory registers already-constructed services.

Do not introduce parallel `modules/<feature>/{domain,application}` trees,
service-to-service HTTP, a broker, or another persistence/framework stack as
routine implementation. The feature-first ADR-0029 proposal was replaced by
ADR-0030; the independent-services example is explanatory, not selected.

## Boundaries agents must preserve

Local analytical endpoint acceptance uses one API serving process with threads,
one analytical execution slot and independently supervised refresh under
[ADR-0053](docs/adr/0053-local-single-owner-analytical-acceptance.md). This is a
local acceptance decision; final EC2 topology remains open. It grants no startup
or activation permission and does not bypass analytical readiness gates.

[ADR-0055](docs/adr/0055-scoped-local-analytical-readiness.md) adds a separately
reviewed local preview/SQL readiness path with refresh idle. Complete high-water/
spill, S3 performance and API/refresh capacity-overlap evidence remains deferred
to the original open full checkpoints. Preserve authorization, isolation, hard
bounds, lifecycle and actual-host/auth checks; local-scope review must not imply
complete runtime acceptance. Scope approval grants no startup or activation.

[ADR-0056](docs/adr/0056-user-directed-local-api-activation.md) records the user's
subsequent explicit local activation direction: assume existing services work
and stop further external-service/browser validation. Those unperformed checks
remain open evidence rather than startup blockers. Keep normal authorization,
parser/worker isolation, bounds and lifecycle enforcement; keep refresh idle.

Before SQL endpoint enablement, enforce user-SQL parsing/reference inspection in
a separate bounded subprocess under
[ADR-0054](docs/adr/0054-bounded-subprocess-sql-inspection.md). Preserve application
authorization before analytical inputs, bounded admission/resources/transport,
confirmed termination and no API-process parsing fallback. Numeric parser budgets
and concrete runtime verification remain open.

Product HTTP refresh uses a configured start through today's UTC date, without
caller date overrides or a fixed 183-day ceiling, under
[ADR-0063](docs/adr/0063-configured-start-current-end-refresh.md).
Source/model interval budgets use the resolved inclusive span; all non-date
resource bounds remain enforced. Legacy end/date-cap environment settings are ignored.
Record the resolved interval at admission; later configuration changes must
not change a run. Initial-load dates and connector CLI behavior remain governed
by their existing ADRs.

Under [ADR-0052](docs/adr/0052-interrupted-refresh-recovery.md), a healthy refresh
worker survives API-only restarts. Reconcile publication after worker loss;
unpublished interrupted runs require explicit Admin retry, not automatic source
reruns. Recovery must prevent stale owners from publishing.

1. No storage/SDK/engine calls or business rules in Flask routes. No Flask
   context (`request`, `g`, `current_app`) in domain or application code.
2. Enforce permissions in application use cases before analytical data access;
   route decorators alone are insufficient except for the explicitly accepted
   request-scoped refresh contract in ADR-0066: application-owned `AccessService`
   resolves fresh identity and checks roles in the guards, which pass approved
   access into refresh use cases without a second lookup. Non-HTTP refresh callers
   must obtain fresh access through `RefreshService.authorize(token)` first.
   ADR-0070 extends request-scoped access to preview: controller role/dataset guards
   establish `PreviewAccess`; `PreviewService.read` consumes it without another lookup.
   Non-HTTP callers authenticate freshly and call `AccessService.require_dataset`
   before reading. ADR-0083 extends request-scoped access to catalog: the guards
   establish `CatalogAccess`, and non-HTTP callers authenticate freshly and call
   `AccessService.require_catalog` before listing. ADR-0071 permits narrowly
   reviewed Pydantic APIs in `application/pagination/request.py` and
   `application/preview_request.py` only.
   ADR-0073 additionally permits `BaseModel`, `ConfigDict`, `Field` and
   `ValidationError` in `application/refresh_request.py` for admission validation.
   Cognito supplies identity;
   application-owned PostgreSQL users and role assignments determine access.
   Under ADR-0043, users and roles are seeded; registration and Admin user
   management are excluded throughout implementation. Each user has exactly
   one role under ADR-0044. Access is role-only;
   do not introduce per-role read/write/delete permissions, per-user grants,
   ABAC or row/column policies for current scope.
3. Execute user SQL only through the isolated execution boundary, with authorized
   inputs and bounded resources. No API-process DuckDB fallback or worker
   access to operational PostgreSQL, cloud credentials, or unrestricted cache files.
4. Preserve one execution's result for SQL pagination. Under ADR-0090, HTTP
   request DTOs validate page inputs before execution; non-HTTP execution
   entrypoints must validate their own inputs. `QueryService` authorizes the
   inspected SQL scope once and the pager reuses that approval for its first
   page; each later page request requires fresh authorization. `QueryService`
   has no page method. Do not inject pagination
   clauses, silently rerun SQL, or persist query-ID metadata in PostgreSQL.
5. Keep refresh outside request/import/app-factory lifecycles. Publish only a
   fully verified generation; preserve previous data and accepted invalid-row,
   duplicate, revision, and retained-valid-row policies.
   [ADR-0037](docs/adr/0037-connector-initial-load-and-retention.md) retains absent
   prior keys and wholly excluded routes while allowing other valid updates.
   Initial live loading requires usable output in all three grains; its explicit
   initial start is April 2, 2026; ADR-0069 replaces the fixed initial end with
   the UTC end date frozen at admission for product refreshes.
6. Inject concrete dependencies at startup. Avoid module-import side effects,
   circular imports, catch-all utilities, generic CRUD hierarchies, and live
   database connections shared across processes.
7. Preserve concurrent changes, historical ADRs, and the append-only devlog.
   Record a new ADR for a changed accepted boundary; do not silently treat an
   unaccepted recommendation as an implementation decision.

## Mandatory persistence repository convention

Before adding model queries or refactoring persistence, read
[Required persistence repository pattern](docs/context/persistence-repositories.md).
Use `PostgresqlRefreshRunRepository` as the reference implementation.

- MUST centralize model queries in dedicated infrastructure repositories using
  SQLAlchemy ORM/expressions. ORM records describe mapping; repositories own queries.
- MUST use `@with_session` at repository operation boundaries to inject the
  short-lived session and keep lifecycle boilerplate out of query methods.
- MUST keep process/workflow logic separate: invoke persistence operations through
  application ports or injected repositories as allowed by the layer. No raw SQL
  or inline ORM queries mixed into process coordinators, services or controllers.
- MUST construct/inject concrete repositories through bootstrap and return domain
  values/DTOs rather than live ORM objects. Preserve the shared bounded pool.
- MUST preserve atomic transactions: separate decorated calls do not share a
  transaction. Multi-step atomic database operations need one shared session;
  their internal helpers must not open independent decorated sessions.
- Admission is the scoped exception in ADR-0089: its repository exposes an
  application-owned transaction port so `RefreshService` can invoke policy
  under the coordination lock. `@with_session_context` keeps its session open
  for the entire `with` block; the session remains inside infrastructure.
- Remaining raw queries in publication/access adapters are not patterns to copy.
  Migrate only within the user's requested scope. Migration/connection SQL and
  isolated analytical SQL retain their separate documented roles; any necessary
  raw operational statement belongs in a repository with a documented reason.

## Mandatory HTTP controller convention

Before adding or refactoring any controller, read
[Required HTTP controller pattern](docs/context/http-controllers.md) and
[ADR-0075](docs/adr/0075-decorator-driven-http-controllers.md).
Use the refresh controller as the reference implementation.

- MUST declare applicable auth/role/dataset/CSRF guards as decorators, then
  `validated_request` and `respond_with(ResponseDto)` for JSON endpoints.
- MUST use validated request DTOs with reviewed Pydantic APIs for structured
  inputs; no-input endpoints still use the empty-request validation decorator.
- MUST keep handlers focused on service calls and returning their results.
  Response DTOs specify body/status/headers; the generic decorator builds HTTP.
- MUST register blueprints, error handling and endpoint preflight policies
  centrally in HTTP setup. Preserve existing authorization/CORS/error contracts.
- MUST NOT reintroduce inline `parameters(set())`, request parsers, identifier
  checks, manual DTO constraint loops, `jsonify`, response/status/header building,
  missing-result response branches, local exception handlers or preflight hooks
  in JSON controllers. The guide maps each old pattern to its required replacement.
- Auth/query transport DTO Pydantic APIs are scoped to the exact modules in
  [ADR-0076](docs/adr/0076-auth-and-query-transport-request-models.md), with
  module locations updated by
  [ADR-0092](docs/adr/0092-group-http-transport-by-responsibility.md). Catalog
  receives approved application-owned `CatalogAccess` under ADR-0083; query
  services retain application authorization. Auth redirects and bodyless
  logout use dedicated response decorators; session/logout reject nonempty inputs.
- Existing legacy routes are not examples to copy. Non-JSON flows and public
  endpoints retain their documented transport/access contracts; do not add
  authentication or force redirects/bodyless responses through JSON serialization.

## Verification and reporting

Use the dependency matrix and change checklist in the structure guide.
Run the relevant available checks and report what actually ran. The health
scaffold includes automated import-boundary checks in `tests/architecture/`
and `.github/workflows/ci.yml`. Preserve their negative fixtures and narrow
startup exception. Run Ruff, mypy, and pytest as documented in README.
Static checks and liveness do not prove runtime authorization or isolation.

Temporary user instruction (2026-10-12): pause running unit tests to reduce
token use until the user asks to resume. Use focused checks for current work and
report exactly which checks ran; this does not change CI or the test suite.

EC2 deployment/storage, sandbox launcher, session mapping, and measured budgets
remain open. One WSGI process is a proposal, not an accepted runtime mandate.
Do not invent source schemas, resource measurements, or test results to close
these gaps. Documentation work does not authorize deployment or publication.
