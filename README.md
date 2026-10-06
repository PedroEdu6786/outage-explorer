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
Python/Flask with [EC2 as the deployment target](docs/adr/0038-ec2-deployment-local-development.md)
and [PostgreSQL on Amazon RDS](docs/adr/0032-postgresql-on-rds.md)
for operational records.
DuckDB scans modeled Parquet through a bounded local disk cache
([ADR-0008](docs/adr/0008-local-parquet-file-cache.md)). Development runs locally;
no EC2 instance is required or blocks local implementation and testing.
EC2 deployment configuration and query isolation remain to be finalized. The earlier
SQLite-specific EC2/EBS storage proposal in ADR-0011 no longer applies. See the
[storage and query-engine decision](docs/adr/0001-s3-parquet-duckdb.md).

Amazon Cognito User Pools is selected for managed login and OAuth2 token
issuance through Authorization Code with PKCE. Our PostgreSQL tables own application
permissions ([ADR-0018](docs/adr/0018-cognito-authentication.md)). The user confirmed
Cognito setup and the RDS connection completed on October 3, 2026. Application
authentication is implemented and controlled-tested; real managed-login acceptance
remains pending.

Current repository scope: the data connector, data model, and backend API.
The web client will live in a separate repository using React, Next.js,
TypeScript, Tailwind and the existing Figma design. The
[Astra UI handoff](docs/context/ui-client/README.md) contains the starting prompt
and portable context documents; client implementation remains pending.
See [project context](docs/context/overview.md) and
[ADR-0039](docs/adr/0039-separate-ui-client-atomic-design.md).

Use the [challenge discussion index](docs/challenge/README.md) to review criteria
and individual evidence-based investigations. [FINDINGS.md](FINDINGS.md) tracks
reconciliation and anomaly findings, starting with the facility row-count gap.

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

Interactive API documentation is available at <http://127.0.0.1:8000/api/docs>.
Import <http://127.0.0.1:8000/api/openapi.json> into Postman for the complete
OpenAPI 3.1 contract, including health, authentication, datasets, SQL and refresh.
Run `make setup` after updating dependencies. Documentation is available even
when auth/data services are disabled; those operations still require their normal
enablement and configured resources.

To test protected operations in Swagger, sign in through `/api/auth/login` in the
same browser on the backend origin. Swagger sends the existing session cookie.
Use `/api/auth/session` to obtain `csrf_token`, then supply `X-CSRF-Token` and
the exact configured `Origin` for POST requests. Refresh requires Admin access;
executing it starts real background work. Logout invalidates the current session.

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

Run all quality checks, or just the tests, with disposable PostgreSQL and Chromium:

```sh
make test-postgres
docker exec outage-explorer-test-postgres pg_isready -U outage_test -d postgres
export OUTAGE_TEST_POSTGRES_DSN='host=127.0.0.1 port=55439 dbname=postgres user=outage_test password=controlled-test-only sslmode=disable'
make test-browser-setup
make check
make test
make test-postgres-stop
```

An existing disposable loopback PostgreSQL instance also works with an explicit
test DSN. Missing database/browser setup fails required checks. CI provisions
PostgreSQL and Chromium for Python 3.12/3.14; required tests use controlled
provider transport and receive no cloud credentials.

Configured auth now supports fresh per-physical-connection IAM signing, explicit
DSN/local/password modes, public or confidential Cognito PKCE, and reusable
HTTP authentication/CSRF/query-and-JSON guards. Follow the
[user-access setup runbook](docs/specs/user-access/setup.md),
[HTTP contract](docs/specs/user-access/http-contract.md), and
[verification record](docs/specs/user-access/verification.md). Real three-persona
managed login/browser acceptance remains pending; the separate UI and downstream
analytical/refresh endpoints remain outside this auth phase.

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

See the [connector flow diagrams](docs/specs/data-connector/diagrams.md) for the
planned workflow, implemented components, and implementation sequence.

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

