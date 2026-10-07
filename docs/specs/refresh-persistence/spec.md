# Spec: Three-file refresh persistence optimization
> Status: phases 1–2 implemented and verified; G4 resolved; phases 3–4 and G3 pending · Slug: refresh-persistence

## Problem
Admins wait too long for refresh persistence. The current implementation persists
1,442 S3 objects (~57.5 MB) per generation—including raw batches, page descriptors,
dispositions, and daily ledgers—which are never consumed by API users, DuckDB queries,
or challenge deliverables. This creates avoidable upload, readback, and storage overhead.

## Goal
Persist only the three canonical resource Parquet files (national, facility, generator)
per generation to S3, eliminating all persisted supporting artifacts and duplicate
representations, while preserving required merge/retention policies, DuckDB analytical
queries, Admin quality summaries, and exact durable integrity.

## Requirements
### Functional (EARS)
- **FR1:** WHEN a candidate generation is constructed THE SYSTEM SHALL produce and
  persist exactly three resource Parquet files to S3 (national, facility, generator).
- **FR2:** WHEN a refresh runs THE SYSTEM SHALL evaluate source normalization, duplicate
  collapsing, and row validity locally in transient staging without persisting raw
  evidence, page metadata, dispositions, or merge ledgers to S3.
- **FR3:** WHEN persistence is executed THE SYSTEM SHALL transfer the three resource
  Parquet files concurrently up to the configured concurrency limit (1–3, default 3).
- **FR4:** WHEN persistence transfers complete THE SYSTEM SHALL read back and verify
  the byte count and SHA-256 checksum of each persisted resource file before publication.
- **FR5:** WHEN a published generation is committed THE SYSTEM SHALL record the exact S3
  object references (key, SHA-256, byte count, row count) in PostgreSQL atomically.
- **FR6:** WHEN a subsequent refresh runs THE SYSTEM SHALL use the prior generation's
  three resource Parquet files as its baseline input for absence retention and replacement
  merges.
- **FR7:** WHEN a refresh completes THE SYSTEM SHALL store aggregated data quality counts
  (received, excluded, candidate counts, and exclusion reasons) in PostgreSQL
  (`refresh_runs.quality_json`).
- **FR8:** IF any resource file fails S3 upload, readback checksum verification, or
  deadline/cancellation THEN THE SYSTEM SHALL abort publication, clean up transient files,
  and retain the prior active generation.

### Technical / Non-functional
- **TR1:** S3 storage per generation is limited to exactly the 3 resource files (no S3
  manifest file; generation metadata is stored in PostgreSQL).
- **TR2:** A single schema per resource serves both prior-generation merge baseline and
  DuckDB analytical query views; duplicate "modeled" vs "public" files are eliminated.
  The accepted physical contract preserves original provenance, numeric source strings,
  units, natural identity and exact calculation evidence privately. Analytical views
  expose only the existing public column contract.
- **TR3:** Bounded transfer concurrency (1–3, operational default 3) shares aggregate
  request, byte, and staging bounds.
- **TR4:** Supersedes the six-file and audit-preservation requirements of ADR-0057 and
  full-evidence replay of ADR-0042 (formalized in ADR-0060).
- **TR5:** Authorization, single-owner lease fencing, and PostgreSQL atomic publication
  remain strictly enforced. Failures preserve the previous active generation.

## Inputs & Outputs
- **Inputs:** Admitted all-grain refresh configuration, EIA source data, prior generation's
  3 resource Parquet files (if not initial load), configured S3 target.
- **Outputs:** Exactly 3 durable S3 Parquet files, updated PostgreSQL `published_generations`
  record, updated `refresh_runs.quality_json` and status.

## Scope
### In scope
- 3-file Parquet generation model (national, facility, generator).
- Elimination of durable raw, page, disposition, and ledger Parquet/JSON artifacts.
- Single unified schema per resource satisfying both merge retention and DuckDB queries.
- Adaptation of subsequent refresh merge to consume prior 3-file Parquet inputs.
- Concurrency (1–3) for uploading and reading back the 3 resource files.
- Atomic publication recording the 3 exact object references in PostgreSQL.
- Transient quality aggregation stored in PostgreSQL `quality_json`.

### Out of scope (non-goals)
- Deletion or cleanup of existing/historical S3 objects (handled via operator CLI / S3 lifecycle).
- Changing public API endpoints, schemas, or query semantics.
- Re-architecting DuckDB query execution or sandbox isolation boundaries.
- Live external network benchmark studies.

## Assumptions
- The 3 resource Parquet files contain all columns needed for both public analytical
  queries and inter-refresh row identity / retention checks.
- Discarded invalid records and EIA raw pagination anomalies are not required to be
  permanently archived in S3; challenge anomaly evidence (Finding 001) is preserved in
  repository test fixtures and documentation.
- Essential generation references and checksums in PostgreSQL eliminate the need for a
  separate S3 manifest object.

## Acceptance Criteria
- [ ] **AC1:** A completed refresh persists exactly 3 Parquet files to S3 and zero
  supporting evidence, page, ledger, or disposition files. (verifies FR1, FR2, TR1)
- [ ] **AC2:** DuckDB preview and SQL queries against all three grains execute correctly
  against views over the persisted resource files. (verifies TR2)
- [ ] **AC3:** A subsequent refresh successfully reads the prior generation's 3 files,
  correctly applying absence retention, invalid retention, and replacement rules. (verifies FR6)
- [ ] **AC4:** PostgreSQL `published_generations` records the 3 file keys, checksums,
  byte counts, and row counts atomically upon publication. (verifies FR5, TR1)
- [ ] **AC5:** Data quality summary is saved in `refresh_runs.quality_json` matching
  expected row counts and exclusion reason tallies. (verifies FR7)
- [ ] **AC6:** S3 upload and readback use bounded concurrency (1–3), and any upload or
  checksum failure cleanly aborts without publishing or displacing the prior active
  generation. (verifies FR3, FR4, FR8, TR3, TR5)

## Open Clarifications
Scope and direction are confirmed: three-file-only generation persistence, transient
verification, PostgreSQL metadata storage. ADR-0060 and the private-field codec were
explicitly approved October 6, 2026 (task gates G1/G2). The user resolved physical
S3 object identity (G4) by selecting generation-prefixed resource keys in
[ADR-0061](../../adr/0061-generation-prefixed-resource-object-keys.md).
History-preserving current-generation cutover/rollback (G3) remains required
before its corresponding tasks and runtime use; see the task manifest.
