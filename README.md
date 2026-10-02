# outage-explorer
Outage Explorer lets users explore backend-stored U.S. nuclear outage data,
query datasets their role permits, and understand discrepancies between
national, facility, and generator observations.

The core promises are availability from our own storage after ingestion, trust through
reproducible evidence from actual EIA records, and access control that never
exposes facility or generator details to Viewers.

“Local data” means the application's own ingested data, served by a shared
backend to authorized users. Development runs locally; deployment must retain
data independently of disposable application containers. The current scope is
one backend replica serving all authorized users. Amazon S3 stores persistent
Parquet datasets and DuckDB executes analytical SQL. The backend uses
Python/Flask on ECS and [PostgreSQL on Amazon RDS](docs/adr/0032-postgresql-on-rds.md)
for operational records.
DuckDB scans modeled Parquet through a bounded local disk cache
([ADR-0008](docs/adr/0008-local-parquet-file-cache.md)). ECS launch type, RDS configuration,
connectivity, and query isolation remain to be finalized. The earlier
SQLite-specific EC2/EBS storage proposal in ADR-0011 no longer applies. See the
[storage and query-engine decision](docs/adr/0001-s3-parquet-duckdb.md).

Amazon Cognito User Pools is selected for managed login and OAuth2 token
issuance through Authorization Code with PKCE. Our PostgreSQL tables own application
permissions ([ADR-0018](docs/adr/0018-cognito-authentication.md)). Integration
and AWS provisioning are not implemented yet.

Current repository scope: the data connector, data model, and backend API.
Frontend work is deferred. See [project context](docs/context/overview.md).

The accepted [layered Flask monolith structure](docs/context/code-structure.md)
defines package placement, dependency rules, and agent guidance in
[AGENTS.md](AGENTS.md). See [ADR-0030](docs/adr/0030-layered-flask-monolith.md)
and the [architecture comparison](docs/specs/outage-explorer-backend/architecture-options.md).
Flask supersedes FastAPI under [ADR-0028](docs/adr/0028-python-flask-backend.md).
Runtime and storage details remain to be finalized.

For local EIA access, copy `.env.example` to `.env` if `.env` does not already
exist, then set `EIA_API_KEY` to your EIA key. `.env` is excluded from Git.
`make run` loads `.env` through Flask's `python-dotenv` support, preserving
variables already set in your shell. The health endpoint does not need EIA
credentials. Importing the application or calling its factory does not load
dotenv files; local environment loading belongs to the Flask CLI.

## Run the health scaffold locally

Use Python 3.12 or newer on macOS/Linux (CI covers 3.12 and 3.14). On macOS,
the system `python3` may be older; select your installed supported interpreter
when creating the venv, for example `/opt/homebrew/bin/python3`.

From the repository root, setup once and start the API:

```sh
make setup
make run
```

No virtual-environment activation is needed. For a specific interpreter, use
`make setup PYTHON=/opt/homebrew/bin/python3`. On subsequent runs, just use
`make run`. Stop with Ctrl+C; choose another port with `make run PORT=8080`.

Open <http://127.0.0.1:8000/health> in your browser, or in another terminal:

```sh
make health
```

Returns HTTP 200 with JSON like:

```json
{"status":"ok","service":"outage-explorer","checked_at":"2026-10-01T12:00:00+00:00"}
```

This unauthenticated, noncached endpoint reports **process liveness**. It invokes
the injected application health service, whose clock port is implemented by an
infrastructure UTC clock. It does not check PostgreSQL, Cognito, S3, EIA, or
analytical readiness. No external credentials or database are needed for this
slice. PostgreSQL remains required when operational persistence is implemented.
Flask's local development server is not a deployment configuration.

Run all quality checks, or just the tests:

```sh
make check
make test
```

`make help` lists the available commands. The Makefile invokes tools inside
`.venv` directly; it does not change the application startup architecture.

`pytest` includes architecture rules and negative fixtures, HTTP/service tests,
startup-side-effect checks, and the existing devlog tests. CI runs the same gates.
Ruff covers the scaffold; existing devlog tooling keeps its independent
standard-library test workflow. Exact development dependency versions are in
`requirements-dev.txt`; `pyproject.toml` declares supported dependency ranges.
Update resolved versions in a clean venv and rerun all checks.

See the [health spec, plan, and tasks](docs/specs/health-endpoint/spec.md).
Automated import checks establish structural guardrails; health does not prove
authorization, publication safety, or SQL isolation, which remain unimplemented.

## Source exploration

Initial live [EIA metadata snapshots](data/exploration/eia-metadata/) describe
the national, facility, and generator routes. The configured personal API key
subsequently succeeded for all three data routes. The
[30-day source profile](data/exploration/eia-profile.json) records request
parameters, retrieval timestamps, snapshot hashes, field types, candidate-key
checks, and daily comparisons for September 1–30, 2026. Sanitized response
snapshots are stored locally in Git-ignored `data/exploration/eia-samples/`;
they exclude EIA's echoed request credentials. These exploratory JSON files
are evidence for modeling; the Parquet ingestion pipeline remains unimplemented.

| Dataset | Retrieved rows | Candidate key, unique in this sample |
| --- | ---: | --- |
| National | 30 | `period` |
| Facility | 1,650 | `period`, `facility` |
| Generator | 2,850 | `period`, `facility`, `generator` |

Measurements arrive as JSON strings: `capacity` and `outage` are MW, while
`percentOutage` is percent. Initial model candidates are a date for `period`,
text identifiers, and explicitly parsed decimal measurements. Keep
`facilityName` as a source attribute rather than an identifier, and scope
generator IDs to their facility. Final numeric precision, nullability and
historical key guarantees require broader validation.

Facility and generator capacity/outage sums equal national values on all
30 sampled dates. However, the facility response advertises `total=2850`
while returning 1,650 rows (55 per day). Pagination and completeness semantics
must be investigated before relying on that total; matching sums alone do
not prove completeness. No discrepancy explanation or final model contract
has been accepted from this initial exploration.

Codex session devlogs are configured in `.codex/hooks.json`. Review and trust
the two hooks through `/hooks` to enable them. See
[devlog behavior and tests](docs/context/conventions.md#automatic-codex-devlog).