The EIA source adapter uses pinned HTTPX with an explicitly injected transport.
It retrieves allowlisted routes sequentially with caller-supplied limits,
bounded retries, safe credential handling, and replayable page/row identities.
Controlled fixtures exercise pagination, malformed responses, coverage/total
diagnostics and exact Parquet replay. The facility total discrepancy remains
visible without excusing failed pages. The explicit contributor command below constructs a live transport only when invoked.
Live ordering/pagination and production budgets still need evidence.

See the [task breakdown](docs/specs/data-connector/tasks.md) for progress and
remaining work. The local contributor pipeline is runnable; production enablement,
Controlled S3 graph persistence/recovery is implemented; configured-bucket
verification, authorized durable refresh and publication remain pending.
The [facility row-count investigation](docs/challenge/001-facility-row-count.md)
resumed on October 3 with sample replay and bounded live probes. It remains
separate from failed-page and storage-integrity handling; this investigation
does not change the connector's accepted nonblocking treatment of that discrepancy.

The development [AWS setup record](docs/specs/data-connector/aws-setup.md)
documents the confirmed `outage-explorer` profile and `s3://arkham-outage-explorer/data/`
target, successful S3 Parquet round-trip checks, and user-confirmed RDS/Cognito setup. Nonsecret
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

### Build a connector candidate and store it in S3

After `make setup`, inspect the command without credentials or source/storage work:

```sh
make connector-help
# Direct CLI equivalent:
.venv/bin/build-connector-candidate --help
# Equivalent without reinstalling the console entry point:
.venv/bin/python -m outage_explorer.entrypoints.cli.connector_startup --help
```

The default run retrieves EIA, verifies a local candidate, then uploads and
fully verifies its complete graph in S3 ([ADR-0042](docs/adr/0042-connector-cli-default-s3-persistence.md)).
Export `EIA_API_KEY`, `OUTAGE_S3_BUCKET`, `OUTAGE_S3_PREFIX`, `AWS_REGION`, and
AWS credentials/profile into the process environment first. `make setup` installs
Boto3 with CRT support for profiles created with `aws login`. For local profile use:

```sh
export AWS_PROFILE=outage-explorer AWS_REGION=us-east-1
export OUTAGE_S3_BUCKET=arkham-outage-explorer OUTAGE_S3_PREFIX=data/
# Export your EIA_API_KEY separately; never put it in the command arguments.
```

Use `make connector LOCAL_ONLY=1 ...` or CLI `--local-only` to build a local
candidate without AWS. The connector does **not** load `.env` automatically and
never accepts the key as a command argument or JSON field. Resource limits have immutable typed
defaults in [settings.py](src/outage_explorer/settings.py), with optional
`--config PATH` JSON overrides ([ADR-0041](docs/adr/0041-connector-defaults-and-json-configuration.md)).
`OUTAGE_CONNECTOR_*` environment variables are no longer read; move any custom
budgets into the JSON file.

Defaults admit the accepted 183-day initial interval: 500 rows per page,
30,000 aggregate source rows, 100 pages, 200 request attempts, up to three
attempts per request, and a 1,800-second retrieval/model/replay budget. Requests
have a 10-second timeout. Source response/output caps are 30/40 MB; artifact
storage is capped at 256 MB, with 256 MB of logical buffer admission and 600 MB
of temporary/staging admission. Modeling permits 30,000 incoming, prior and
output rows. Endpoint and S3 workers still default to one.
S3 transfer/replay has a separate 1,800-second budget, 10-second request timeouts
and 1.6 GB of aggregate attempted wire bytes. These are bounded contributor
validation allowances, **not measured live/production limits**; successful full
initial-interval verification remains pending. JSON can override individual
limits, including smaller budgets. Configuration and inclusive ISO dates are
validated before staging storage or HTTP transport construction.

```sh
make connector START=2026-04-02 END=2026-10-01
```

