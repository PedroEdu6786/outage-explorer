# ADR-0008: Query Parquet through a bounded local disk cache

Status: **Accepted under delegated selection**

Date: 2026-10-01

## Context

The user delegated the remaining loading choice with a preference for speed
and robustness. S3 remains the durable home for published Parquet and
ADR-0007 establishes batch processing with bounded resources. This decision
resolves the previously open loading path in ADR-0001 and ADR-0007.

## Options considered

| Option | Benefits | Tradeoffs |
| --- | --- | --- |
| Direct S3 scans | Can transfer only needed Parquet ranges; avoids maintaining complete local copies | Query execution depends on remote reads; user-SQL workers need a constrained network/credential path |
| Download files for every query | Keeps S3 access outside query execution | Repeats transfer and preparation for unchanged inputs |
| Bounded local Parquet file cache | Reuses downloaded inputs across queries; keeps query workers without network or S3 credentials | Requires disk capacity, coordinated downloads, reader references and eviction; cold queries still download whole required files |

## Decision

Use a bounded, disposable local disk cache of immutable modeled Parquet
files. DuckDB scans those files directly in batches, without importing whole
datasets into in-memory tables. Cache files, not query results.

1. Authorize the complete request and pin one published manifest before
   accessing analytical objects, including cache hits. Resolve its exact
   permitted modeled inputs through trusted metadata.
2. A trusted loader reuses verified cache entries. For misses, stream S3
   downloads to disk-backed temporary files, verify expected size/content
   hash, then atomically make the completed entry available. Partial or
   mismatched downloads must never be served. Coordinate requests for the
   same object across backend processes to avoid duplicate downloads.
3. Identify entries by trusted immutable object identity and expected content
   hash. Snapshot manifests select inputs; never use an unversioned `latest`
   directory or mix files from different snapshots accidentally.
4. Pin the local files before worker launch. Expose only that request's
   authorized inputs read-only to the isolated DuckDB worker, not the entire
   cache directory. The worker receives no S3 credentials or network access.
5. Release local references after use and retain entries for reuse within
   the byte quota. Evict unpinned entries by least recent use. Coordinate
   reference acquisition with eviction; active files cannot be reclaimed.
6. Reserve capacity for downloads, query spill and refresh staging separately
   from the cache quota and durable SQLite data. If required inputs cannot
   fit safely, fail preparation with a bounded resource error. Do not silently
   switch the worker to direct remote access.

Refresh continues to publish automatically on success. New queries resolve
the new manifest; running queries keep their original manifest and local
references. Background cache prewarming is not required for publication.

## Consequences

Reusing cached files removes repeated S3 transfers for those files while
present. This is the expected performance advantage, not a measured claim
that every query is faster. A cold selective query may be faster with direct
S3 range reads. Neither local nor remote scans remove query working-memory
requirements or spill limitations.

S3 is authoritative. Cache loss or backend replacement triggers on-demand
rehydration without contacting EIA. Recovery ignores incomplete entries and
verifies retained files before reuse. A missing uncached object still needs
S3; this does not promise API availability during S3 or operational-store
outages. Local eviction is separate from durable snapshot/evidence retention.

Exact cache size, file layout, worker runtime and shared disk budgets remain
to be measured. Verify cold/warm latency, bytes transferred, peak memory,
disk exhaustion, refresh transitions, concurrent download/eviction and role
isolation. Revisit the choice if representative inputs cannot fit or cold
transfer dominates. No cache implementation or performance benchmark exists
yet.

## References

- [ADR-0001 — Persistent Parquet and DuckDB](0001-s3-parquet-duckdb.md)
- [ADR-0007 — Bounded query execution](0007-bounded-parquet-query-execution.md)
- [DuckDB remote I/O guidance](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads)
- [Parquet scanning](https://duckdb.org/docs/current/data/parquet/overview)
- [DuckDB execution isolation](https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview)
