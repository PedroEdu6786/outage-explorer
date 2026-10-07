# Plan: Three-file refresh persistence optimization
> Status: phase 1 locally implemented and verified; phases 2–4 and G3/G4 pending · Slug: refresh-persistence · Spec: ./spec.md

## Approach
Replace the 1,442-object graph persistence with a clean 3-file Parquet architecture.
Candidate construction produces exactly three resource Parquet files (national,
facility, generator) with a unified resource schema, while computing data quality
metrics and verifying validity transiently in local staging. Persistence uploads only
these three files concurrently (1–3 workers, default 3) to S3, reads back and verifies
their SHA-256 checksums and byte counts, and commits the three exact object references
directly to PostgreSQL. Subsequent refreshes consume the active generation's three
files as baseline input for absence retention and replacement merges. (FR1–FR8, TR1–TR5)

## Components affected
- `infrastructure/parquet/candidates.py` & `schemas.py`: Write only the three resource
  Parquet files; eliminate disk writes for raw batches, page descriptors, dispositions,
  and ledgers; compute quality metrics in-memory. (FR1, FR2, FR7, TR1, TR2)
- `infrastructure/parquet/partitions.py`: Update `prior_days` and merge logic to read
  baseline rows directly from the prior generation's single resource Parquet file. (FR6, TR2)
- `application/services/connector_artifacts.py`: Persist only the three resource files,
  using bounded concurrency (1–3 workers); verify each file via readback checksum;
  eliminate graph dependency discovery and manifest upload. (FR3, FR4, FR8, TR3)
- `infrastructure/postgresql/publication.py`: Store the three exact file references
  (S3 key, SHA-256, byte count, row count) atomically on publication; eliminate S3
  manifest dependency. (FR5, TR1)
- `infrastructure/local_cache/modeled.py`: Pin and download the published resource file
  directly from PostgreSQL generation references for DuckDB query views. (TR2)
- `application/services/refresh_execution.py`: Orchestrate 3-file candidate generation,
  3-file persistence, and publication with quality summary recording. (FR1–FR8)

## Data model changes
- **PostgreSQL `published_generations`:** Stores the three exact file descriptors
  (keys, checksums, sizes, row counts) associated with the published generation.
  Eliminates reliance on S3 manifest key/digest. (FR5, TR1)
- **`PublishedGeneration` domain entity:** Carries exact `DatasetSummary` entries
  with S3 object key, SHA-256, byte count, and row count for each grain. (FR5)
- **Unified resource schema:** One schema per grain (national, facility, generator)
  containing public analytical columns plus natural identity and period fields needed
  for inter-refresh merges. User-approved G2 retains the existing modeled codec's
  original provenance, numeric source strings, units and exact calculation evidence
  as private physical columns. Views explicitly project existing public columns under
  `national`, `facilities`, `generators`; no source fields are synthesized and no
  precision is lost. Eliminates duplicate "modeled" vs "public" files. (TR2)

## Interfaces & contracts
### Candidate generation & transient quality (FR1, FR2, FR7, TR2)
- `ParquetCandidateBuilder.build()` produces a `CandidateResult` containing:
  - 3 `ArtifactRef` items (one per grain).
  - In-memory `QualityReport` summarizing received, excluded, and selected rows with
    reason tallies.
- Source validation, duplicate collapsing, and row eligibility run during the merge
  walk; dispositions and ledgers are evaluated in-memory without Parquet serialization.

### 3-file S3 persistence & readback (FR3, FR4, FR8, TR3)
- `PersistConnectorArtifacts.execute()` accepts the 3 resource file references.
- S3 transfer uploads the 3 files using bounded concurrency (1–3 worker threads).
  Each upload uses single `PutObject` with `ChecksumSHA256` and `IfNoneMatch="*"`.
- Immediate readback verifies `ContentLength` and SHA-256 digest of each uploaded file.
- Any failure or cancellation aborts the operation, joins workers, cleans temporary files,
  and withholds publication.