This command uses typed defaults and requires the exported EIA/S3 configuration
above. See [ADR-0048](docs/adr/0048-initial-interval-connector-defaults.md).

```sh
make connector START=2026-09-01 END=2026-09-01

# Explicit local-only build (no S3 configuration or AWS credentials needed):
make connector LOCAL_ONLY=1 START=2026-09-01 END=2026-09-01

# Optional JSON configuration and explicit overrides:
make connector CONFIG=connector.config.example.json
make connector CONFIG=connector.config.example.json END=2026-09-01 STAGING=data/connector-one-day

# One-day live smoke profile with larger pages and bounded request retries:
make connector CONFIG=connector-smoke.json

# Direct CLI equivalents:
.venv/bin/build-connector-candidate \
  --start 2026-09-01 --end 2026-09-02 --staging data/connector-local

# Supply all nonsecret run configuration in a file:
.venv/bin/build-connector-candidate --config connector.config.example.json

# Explicit run flags override corresponding file values:
.venv/bin/build-connector-candidate --config connector.config.example.json \
  --end 2026-09-01 --staging data/connector-one-day

# Rerun against an explicit eligible prior from the SAME staging store:
.venv/bin/build-connector-candidate \
  --start 2026-09-01 --end 2026-09-02 --staging data/connector-local \
  --prior '<manifest-sha256>:<byte-count>'
```

`make connector` forwards to the same CLI and persists to S3 by default. The
CLI default is also durable; `--local-only` opts out, while `LOCAL_ONLY=1` supplies
that flag through Make. Without `CONFIG`, staging defaults to
`data/connector-local`; with `CONFIG`, the file's staging value is preserved unless
you pass `STAGING=...`. Dates remain explicit through `START`/`END` or the file.
Use `PRIOR='<manifest-sha256>:<byte-count>'` for a rerun. Export `EIA_API_KEY`
before invoking Make; neither entry point loads `.env` automatically.

The optional [smoke profile](connector-smoke.json) uses 100 rows/page, a 10-second
request timeout, up to 3 attempts and a 120-second per-route deadline for
September 1, 2026. A bounded live run with this profile verified 1 national,
55 facility and 95 generator rows on October 4; this does not establish larger
intervals or production limits. See [retrieval troubleshooting](docs/specs/data-connector/troubleshooting.md).

Use [connector.config.example.json](connector.config.example.json) as a complete
reference, or provide only the fields to override:

```json
{
  "start": "2026-09-01",
  "end": "2026-09-02",
  "staging": "data/connector-local",
  "source": {"page_rows": 100, "timeout_seconds": 10}
}
```

The optional top-level keys are `start`, `end`, `staging`, `prior`, `source`,
`artifact`, `model`, `workers`, and `report_bytes`. The first four are strings; `prior` uses
the same exact reference format as the flag. Omit it for an initial candidate.
`source`, `artifact`, `model` and `workers` are objects whose fields override individual
typed defaults; `report_bytes` caps combined progress/final report bytes.
Dates and staging must be supplied by the file or flags. Relative file/staging
paths resolve from the current working directory. Precedence is **explicit run
flags → JSON fields → typed resource defaults**.

The file must be a UTF-8 JSON object of at most 64 KiB. Unknown or duplicate keys,
invalid types, nonpositive/noninteger limits, and unreadable/malformed files fail
with exit 2 before connector work. Resource sections may be empty. Keep secrets
outside the file. `--help` does not open it or require credentials.

Connector commands now print timestamped step-by-step logs to **stderr** by
default: EIA routes/pages/retries, local collection, comparison and skip/retention
counts, verification, and S3 transfer/readback for default runs and explicit persist/recover.
Final status and manifest references stay on stdout. To save both streams:

```sh
make connector CONFIG=connector-smoke.json 2>&1 | tee connector-run.log
```

