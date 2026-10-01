# ADR-0001: Store Parquet in Amazon S3 and query it with DuckDB

Status: **Accepted**

Date: 2026-10-01

## Context

Outage Explorer must preserve ingested EIA data across backend redeployments
and serve all authorized users through one active backend replica. Raw and
modeled datasets will use Parquet. Ordinary queries must work without
contacting EIA after successful ingestion.

The user requested that the S3 + DuckDB decision be kept in the project after
comparing it with DuckDB backed only by persistent backend disk. This records
that selection; it does not approve every tool in the council's draft plan.

## Options considered

| Option | Advantages | Costs and limitations |
| --- | --- | --- |
| Amazon S3 + Parquet + DuckDB | Durable datasets have a lifecycle separate from backend instances; managed object storage; preserves the required file format | Network dependency, request/storage/transfer costs, bucket permissions and lifecycle configuration |
| Persistent backend disk + Parquet/DuckDB | Local reads; fewer remote storage interactions | Must preserve/reattach disk, manage capacity and backups, and define host-loss recovery |
| Self-hosted S3-compatible storage + DuckDB | Open-source provider option such as SeaweedFS | Requires operating the storage service, persistent disks, backups and recovery; not selected |

## Decision

- Use **Amazon S3** as the authoritative persistent home for raw and modeled
  **Parquet** datasets.
- Use **DuckDB** as the analytical SQL engine in backend-controlled execution.
  It need not permanently import the datasets into a `.duckdb` database.
- Keep **one active backend replica**, serving multiple authorized clients.
  Users access datasets through the API, not through client-side Parquet copies.
- Contact EIA during ingestion/refresh. Ordinary queries use published data
  from our storage. Admin controls refresh; Viewer is national-only and
  Analyst/Admin may query all analytical datasets.
- Keep backend analytical staging disposable. Losing staging must be
  recoverable from S3 without another EIA extraction.
- Persist operational records separately: accounts, sessions, refresh state,
  snapshot references and evidence pins are not automatically persisted by
  storing Parquet in S3. Their database and persistence mechanism remain open.

## Data flow and remaining choices

```text
Admin refresh → EIA → validation/modeling → Parquet snapshots in S3
User query → API authentication/authorization → DuckDB → API results
                                                  ↑
                          published Parquet from S3
```

The final path between S3 and DuckDB is **not selected**. DuckDB supports direct
remote Parquet reads. The current security proposal instead uses a trusted
loader, authorized temporary files and isolated workers with materialized
in-memory tables. Reusable local snapshots are an optional optimization,
deferred until transfer, load time, memory and query measurements justify them.

Direct S3 views alone do not enforce application roles. Any selected path must
validate and authorize the complete query before analytical access, restrict
accessible datasets, and enforce execution/resource boundaries. Choosing S3
and DuckDB does not settle SQLGlot compatibility, worker isolation, exact SQL
surface, credentials or cache lifecycle.

The proposed publication flow uploads and verifies a complete immutable
snapshot before publishing its reference. Readers stay on one snapshot;
failed refreshes must preserve the previous published data. Exact refresh and
retention policies remain under review in the plan.

## Consequences

- Backend redeployment preserves S3 objects provided infrastructure lifecycle
  configuration retains the bucket and data; persistence is not protection
  against deliberate deletion or misconfigured retention.
- DuckDB supports in-memory and persistent database modes. A persistent
  `.duckdb` file would still need durable underlying storage; it would not
  replace the challenge's required Parquet artifacts.
- EIA-independent querying does not promise availability during an S3 outage.
- No additional database server is required for DuckDB query execution.
  One replica still permits multiple clients; measured concurrency is open.
- AWS region, bucket security/retention/recovery settings, backend hosting,
  development storage setup, operational database and execution runtime remain
  open. Selecting S3 does not select an AWS compute service.
- No cloud resources or application implementation have been created by this
  decision. Revisit storage/engine choices if measured workload, cost,
  availability or SQL-isolation requirements cannot be met.

## References

- [DuckDB S3 support](https://duckdb.org/docs/current/core_extensions/httpfs/s3api)
- [DuckDB connection and persistence](https://duckdb.org/docs/current/connect/overview)
- [DuckDB Parquet support](https://duckdb.org/docs/current/data/parquet/overview)
- [Backend specification](../specs/outage-explorer-backend/spec.md)
- [Backend design plan](../specs/outage-explorer-backend/plan.md)
- [Council decision history](../specs/outage-explorer-backend/council/03-decisions.md)
