# Layered Flask monolith structure

Status: **accepted structure**, [ADR-0030](../adr/0030-layered-flask-monolith.md).
The health scaffold and offline national/facility/generator verification are implemented; product
data delivery remains pending. This guide governs application code and refactors;
[AGENTS.md](../../AGENTS.md) makes its rules discoverable to agents.

Operational storage uses [PostgreSQL on Amazon RDS](../adr/0032-postgresql-on-rds.md).
Use PostgreSQL for local development and integration tests as well; pure unit
tests may substitute application ports with fakes. The engine version, driver,
migration tooling, and local setup remain to be selected.

Use one application organized by technical layer. Keep business policies
independent of Flask and storage through small application-owned interfaces.
This provides a simple layered layout with testable dependencies. HTTP,
background refresh, and verification commands reuse the same use cases.

## Directory layout

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
    s3/                         # immutable objects and manifest retrieval
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

`application/ports/artifacts.py` and `candidates.py` define artifact and candidate
contracts without Arrow types. `infrastructure/parquet/` implements explicit
schemas, bounded evidence replay, complete date-group modeling and history scans,
immutable local objects, and persisted manifests. Verification replays expected
rows/ledgers, checks cross-file uniqueness and exact values, and binds retained
rows to inherited evidence and the pinned base manifest. No whole-history row
collection is required; manifest metadata, day groups and batches have explicit
caller budgets. Read-only verification trades repeated sequential scans for
bounded memory. Local tests do not establish measured production resource limits
or AWS guarantees. The source contract in `application/ports/source.py` and
adapters in `infrastructure/eia/` now supply bounded sequential retrieval,
sanitized evidence and source-quality reconciliation. HTTPX stays in
infrastructure; an explicit injected transport enables controlled tests without
network access or import-time construction. A context-local transport logging
filter covers wire reads and closes without retaining secrets or suppressing
unrelated concurrent logs. The contributor CLI now composes these adapters through
`application/services/connector.py`, with typed default budgets and optional JSON
file overrides through `--config` (ADR-0041), exact
prior-manifest input, sequential terminal-quality checks and bounded separate-run
JSON progress/final reports. `infrastructure/parquet/connector.py` reopens and
verifies the complete bounded ancestry before retrieval and after candidate
persistence. `bootstrap.execute_connector` validates configuration, constructs
adapters and closes the transport; `entrypoints/cli/connector_startup.py` only
passes that callable to the command so help performs no connector work. Its exact
AST exception and negative fixtures preserve startup restrictions. The command
has no publication capability or mutable active pointer. S3, authorized durable
refresh, publication and live enablement remain work in the
[connector tasks](../specs/data-connector/tasks.md).

Facility and generator verification reuse `domain/observations.py` (national's
API remains in `domain/national.py`) and the shared evidence service/adapters,
with explicit grain contracts and entity/date coverage. Their separate commands
remain offline contributor tools. The source-total difference is reported as
unresolved evidence; this does not establish live pagination completeness or
product authorization. See the [detail contract](../specs/facility-generator-verification/contract.md).