Valid conflicts use the last valid row in recorded source order; duplicates and
invalid rows are skipped, with prior valid rows retained where required. Existing
S3 objects are skipped only after identical bytes are verified; conflicting bytes
abort without overwriting. Logs omit credentials, request URLs and raw records.
See [execution logging](docs/specs/data-connector/logging.md).

Successful output prints the exact manifest reference. Content-addressed immutable
objects live under `STAGING/objects/`; each generated run has separate
`STAGING/runs/RUN_ID/progress-NN.json` and `report.json`. There is no mutable active
pointer. Preserve the entire store for inherited evidence and manifest ancestors;
copying only the newest manifest is insufficient. Reopening uses exact references
and verifies the bounded graph without EIA. Very long histories may require larger
explicit graph budgets; budget exhaustion fails rather than deleting old output.
No automatic pruning is performed.

Reports include interval, run/generation identity, stage, safe failure code,
verified manifest reference, source totals/received/observed coverage, and model
selected/excluded/duplicate/superseded/reason counts. Retained-invalid,
retained-absent and carried-outside-interval counts stay separate. Source totals
and observed rosters do not prove upstream completeness. A facility-total mismatch
alone is diagnostic; a known failed page is a failure. Progress files are snapshots,
not durable backend refresh outcomes; only the final report records completion.

Default CLI success prints `candidate_s3_verified` only after complete durable
readback/replay; its `local_outcome` identifies `candidate_verified` or
`retained_all_excluded`. Local JSON reports and `--local-only` outcomes are:

| Outcome / exit | Meaning |
| --- | --- |
| `candidate_verified` / 0 | Persisted and reopened local candidate, plus written final report. |
| `retained_all_excluded` / 0 | Every incoming route excluded; prior modeled rows retained. Continue using the last eligible candidate as `--prior`. |
| `failed` / 1 | Retrieval, resource, representation, integrity, input or report failure; no confirmed completed candidate. |
| Configuration/arguments / 2 | Invalid input rejected before connector I/O. |
| Interrupted / 130 | Cooperative interruption; no publication. Abrupt process termination may leave only progress or orphan immutable objects. |

A persistence failure returns a nonzero exit, prints `failed persistence` and
`local_manifest=SHA256:BYTE_COUNT` for source-disabled retry with
`--operation persist`, and preserves the verified local candidate/report. A
successful local report alone does not confirm S3 durability. Missing S3 target
configuration fails before EIA work; credential resolution/storage errors may
occur afterward. No silent local fallback is used.

Every outcome has `published: false`. Reports omit credentials, request URLs and
raw exceptions. Report-write failure returns failure and may leave no final report,
even when artifacts were already written; it never confirms success. Earlier
objects and reports remain intact. Without a prior candidate, every grain must
have usable output. Later runs replace valid revisions, preserve invalid/absent
keys with their original provenance, and retain wholly excluded routes. Equal
inputs may have different identities/timestamps and manifest bytes.

The command is a contributor operation, not an authorized refresh endpoint or
initial live publication. The accepted product initial interval remains April 2–
October 1, 2026 inclusive. Configured-bucket durability checks, authorization,
atomic activation and reader pinning remain later work; no PostgreSQL, Cognito, S3 or EC2 connection is
required by the controlled tests. Run all checks with `make check`, or the focused
local connector tests with:

```sh
.venv/bin/python -m pytest tests/unit/test_connector_service.py tests/unit/test_connector_settings.py tests/integration/test_connector_cli.py tests/integration/test_connector_reruns.py
```

### Recorded source profile

Initial live EIA metadata snapshots (local `data/exploration/eia-metadata/`) describe
the national, facility, and generator routes. The configured personal API key
subsequently succeeded for all three data routes. The
30-day source profile (local `data/exploration/eia-profile.json`) records request
parameters, retrieval timestamps, snapshot hashes, field types, candidate-key
checks, and daily comparisons for September 1–30, 2026. Sanitized response
snapshots are stored locally in Git-ignored `data/exploration/eia-samples/`;
they exclude EIA's echoed request credentials. These exploratory JSON files
are evidence for modeling and local Parquet regression tests; live ingestion
and durable publication remain unimplemented.
All three snapshots and supporting documents have byte-identical versioned
copies in `data/verification/{national,facility,generator}-2026-09/` for
clean-checkout replay. These existing regression fixtures are the exception to
ignoring `/data/`: tests require their exact source rows and integrity manifests.
Exploratory copies, investigation downloads and connector runs stay local.
New downloaded data is ignored by default; add a fixture deliberately only when
required by a reproducible regression test.

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