### PostgreSQL publication & local cache (FR5, TR1, TR2)
- `PublicationStore.publish()` records the generation ID, timestamp, interval, and the
  3 exact file keys and checksums atomically.
- `ModeledCache` retrieves the approved file directly from PostgreSQL metadata and
  downloads only that single resource file from S3 to pin for DuckDB views.

### Subsequent refresh merge (FR6)
- `prior_days()` scans the single prior resource file from the local cache/store,
  yielding prior modeled rows in date order.
- Absence retention, invalid retention, and replacement rules evaluate against these
  rows identically to the previous multi-partition logic.

## Implementation phases
The user authorized proceeding with local Phase 1 after reviewing the sequencing
conflict: implement its three-resource contracts and candidate pipeline through
explicit injection first, prepare durable consumers in phases 2–3, then switch
shared CLI/refresh/bootstrap composition in phase 4. Preserve current consumers
and their regression tests until the switch; no new candidate writes both layouts
and no old-format conversion is introduced. Phase 1 tests establish the local
AC1/AC2/AC3/AC5 obligations, not S3/publication/runtime acceptance or benchmarks.

1. **Phase 1: 3-file local candidate generation & transient quality**
   - Unify schema per resource in `infrastructure/parquet/schemas.py`.
   - Implement the three-resource builder using the existing codec/policies and
     bounded storage; write only three files and compute quality transiently.
     Retain the existing composed producer until phase 4 switches its consumers.
   - Update `prior_days` in `infrastructure/parquet/partitions.py` to stream from the
     single Parquet file.
   - Unit tests verify candidate creation, row counts, and quality metrics. (FR1, FR2, FR6, FR7)
2. **Phase 2: 3-file S3 persistence & readback verification**
   - Update `PersistConnectorArtifacts` to upload and verify only the 3 resource files.
   - Support bounded concurrency (1–3 workers, default 3) with thread joining and cancellation.
   - Verify that upload error or checksum mismatch cleanly fails without corrupting state. (FR3, FR4, FR8, TR3)
3. **Phase 3: PostgreSQL publication & local cache integration**
   - Update `published_generations` storage and `PublishedGeneration` DTO to track the
     3 exact file keys/checksums.
   - Update `local_cache/modeled.py` to pin the exact file without manifest resolution.
   - Verify DuckDB views over the single resource files. (FR5, TR1, TR2)
4. **Phase 4: Refresh execution orchestration & end-to-end verification**
   - Switch shared CLI/refresh/bootstrap composition to the updated candidate
     builder, persistence and publication; remove obsolete graph/manifest writes
     and declarations once all consumers use three-resource contracts.
   - Integration tests verify full refresh cycle: EIA ingestion → 3-file Parquet → S3
     persistence → publication → DuckDB SQL query.
   - Verify subsequent refresh applying updates and retaining absent keys. (AC1–AC6)

## Dependencies & integrations
- Reuses existing boto3 client, PyArrow Parquet writer/reader, PostgreSQL connection pool,
  and DuckDB view layer. No new libraries or services.

## Risks & tradeoffs
- **Replay traceability:** Discarded invalid rows and EIA pagination metadata are not
  retained in S3. Mitigated by keeping challenge anomaly evidence in repo test fixtures
  and recording aggregate quality statistics in PostgreSQL.
- **Migration of existing data:** Old 1,442-object generations in S3 are superseded by the
  3-file format; a fresh initial load creates the canonical 3-file baseline under ADR-0060.

## Test strategy
- **AC1:** Test that refresh creates exactly 3 S3 objects under the generation prefix.
- **AC2:** Test DuckDB `SELECT * FROM national`, `facility`, `generator` queries and
  previews execute against the new files.
- **AC3:** Test two sequential refreshes: initial load followed by interval update; verify
  absent rows are retained and updated rows are replaced.
- **AC4:** Test PostgreSQL `published_generations` contains valid keys and checksums.
- **AC5:** Test `refresh_runs.quality_json` contains exact row counts and exclusion codes.
- **AC6:** Test injected S3 error/corruption aborts without publishing or displacing prior generation.
