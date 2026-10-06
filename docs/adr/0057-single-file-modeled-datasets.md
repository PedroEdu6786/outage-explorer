# ADR-0057: Store modeled data as one Parquet file per dataset

Status: **Accepted** (user decision, October 6, 2026)

## Context

The connector stores each generation's modeled data as daily Parquet partitions
(549 objects for the six-month baseline of about 27,600 observations). That layout
came from the [connector plan](../specs/data-connector/plan.md), not an accepted
ADR. Preview and SQL rebuild public inputs from every partition of a dataset on
cold requests, adding serial S3, hashing and copy work, while the connector keeps
a parallel day-partitioned path for merge, verification and recovery. The user
found the two overlapping paths conflicting and asked for one layout.

## Decision

- Each generation stores, per dataset (national, facilities, generators),
  **exactly one modeled Parquet file** (full modeled schema, including
  provenance) and **exactly one public projection Parquet file** (only the
  public columns, an exact projection of the modeled file): six files per
  generation. The connector produces and verifies both in CLI and refresh runs;
  they are persisted and read back with the candidate under
  [ADR-0042](0042-connector-cli-default-s3-persistence.md).
- The modeled files are the **only** modeled representation: the next run's
  prior input, verification target and persisted/recovered graph. The public
  files are the **only** analytical worker inputs for preview and SQL. Readers
  never rebuild or reproject inputs per request.
- New runs write no daily modeled partitions. The manifest format version is
  bumped; old-layout manifests are rejected, and no code reads, supports or
  converts the old layout. The user deletes existing data in that layout, and a
  fresh initial load (April 2–October 1, 2026) rebuilds it.
- **Publication reset:** an explicit, guarded operator CLI operation clears the
  active publication pointer so the next refresh admits as an initial load. It
  requires the expected current generation ID, refresh idle (no active run or
  owner, latest run terminal and not `publication_unknown`), and changes nothing
  otherwise. Immutable refresh and publication history is not modified. Direct
  SQL edits are not a supported reset path.
- Every generation writes all six files. Reuse of unchanged daily objects across
  generations ends.
- Existing validation, duplicate, replacement and retention rules
  ([ADR-0023](0023-exclude-invalid-source-records.md),
  [0024](0024-collapse-duplicates-and-use-latest-values.md),
  [0026](0026-retain-valid-data-on-invalid-refresh.md),
  [0037](0037-connector-initial-load-and-retention.md)) are unchanged. Per-day
  merge logic still runs on rows grouped by day in memory.
- Raw source evidence, dispositions, ledgers, provenance and reports remain
  recoverable for replay and audit; dispositions and ledgers keep their current
  layout. [ADR-0050](0050-day-indexed-candidate-verification.md) day indexes
  remain derived local verification staging only.
- Per-day row bounds become per-dataset bounds. The per-file byte bound starts
  at **32,000,000 bytes** under [ADR-0041](0041-connector-defaults-and-json-configuration.md);
  this is an initial, unmeasured limit. Sizing targets current data only;
  growth is not a requirement.
- Workers scan the public files directly through views restricted to the exact
  staged files, with external access disabled and configuration locked, under
  [ADR-0007](0007-bounded-parquet-query-execution.md); no whole-input table
  import. The [ADR-0008](0008-local-parquet-file-cache.md) local cache holds the
  three public files per generation. Container isolation remains the primary
  boundary. Authorization and publication guarantees are unchanged.

## Alternatives

- **Keep daily partitions and add compact serving files:** fixes reads but keeps
  two overlapping layouts. Rejected by the user.
- **Build compact files lazily in the reader cache:** no connector change, but
  first requests pay the build cost and the overlap remains. Rejected.
- **Convert the current generation in place:** keeps identical data without EIA
  calls but requires old-layout reading code. Rejected in favor of a fresh load.
- **Public files only, provenance from ledgers/evidence:** three files, but merge
  must rebuild prior rows from evidence. Larger, riskier change. Rejected.
- **Serve the modeled file to workers:** exposes provenance columns. Rejected.
- **Reset by documented SQL:** bypasses guards and immutable history. Rejected.
- **Monthly or size-based partitions:** suited to growth, which is out of scope.

## Consequences

- Large connector change: modeling output, merge input, verification, manifests,
  export/recovery and coverage reporting are rewritten for six files. Old-layout
  code is deleted, not kept behind compatibility paths.
- Removes reader-side partition loading, projection and per-request preparation.
- Each refresh rewrites a few MB of modeled and public data for the current
  baseline.
- The analytical worker image and runtime profile change, so a new local review
  record is required before startup under ADR-0055/0056; no additional external
  or browser validation.
- Preview/SQL are unavailable between deletion and the new publication. EIA may
  return revised values versus the deleted data.
- The connector plan, diagrams, code-structure and architecture guides must be
  updated to match.
- Does not repair the separately diagnosed deadline and cleanup defects, or
  establish measured latency.

## References

- [Spec](../specs/compact-analytical-serving/spec.md) and
  [plan](../specs/compact-analytical-serving/plan.md)
- [ADR-0001](0001-s3-parquet-duckdb.md), [ADR-0002](0002-analytical-dataset-contracts.md)
