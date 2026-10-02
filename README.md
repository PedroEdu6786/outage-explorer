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
Python/FastAPI and SQLite for operational records, with Amazon ECS hosting selected.
DuckDB scans modeled Parquet through a bounded local disk cache
([ADR-0008](docs/adr/0008-local-parquet-file-cache.md)). ECS launch type and durable SQLite storage remain to be finalized
([ADR-0011](docs/adr/0011-ecs-hosting.md)). See the
[storage and query-engine decision](docs/adr/0001-s3-parquet-duckdb.md).

Amazon Cognito User Pools is selected for managed login and OAuth2 token
issuance through Authorization Code with PKCE. Our SQLite tables own application
permissions ([ADR-0018](docs/adr/0018-cognito-authentication.md)). Integration
and AWS provisioning are not implemented yet.

Current repository scope: the data connector, data model, and backend API.
Frontend work is deferred. See [project context](docs/context/overview.md).

For local EIA access, copy `.env.example` to `.env` if `.env` does not already
exist, then set `EIA_API_KEY` to your EIA key. `.env` is excluded from Git.
No application or automatic dotenv loader is implemented yet.

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
