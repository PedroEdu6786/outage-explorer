# Refresh persistence optimization — Risks & Test Scenarios

## Edge cases
- **EC1:** Exactly 3 resource files (national, facility, generator) per generation →
  transferred concurrently; publication occurs only after all 3 pass readback. FR1–FR4.
- **EC2:** Initial refresh vs subsequent refresh → initial has no prior; subsequent
  reads prior generation's 3 files as baseline for absence retention and updates. FR6.
- **EC3:** Missing historical concurrency field in PostgreSQL → defaults to 1; invalid
  present field fails cleanly after claim before connector work. FR5.
- **EC4:** Candidate nearly consumes its deadline → check candidate completion; fresh
  persistence deadline governs 3-file S3 upload and readback. FR3, FR4, FR8.
- **EC5:** All incoming rows excluded → candidate outcome is `retained_all_excluded`;
  existing generation remains active; no new files persisted. FR8.

## Failure modes
- **FM1:** S3 upload error on any of the 3 files → abort publication, close streams,
  join workers, preserve previous active generation. FR8.
- **FM2:** Readback checksum or byte count mismatch on any resource file → abort
  publication, fail run, retain prior generation intact. FR4, FR8.
- **FM3:** Lease failure / worker loss during upload or readback → shared cancellation
  aborts; PostgreSQL reconciliation prevents stale publication. FR8.
- **FM4:** Transient source validation rejects corrupt EIA data → refresh fails in
  local staging before any S3 write. FR2, FR8.
- **FM5:** PostgreSQL connection fails during publication commit → publication is
  uncommitted; active generation remains unchanged. FR5, FR8.

## Key test scenarios
- **TS1:** Completed refresh persists exactly 3 S3 files (one per grain) with correct
  public schema, row counts, and non-empty Parquet data. AC1, AC2.
- **TS2:** S3 objects created per refresh equals 3 (zero raw, page, disposition,
  or ledger files). AC1.
- **TS3:** DuckDB preview and SQL queries against `national`, `facility`, `generator`
  execute correctly over the newly persisted files. AC2.
- **TS4:** Subsequent refresh against prior 3-file generation correctly retains absent
  observations and updates modified rows. AC3.
- **TS5:** PostgreSQL `published_generations` records the 3 exact keys, checksums,
  byte counts, and row counts atomically. AC4.
- **TS6:** `refresh_runs.quality_json` contains exact received, excluded, and candidate
  counts matching the processed source data. AC5.
- **TS7:** Injected S3 PUT or readback GET failure aborts publication and leaves the
  prior active generation active. AC6.
- **TS8:** Concurrency limits (1, 2, 3) are respected during upload/readback, sharing
  aggregate resource bounds. AC6.

## Accepted risks
- **Replay traceability:** Raw source batches, page descriptors, and per-row exclusion
  records are not durably preserved in S3. Mitigated by keeping challenge anomaly
  evidence in repository test fixtures and recording aggregate quality statistics in
  PostgreSQL.
- **Migration of historical S3 data:** Existing multi-object generations in S3 remain
  intact until cleaned up by an operator; new refreshes write strictly 3-file
  generations under ADR-0060.
