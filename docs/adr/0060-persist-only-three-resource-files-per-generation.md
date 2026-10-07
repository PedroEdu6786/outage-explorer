# ADR-0060: Persist only three resource Parquet files per generation

Status: **Accepted** (explicit user acceptance, October 6, 2026)

## Context

[ADR-0057](0057-single-file-modeled-datasets.md) replaced daily modeled partitions
with one modeled and one public file per resource (six dataset files per generation).
However, it explicitly preserved the historical layout for supporting artifacts:
raw source batches, page descriptors, row-level disposition decisions, and daily
merge ledgers.

In practice, a single 183-day generation (April 2–October 1, 2026) produces **1,442
distinct S3 objects**:
- 3 modeled Parquet files
- 3 public Parquet files
- 549 disposition files (183 days × 3 grains)
- 549 merge-ledger files (183 days × 3 grains)
- 277 raw-evidence files
- 60 page-metadata files
- 1 JSON manifest

Uploading, verifying, downloading, and replaying these 1,442 objects accounts for the
majority of refresh persistence time and S3 storage. Neither the operational API,
DuckDB analytical queries, nor the technical challenge requirements consume these
supporting files after publication:
- DuckDB queries only read the public dataset files.
- Subsequent refresh merges only need prior accepted rows to perform absence retention
  and last-valid replacement.
- Challenge reconciliation and fleet metrics are computed from retained values.
- Challenge anomalies (such as Finding 001) rely on specific recorded observations,
  not continuous S3 preservation of all discarded records.

The user directed that storing these additional files is unnecessary and that the
system should store only the three resource files.

## Decision

1. **Exactly three durable files per generation:** Each published generation stores
   in S3 exactly three Parquet files—one for national, one for facilities, and one for
   generators.
2. **Transient-only supporting evidence:** Raw EIA responses, page metadata,
   row dispositions, and merge ledgers are transient working data during candidate
   construction. They are verified in local staging before upload and are **not
   persisted to S3**.
3. **Single schema per resource:** The persisted file contains the public dataset
   columns required by DuckDB and API queries, plus the natural identity keys and
   period needed for the next refresh's merge. It also retains original provenance,
   numeric source strings, units and exact calculation evidence as private physical
   columns, preserving ADR-0037 retention fidelity and the existing modeled codec's
   exact round trip. DuckDB views explicitly project only the existing public
   columns under `national`, `facilities` and `generators`; private columns are not
   exposed through SQL or previews. Separate "modeled" vs "public" files are eliminated.
4. **Subsequent refresh input:** When a subsequent refresh runs, it fetches the prior
   generation's three resource Parquet files as its baseline input. Incoming source
   rows are merged with this baseline using the accepted retention policies
   ([ADR-0024](0024-collapse-duplicates-and-use-latest-values.md),
   [ADR-0026](0026-retain-valid-data-on-invalid-refresh.md),
   [ADR-0037](0037-connector-initial-load-and-retention.md)).
5. **Quality summary preserved in PostgreSQL:** Aggregate data quality counts
   (received, excluded, candidate counts, and exclusion reasons) are computed
   transiently and stored in PostgreSQL (`refresh_runs.quality_json`), preserving the
   Admin quality summary ([ADR-0025](0025-admin-refresh-quality-report.md)).
6. **Publication metadata in PostgreSQL:** PostgreSQL `published_generations` records
   the three exact S3 object keys, SHA-256 checksums, byte counts, and row counts
   atomically upon publication. No S3 manifest file is required.
7. **Durable persistence verification:** Refresh persistence transfers the three
   resource files to S3 with SHA-256 checksums and reads each back to verify bytes
   and checksums before committing publication.

## Consequences

- **Rollout:** Acceptance authorizes implementation and convention synchronization.
  Physical S3 key mapping and a history-preserving current-generation cutover remain
  the G4 and G3 prerequisites in the implementation task manifest. Acceptance does
  not authorize a live load, pointer reset, historical-object deletion or activation.

- **Performance:** S3 operations per refresh drop from ~4,326 (1,442 PUTs + 1,442
  readback GETs + 1,442 recovery GETs) to **9 operations** (3 PUTs + 3 readback GETs +
  3 recovery GETs). Total S3 storage per generation drops from ~57.5 MB across 1,442
  objects to ~18 MB across 3 objects.
- **Verification:** Verification of source normalization, duplicate collapsing, and
  validity rules occurs in-memory/in-staging prior to upload. Durable verification
  confirms exact artifact integrity (SHA-256 and byte count) of the 3 resource files.
- **Traceability tradeoff:** Discarded invalid rows, overwritten duplicates, and
  EIA pagination metadata are not durable in S3. Challenge findings requiring raw
  pagination anomalies are captured in repo test fixtures / documentation rather than
  per-run S3 archives.
- **Superseded boundaries:** Supersedes the six-file and audit-preservation clauses of
  [ADR-0057](0057-single-file-modeled-datasets.md) and the complete evidence graph
  replay requirement of [ADR-0042](0042-connector-cli-default-s3-persistence.md).
