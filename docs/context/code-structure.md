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
| `settings.py` | Read and validate startup configuration. | Environment values and enabled features. |

Selected existing files and packages:

```text
src/outage_explorer/
  bootstrap.py
  settings.py
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
      preview.py               # snapshot-bound browsing
      queries.py               # inspect, authorize, execute and page SQL
      refresh.py               # refresh admission
      refresh_execution.py     # execute admitted work and publish
      refresh_recovery.py      # reconcile interrupted work
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
      data_schemas.py          # data HTTP input/output handling
      routes/                  # health, auth, datasets, queries, refresh, docs
      openapi.json             # packaged HTTP contract
      analytical_startup.py    # explicit analytical API startup
    cli/                       # connector, setup and offline verification
    refresh_worker.py          # independent refresh worker loop
    query_worker.py            # restricted analytical worker protocol
    refresh_worker_startup.py  # refresh process composition seam
    query_worker_startup.py    # query process composition seam
```

Split an oversized module into a package **within its existing layer**. Related
features can be grouped inside each layer. Create files only when behavior needs
them; do not add a parallel `modules/<feature>/{domain,application}` hierarchy,
generic CRUD framework or repository for every analytical row type.

## Dependency matrix

Read each row as: “code in this location may import these internal modules.”
Runtime calls through a port do not permit importing its concrete implementation.

| Importing code | Allowed internal dependencies | Forbidden dependencies |
| --- | --- | --- |
| `domain` | Domain types/functions; pure standard-library operations. | Application, infrastructure, entrypoints, bootstrap and settings. |
| `application` | Domain; application services, DTOs, errors and ports. | Infrastructure, entrypoints, bootstrap and settings. |
| `infrastructure` | Domain; application ports/DTOs/errors; cohesive infrastructure helpers. | Entrypoints, bootstrap and application service orchestration. |
| `entrypoints` handlers | Application services/DTOs/errors; entrypoint schemas/helpers. | Concrete infrastructure, direct domain policy execution and runtime wiring. |
| `bootstrap` | All layers and settings, for construction and injection. | Business rules and request orchestration. |

Database drivers, SDKs, engine calls and file/network I/O belong in infrastructure.
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
| Resolve current access and choose a pinned preview generation. | Application preview/access services. | Route decorators as the sole authorization check. |
| Decide whether capacity is valid and calculate the offline share. | Pure domain policy. | HTTP handlers or DuckDB SQL as the sole policy definition. |
| Verify a Cognito signature or exchange an authorization code. | Cognito adapter behind an application port. | Domain and route bodies. |
| Read role assignments or commit publication metadata. | PostgreSQL adapter through an application port. | Flask routes and analytical workers. |
| Inspect SQLGlot AST references. | SQL-validation adapter behind the inspection port. | Application code importing parser AST classes. |
| Download/checksum Parquet and manage cache pins. | S3/cache adapters. | Domain and caller-selected filesystem paths. |
| Register or start a concrete adapter. | Bootstrap and the explicit process lifecycle. | Imports, HTTP requests and `create_app`. |

For example, a preview request follows this flow:

```text
HTTP route: validate input
  → application service: resolve session and authorize
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
