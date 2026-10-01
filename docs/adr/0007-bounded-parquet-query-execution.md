# ADR-0007: Query Parquet with bounded memory and temporary disk

Status: **Accepted**

Date: 2026-10-01

## Context

The user accepted batch-based Parquet processing with memory, temporary disk,
concurrency and result limits after discussing DuckDB memory usage. Streaming
avoids loading the entire input first, but intermediate query state can still
exhaust resources.

## Options considered

- Scan modeled Parquet in batches and bound execution resources: selected;
  avoids a mandatory full-dataset import before each query.
- Materialize every permitted dataset into in-memory tables before querying:
  adds loading and memory costs without a demonstrated workload need.
- Rely on streaming alone: insufficient for memory-intensive joins, sorts,
  aggregations and windows.

## Decision

- Query modeled Parquet directly, decompressing and decoding required data
  in batches. Do not require full-dataset in-memory materialization.
- Set a DuckDB memory budget with headroom inside an enforced worker memory
  limit. Streaming and DuckDB's memory setting do not bound every allocation.
- Provide bounded, disk-backed temporary storage for supported spill
  operations. Do not assume every operator or query can spill successfully.
- Limit concurrent queries and account for API and refresh resource use.
- Fetch and serialize results in bounded batches under row and byte limits;
  avoid collecting unrestricted results in Python memory.
- Resource exhaustion must fail the query cleanly without taking down the
  API. Verify this behavior on the chosen runtime before claiming it works.

## Consequences and open choices

Direct S3 reads versus temporary local Parquet staging remains open. Both
use memory for execution; neither requires importing all input into tables.
If staging is selected, stream downloads to actual disk-backed storage.
Reusable file caching, exact budgets, worker runtime and spill quotas remain
unselected and require measurement.

The earlier plan's mandatory in-memory import proposal is replaced. For
local scans, the worker must retain read access to its exact authorized
Parquet inputs; disabling all file access would break those scans. Query
authorization and worker isolation remain required. This acceptance does
not select their implementation or authorize broader filesystem access.

## References

- [DuckDB Parquet support](https://duckdb.org/docs/current/data/parquet/overview)
- [Larger-than-memory execution](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads)
- [DuckDB memory management](https://duckdb.org/2024/07/09/memory-management)
- [Backend plan](../specs/outage-explorer-backend/plan.md)
