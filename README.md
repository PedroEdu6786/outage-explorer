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
Parquet datasets and DuckDB executes analytical SQL. Backend hosting and the
final remote-read/staging strategy remain open. See the
[storage and query-engine decision](docs/adr/0001-s3-parquet-duckdb.md).

Current repository scope: the data connector, data model, and backend API.
Frontend work is deferred. See [project context](docs/context/overview.md).

Codex session devlogs are configured in `.codex/hooks.json`. Review and trust
the two hooks through `/hooks` to enable them. See
[devlog behavior and tests](docs/context/conventions.md#automatic-codex-devlog).