Codex devlogs are configured in `.codex/hooks.json`: `Stop` buffers summaries
and `PreToolUse` writes them before a Codex `git commit`. Review and enable
both hooks through `/hooks`; new notes pause the commit for review and staging. See
[devlog behavior and tests](docs/context/conventions.md#automatic-codex-devlog).

### Persist and recover connector artifacts

Default candidate CLI runs automatically perform persistence after local
verification. Explicit `--local-only` creation remains AWS-independent. Default
and explicit durable operations require configured `OUTAGE_S3_BUCKET`, `OUTAGE_S3_PREFIX` and `AWS_REGION`, plus
an SDK credential provider (`AWS_PROFILE` for local profiles, or a workload
role). `.env` is not automatically loaded. Save the exact manifest reference
printed by a verified candidate, together with its bucket/prefix configuration.

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.connector_startup \
  --operation persist --staging data/connector-local \
  --manifest SHA256:BYTE_COUNT

# A new empty staging location; EIA_API_KEY is unnecessary.
.venv/bin/python -m outage_explorer.entrypoints.cli.connector_startup \
  --operation recover --staging data/connector-recovered \
  --manifest SHA256:BYTE_COUNT
```

Replace `SHA256:BYTE_COUNT` with the exact saved lowercase digest and byte count.
Optional `--config PATH` applies existing artifact/model bounds and staging;
`--staging` overrides the file. Persist/recover need no dates and do not retrieve
EIA. Recovery requires absent or empty staging; use a fresh location after a
failed recovery. Exit codes remain 0 verified, 1 failed, 2 invalid configuration
or arguments, and 130 interrupted. Failures print sanitized messages and never
print a verified receipt. Successful output says `persist_verified` or
`recover_verified`, with the exact manifest and graph object/byte counts.

Persistence verifies all exact dependencies (including ancestor manifests,
inherited raw/page evidence and unchanged modeled files) before the final
manifest, then restores and fully replays the durable graph in fresh staging.
Writes use conditional creation and compare SHA-256/bytes; identical retries
verify existing objects and conflicting bytes fail without overwriting them.
A manifest may exist after an interrupted final verification, but its existence
alone is not a verified receipt or an active-generation pointer. No deletion,
bucket listing, PostgreSQL refresh-outcome persistence or publication is added.

The automated suites use controlled SDK behavior, including default one-command candidate-to-S3 execution and local-preserving persistence failures. See
[recovery verification](docs/specs/data-connector/recovery-verification.md) for
coverage and [configured-bucket checks](docs/specs/data-connector/aws-setup.md)
for separately authorized Phase 6 work. No automated local checkpoint establishes
live AWS, deployed-role or full backend recovery guarantees.

### Bounded connector concurrency and measured scope

Optional JSON `workers` settings independently choose `endpoint_workers` and
`s3_workers` from 1–3 (both default to 1). For example:

```json
{"workers": {"endpoint_workers": 3, "s3_workers": 3}}
```

Pages stay sequential within each route. Aggregate retrieval, object, byte,
request, staging and logical buffer limits are shared across workers; errors and
interruptions cancel new admission and join workers before returning. Modeling,
combined manifests and final receipt verification remain coordinated. S3 final
root creation follows successful dependency transfers, then full durable replay.
The same transfer setting applies to default candidate runs and explicit
persist/recover. `workers.memory_bytes` and `temporary_bytes` may explicitly
override logical admission envelopes; these are not OS process RSS/disk limits.

Controlled overlap/equivalence tests and authorized one-day/September live runs
are recorded in [live verification](docs/specs/data-connector/live-verification.md)
and [resource evidence](docs/specs/data-connector/resource-evidence.md). Configured
S3 readback and source-disabled inherited recovery passed. All six connector
phases are complete: a fresh April2–October1 live candidate verified all three
grains, and exact source-disabled configured-S3 reconstruction verified its full
durable graph. The earlier interrupted attempt is retained as historical evidence.
See the [initial recovery measurement](docs/specs/data-connector/evidence/2026-10-04/initial-interval-recovery.json).
No production enablement, active publication or backend recovery follows.


### Fetch pages and save S3 files in parallel

Use the plain command (no JSON profile required):

```sh
make connector START=2026-04-02 END=2026-10-01 FETCH_WORKERS=3 S3_WORKERS=3
```

`FETCH_WORKERS` runs up to three page requests concurrently **within each route**;
endpoint workers remain1 by default. `S3_WORKERS` runs up to three independent
artifact uploads/readbacks concurrently. The CLI equivalents are `--fetch-workers`
and `--s3-workers`, which override JSON `workers.page_workers`/`workers.s3_workers`.
Both default to1; existing `workers.endpoint_workers` remains independently
configurable. Explicit local-only operation still uses `LOCAL_ONLY=1`.

Persist/recover also accept the transfer override:

```sh
make connector OPERATION=persist STAGING=path/to/staging MANIFEST=SHA256:BYTES S3_WORKERS=3
make connector OPERATION=recover STAGING=path/to/empty-staging MANIFEST=SHA256:BYTES S3_WORKERS=3
```

Pages are consumed in canonical offset/row order regardless of completion.
Short pages repair offsets using received counts; advertised totals do not end
retrieval. Every admitted request must succeed. Unused successful lookahead is
retained as sanitized, hashed transport evidence in the complete S3 graph, with
explicit fetched/unused counts; it does not become additional modeled rows.
Parallel lookahead can spend extra requests/rows/bytes, subject to the same
aggregate limits. Details: [ADR-0049](docs/adr/0049-bounded-page-prefetch-and-worker-flags.md).
These knobs do not parallelize synchronous modeling/replay or establish a speedup,
a verified full initial candidate, source snapshot consistency or production limits.

### Run the independent refresh worker

Data API Phase 3 supplies an explicit supervised worker, separate from HTTP:

```sh
.venv/bin/python -m outage_explorer.entrypoints.refresh_worker_startup
```

Configure the existing `OUTAGE_ACCESS_DATABASE_*` database settings,
`OUTAGE_REFRESH_STAGING` for private per-run local artifacts, `EIA_API_KEY`, and
`OUTAGE_S3_BUCKET`, `OUTAGE_S3_PREFIX` and `AWS_REGION` (optional `AWS_PROFILE`).
The worker validates the S3 target before source work and claims only committed
admissions. Dates and source/model interval limits, candidate deadline and
persistence deadline come from each frozen admission, independent of current
worker environment. Remaining connector resource bounds use typed initial defaults;
these are not measured production allowances.

The process polls durably, renews fenced database-time leases and reconstructs
verified pinned bases from S3. Only full verified graph persistence/readback
permits atomic all-grain publication. SIGTERM stops polling after the current
bounded operation; explicit process shutdown closes transport/SDK/database
resources. A lost claimed run is reconciled against publication history; confirmed
unpublished work becomes interrupted and requires a new Admin admission, without
automatic source retries. Imports and HTTP factories start no refresh work.
HTTP refresh endpoints arrive in data API Phase 6. This local executable and its
controlled tests do not authorize live publication or establish EC2 supervision,
measured budgets or SQL sandbox readiness.


## Data API HTTP integration

The seven operations in the [data contract](docs/specs/data-api/http-contract.md)
are implemented. Enable their transport alongside configured authentication and
apply explicit migrations to your intended database before serving requests:

```sh
.venv/bin/access-setup migrate
export OUTAGE_DATA_HTTP_ENABLED=true
export OUTAGE_REFRESH_START_DATE=2026-04-02
export OUTAGE_REFRESH_END_DATE=2026-10-01
make run
```

These commands are an operator runbook; this implementation did not migrate live
RDS or publish live data. Configured dates are captured durably at refresh
admission; request dates/selectors are rejected. Start `refresh-worker` separately
with its documented EIA/S3/staging configuration. The HTTP factory never starts it.

Without explicitly injected reviewed analytical resources, authorized previews
and SQL submissions fail closed with `503 service_unavailable`. Catalog and
durable refresh remain usable independently. A reviewed supervisor can pass
`DataHttpResources` to `build_http_app`, explicitly call `outage_data_start`, and
close `outage_data_close`; quota, cache, execution and cleanup ownership must come
from that configured composition. The default CLI startup supplies no real SQL
launcher. User-owned T1.7 validation remains separate.

For reproducible controlled acceptance, use disposable loopback PostgreSQL and
the installed Chromium browser as documented above, then run:

```sh
.venv/bin/python -m pytest tests/integration/test_data_api_http.py tests/acceptance/test_data_api_lifecycle.py tests/integration/test_refresh_recovery.py
make check
```

The HTTP tests use real PostgreSQL/Parquet and controlled source/S3/analytical
workers. They verify contract envelopes, current roles, durable acknowledgement,
refresh/query overlap and retained snapshots; they do not prove Linux isolation,
live provider readiness, deployment or measured production resource budgets.

### Explicit analytical startup

For the already provisioned and approved local `outage-runtime` Colima service:

```sh
make run-analytical
# API: http://localhost:8000; keep the command running. Ctrl+C stops it.
# Or, from another terminal:
make stop-analytical
```

Use `run-analytical` for preview and SQL. `make run` starts a separate macOS Flask
process without analytical resources, whose preview/SQL calls return 503. Do not
run both on port 8000. The analytical target restarts only the existing configured
service and renews its trusted application credentials every minute from the
existing local AWS login. A private SDK credential process makes both IAM signing
and long-lived S3 clients consume renewed credentials without restarting the API.
It does not provision a runtime, start refresh, or fall back to Flask. Restart
discards process-owned cursors/results. The guest must retain its reviewed
`/run/outage-api` configuration; guest reboot requires reactivation. Credentials
are never logged or supplied to parser/analytical workers. If the local AWS login
expires, renew that existing login; the launcher retries credential export. See
[local activation evidence](docs/specs/data-api/runtime-evidence.md).

Analytical-runtime Phase 3 delivers an inert `build_analytical_resources` builder
and a process-owned supervisor. Imports and HTTP factories create no cache,
Docker process or cleanup thread. Its explicit executable accepts a bounded
nonsecret profile/evidence JSON:

```sh
.venv/bin/python -m outage_explorer.entrypoints.http.analytical_startup --help
```

After readiness and separate enablement authorization, its intended invocation
is `--config /private/tmp/outage-runtime-reviewed.json`; authentication/data HTTP
and trusted PostgreSQL/S3 settings remain host configuration. The local executable
supports one loopback serving process, explicit start/close, periodic worker
recovery and preview/result expiry, safe rollback and restart loss of ephemeral
IDs. It rejects reloaders, inherited resources and multiple serving processes;
it does not own the refresh worker.

API analytical execution remains gated: tmpfs-smoke cannot pass readiness, while
quota-disk now supports a separately provisioned finite ext4 filesystem on native
Linux Docker. Actual isolation/storage/measurement evidence remains unreviewed.
Controlled implementation tests do not authorize API enablement. See the
[profile, readiness and local lifecycle contract](infrastructure/analytical-worker/README.md)
and the remaining [runtime tasks](docs/specs/analytical-runtime/tasks.md).
