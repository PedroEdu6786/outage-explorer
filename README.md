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

### Verify the national baseline offline

The fixed September 1–30, 2026 national verification is implemented. From the
repository root, run:

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.startup
```

It writes `build/national-verification/report.json` and `report.md`. After
`make setup`, the equivalent command is `.venv/bin/verify-national-data`.
Use `--output-directory PATH` to choose another report directory and
`--evidence-bundle PATH/manifest.json` for an explicitly identified test bundle.
The default uses the [versioned evidence bundle](data/verification/national-2026-09/manifest.json);
it requires no API key, network, database or clock-dependent date selection.

The reports show both percentages, exact calculations, source positions,
exclusions, all 30 dates and evidence limits. A difference between the displayed
percentages does not fail verification. Evidence-integrity, contract and
arithmetic failures return a nonzero exit status. Existing report files at the
destination are replaced on success; source evidence cannot be an output target.

See the [observation contract](docs/specs/national-data-verification/contract.md)
and [verification findings](docs/specs/national-data-verification/verification.md).
This contributor workflow establishes national processing behavior; backend
data delivery, live refresh and product authorization remain pending.

### Verify facility and generator baselines offline

The same verification is available per facility and per facility-scoped generator:

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.facility_startup
.venv/bin/python -m outage_explorer.entrypoints.cli.generator_startup
```

After `make setup`, use `.venv/bin/verify-facility-data` and
`.venv/bin/verify-generator-data`. Both accept `--evidence-bundle` and
`--output-directory` and default to their versioned September 2026 bundles.
Reports are written to `build/facility-verification/` and
`build/generator-verification/` as `report.json` and `report.md`.

They reuse national validation, exact arithmetic and last-valid-record selection,
with separate facility/date and facility/generator/date identities. Reports show
source names and identifiers, both percentages, row dispositions and every date
for each observed entity. Missing entity-days remain unavailable, distinct from
valid zero outage. All 1,650 facility and 2,850 generator rows are usable in this
baseline, covering 55 facilities and 95 facility/generator pairs over 30 days.

**Evidence limitation:** the facility response reports 2,850 total rows while
returning 1,650. Both counts remain visible; observed-entity coverage does not
prove upstream completeness. These are offline contributor reports; live ingestion,
cross-grain reconciliation and authenticated product delivery remain pending.
See the [detail contracts](docs/specs/facility-generator-verification/contract.md)
and [verification findings](docs/specs/facility-generator-verification/verification.md).

### Data connector implementation design

The [connector specification](docs/specs/data-connector/spec.md) and
[implementation plan](docs/specs/data-connector/plan.md) develop the next slice:
live retrieval for all three routes, raw/modeled Parquet, generation evidence,
and safe refresh/publication using the verified observation policies.
Implementation includes the bounded pure transformation in
`domain/refresh.py`: per-grain validation and selection, provenance-preserving
replacement/retention, and quality accounting. Inputs must already be sanitized;
these helpers operate on complete bounded groups, not accumulated history.
The local Parquet adapters now preserve raw pages/observations, modeled values,
dispositions and merge ledgers using explicit versioned schemas. They build
date-partitioned candidates, retain original evidence, and verify hashes, schemas,
counts, exact values and cross-file keys against replayed source data. Immutable
JSON manifests can be reloaded with a new local store instance.

See the [task breakdown](docs/specs/data-connector/tasks.md) for progress and
remaining work. These are programmatic local storage adapters; live retrieval,
S3 storage, authorized durable refresh and publication are still pending.
Investigation of the known facility row-count discrepancy remains
deferred and separate from failed-page and storage-integrity handling.

The development [AWS setup record](docs/specs/data-connector/aws-setup.md)
documents the confirmed `outage-explorer` profile and `s3://arkham-outage-explorer/data/`
target, successful S3 Parquet round-trip checks, and deferred RDS/Cognito setup. Nonsecret
configuration placeholders are in `.env.example`; the cloud adapters remain
unimplemented.

[ADR-0037](docs/adr/0037-connector-initial-load-and-retention.md) records the
initial live interval (April 2–October 1, 2026 inclusive), retention of absent
keys and wholly excluded refresh datasets, and the requirement for usable output
in all three datasets before first publication. The pure foundation tests these
transformation rules and local Parquet candidates; end-to-end publication remains
to be implemented. `make setup` installs pinned PyArrow 25.0.1. Run the storage
and replay checks with:

```sh
.venv/bin/python -m pytest tests/integration/test_connector_evidence.py tests/integration/test_connector_parquet.py
```

### Recorded source profile

Initial live [EIA metadata snapshots](data/exploration/eia-metadata/) describe
the national, facility, and generator routes. The configured personal API key
subsequently succeeded for all three data routes. The
[30-day source profile](data/exploration/eia-profile.json) records request
parameters, retrieval timestamps, snapshot hashes, field types, candidate-key
checks, and daily comparisons for September 1–30, 2026. Sanitized response
snapshots are stored locally in Git-ignored `data/exploration/eia-samples/`;
they exclude EIA's echoed request credentials. These exploratory JSON files
are evidence for modeling and local Parquet regression tests; live ingestion
and durable publication remain unimplemented.
All three snapshots and supporting documents have byte-identical versioned
copies in `data/verification/{national,facility,generator}-2026-09/` for
clean-checkout replay.

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
not prove completeness. The bounded verification contracts now define these sample schemas; historical
contracts and the facility-total explanation remain unverified.

Codex session devlogs are configured in `.codex/hooks.json`. Review and trust
the two hooks through `/hooks` to enable them. See
[devlog behavior and tests](docs/context/conventions.md#automatic-codex-devlog).
