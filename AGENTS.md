# Outage Explorer agent instructions

## Read before changing this project

Read [code structure](docs/context/code-structure.md),
[architecture](docs/context/architecture.md), and
[conventions](docs/context/conventions.md), then the relevant specification
under `docs/specs/` and accepted ADRs. Read `CLAUDE.md` and
`.claude/CLAUDE.md` if present. Current user instructions take precedence.

Use the `palace-knowledge` skill and matching project knowledge when recalling
prior work. Search Engram under `outage-explorer` before architectural changes;
revalidate historical claims and save significant decisions with their rationale.
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

1. No storage/SDK/engine calls or business rules in Flask routes. No Flask
   context (`request`, `g`, `current_app`) in domain or application code.
2. Enforce permissions in application use cases before analytical data access;
   route decorators alone are insufficient. Cognito supplies identity;
   application-owned PostgreSQL tables determine permissions.
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

ECS launch/storage, sandbox launcher, session mapping, and measured budgets
remain open. One WSGI process is a proposal, not an accepted runtime mandate.
Do not invent source schemas, resource measurements, or test results to close
these gaps. Documentation work does not authorize deployment or publication.
