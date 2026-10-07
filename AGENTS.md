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
   route decorators alone are insufficient. Cognito supplies identity;
   application-owned PostgreSQL users and role assignments determine access.
   Under ADR-0043, users and roles are seeded; registration and Admin user
   management are excluded throughout implementation. Each user has exactly
   one role under ADR-0044. Access is role-only;
   do not introduce per-role read/write/delete permissions, per-user grants,
   ABAC or row/column policies for current scope.
3. Execute user SQL only through the isolated execution boundary, with authorized
   inputs and bounded resources. No API-process DuckDB fallback or worker
   access to operational PostgreSQL, cloud credentials, or unrestricted cache files.
4. Preserve one execution's result for SQL pagination. Do not inject pagination
   clauses, silently rerun SQL, or persist query-ID metadata in PostgreSQL.
5. Keep refresh outside request/import/app-factory lifecycles. Publish only a
   fully verified generation; preserve previous data and accepted invalid-row,
   duplicate, revision, and retained-valid-row policies.
   [ADR-0037](docs/adr/0037-connector-initial-load-and-retention.md) retains absent
   prior keys and wholly excluded routes while allowing other valid updates.
   Initial live loading requires usable output in all three grains; its explicit
   initial interval is April 2–October 1, 2026 inclusive.
6. Inject concrete dependencies at startup. Avoid module-import side effects,
   circular imports, catch-all utilities, generic CRUD hierarchies, and live
   database connections shared across processes.
7. Preserve concurrent changes, historical ADRs, and the append-only devlog.
   Record a new ADR for a changed accepted boundary; do not silently treat an
   unaccepted recommendation as an implementation decision.

## Verification and reporting

Use the dependency matrix and change checklist in the structure guide.
Run the relevant available checks and report what actually ran. The health
scaffold includes automated import-boundary checks in `tests/architecture/`
and `.github/workflows/ci.yml`. Preserve their negative fixtures and narrow
startup exception. Run Ruff, mypy, and pytest as documented in README.
Static checks and liveness do not prove runtime authorization or isolation.

EC2 deployment/storage, sandbox launcher, session mapping, and measured budgets
remain open. One WSGI process is a proposal, not an accepted runtime mandate.
Do not invent source schemas, resource measurements, or test results to close
these gaps. Documentation work does not authorize deployment or publication.
