# Outage Explorer

Explore stored U.S. nuclear outage data at national, facility and generator
levels. Browse datasets, filter observations, run read-only SQL and inspect the
daily share of fleet capacity offline.

| Persona | Access |
| --- | --- |
| Viewer | National data only |
| Analyst | All analytical datasets, filtered previews and SQL |
| Admin | Analyst access plus data refresh |

## Run locally

The application has two sibling checkouts: this Flask backend and the
`outage-explorer-web` Next.js client.

**First-time setup:** follow the [local setup guide](docs/development/local-setup.md)
for dependencies, environment variables, Cognito callbacks and seeded accounts.
The full analytical app requires the existing configured Colima Linux runtime,
RDS, Cognito, S3 and a published dataset. The startup command does not provision
these resources.

Once configured, keep these commands running in separate terminals:

```sh
# Backend checkout
make run-analytical
```

```sh
# Web checkout
npm run dev
```

Open **http://localhost:3000** and sign in with a seeded account. Obtain its
credentials privately from the environment owner. Use `localhost` consistently
for both applications.

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/api/docs
- OpenAPI: http://localhost:8000/api/openapi.json

Ctrl+C stops each process. `make stop-analytical` also stops the backend.
API restarts discard preview cursors and retained SQL result IDs; start a new
preview or explicitly rerun a query.

### Backend without analytical resources

For health, documentation and configured nonanalytical HTTP operations:

```sh
make setup
make run
```

Requires Python 3.12+. Choose an interpreter with
`make setup PYTHON=/path/to/python3`. Flask loads local `.env`; see
[.env.example](.env.example). Health and documentation need no credentials.
This startup supplies no preview/SQL execution resources, so those operations
return `503 service_unavailable`. Run only one backend on port 8000.

## Tests

The full backend checks need disposable PostgreSQL and Chromium. From the
backend checkout, with Docker running:

```sh
make setup
make test-postgres
# Continue after this reports that PostgreSQL is accepting connections:
docker exec outage-explorer-test-postgres pg_isready -U outage_test -d postgres
export OUTAGE_TEST_POSTGRES_DSN='host=127.0.0.1 port=55439 dbname=postgres user=outage_test password=controlled-test-only sslmode=disable'
make test-browser-setup
make check
make test-postgres-stop
```

`make check` runs dependency checks, Ruff lint/format, strict mypy, pytest and
package builds. `make test` runs the test suite alone. Required tests use
controlled providers and a disposable database; live-provider tests are excluded.
CI configures Python 3.12/3.14, PostgreSQL and Chromium.

In the web checkout:

```sh
npm run typecheck
npm run lint
npm test
npm run build
```

Its README documents additional boundary and browser checks.

## Data and refresh

[Connector commands](docs/development/connector.md) cover extraction, local-only
runs, S3 persistence/recovery, failure behavior and the independent refresh worker.
Admin refresh runs in the background over a configured date interval. Publication
requires complete verification of all three resource files; failed refreshes
preserve the previous published data. Browsing stored data does not call EIA.

The daily fleet metric is `100 × national outage MW / national capacity MW`.
It includes full outages and partial output reductions; it does not establish
outage cause or lost energy. See the [model and ER diagrams](docs/context/data-model.md).

## Architecture

A layered Python/Flask monolith, with PostgreSQL on Amazon RDS for users,
sessions and publication metadata. Amazon S3 stores three immutable Parquet
resource files per generation; isolated DuckDB workers query authorized public
views through a bounded local cache. Cognito establishes identity; application
roles determine access. The separate web client uses React, Next.js, TypeScript
and Tailwind CSS.

See [architecture](docs/context/architecture.md),
[code structure](docs/context/code-structure.md) and [DECISIONS.md](DECISIONS.md)
for boundaries, alternatives and rationale. EC2 is the deployment target;
local development does not require an EC2 instance.

## Findings and current limits

[FINDINGS.md](FINDINGS.md) links the 30-day cross-grain reconciliation and three
reproducible findings: facility response-count metadata, historical River Bend
omissions and an unusually long Cook Unit 1 outage. Each investigation includes
its evidence, reproduction command and product treatment.

- Seeded users only; registration and user management are outside scope.
- One backend replica and one analytical execution slot. Query pagination retains
  one execution's bounded result; it never silently reruns SQL.
- Full local analytical startup depends on separately provisioned runtime resources;
  clean-machine provisioning is not automated by `make setup`.
- Integrated SQL denials work as expected per user confirmation on October 7, 2026.
  Remaining release evidence and EC2 deployment configuration are separate work.

## Reference

| Topic | Guide |
| --- | --- |
| Full application configuration and startup | [Local setup](docs/development/local-setup.md) |
| Extraction, persistence, recovery and refresh | [Connector operations](docs/development/connector.md) |
| Authentication, database modes and trusted seeding | [User-access setup](docs/specs/user-access/setup.md) |
| Dataset, query and refresh API | [HTTP contract](docs/specs/data-api/http-contract.md) |
| Offline baseline verification | [National](docs/specs/national-data-verification/verification.md) · [Facility/generator](docs/specs/facility-generator-verification/verification.md) |
| Challenge requirements and evidence | [Challenge index](docs/challenge/README.md) |
| My contributions, AI workflow, corrections and manual verification | [Engineering Notes](NOTES.md) |
| Decisions, engineering history and conventions | [Decisions](DECISIONS.md) · [Devlog](docs/devlog/) · [Conventions](docs/context/conventions.md) |

Run `make help` for all backend commands.
