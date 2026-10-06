# Spec: Single-file modeled datasets
> Status: accepted · Slug: compact-analytical-serving

## Problem

Preview and SQL users experience stalls over a six-month baseline of approximately
27,600 observations stored as 549 daily modeled Parquet partitions. Readers
rebuild public inputs from every partition of a dataset on cold requests, and the
connector maintains a parallel day-partitioned layout for merging, verification
and recovery. Two overlapping storage paths serve the same modeled data,
duplicating work and code. Controlled diagnosis also found whole-input imports and
separate deadline/cleanup defects; the precise live stall cause remains unresolved.

## Goal

Store each generation's modeled data as one Parquet file per dataset, used by
both the connector and preview/SQL readers, so reads complete reliably while
existing data rules, generation consistency, authorization and bounds hold.

## Requirements

### Functional (EARS)

- **FR1:** WHEN the data connector produces a verified candidate, from the CLI or
  a refresh run, THE SYSTEM SHALL store, for each dataset (national, facilities,
  generators), exactly one modeled Parquet file and exactly one public projection
  Parquet file.
- **FR2:** THE SYSTEM SHALL NOT store modeled data as daily partitions for new
  candidates or generations.
- **FR3:** WHEN a run merges incoming data with a previous generation THE SYSTEM
  SHALL read that generation's single-file datasets as its prior input.
- **FR4:** WHEN merging THE SYSTEM SHALL apply the existing validation, duplicate,
  replacement and retention rules, including retaining absent keys and wholly
  excluded datasets under [ADR-0037](../../adr/0037-connector-initial-load-and-retention.md).
- **FR5:** WHEN a candidate is verified THE SYSTEM SHALL verify its single-file
  datasets against replayed source evidence and the prior generation with the
  same guarantees as today's candidate verification.
- **FR6:** WHEN a connector CLI run persists durably THE SYSTEM SHALL persist and
  read back the complete candidate, including its single-file datasets; a
  `--local-only` run SHALL keep them locally.
- **FR7:** IF single-file datasets cannot be produced, verified or persisted THEN
  THE SYSTEM SHALL report the run as unsuccessful under existing outcome rules.
- **FR8:** WHEN a generation is published THE SYSTEM SHALL expose only a complete
  verified set of its six dataset files, immutably bound to that generation.
- **FR9:** WHEN preview or SQL starts THE SYSTEM SHALL read the published
  generation's public projection files without rebuilding them during reader requests.
- **FR10:** WHEN a new preview sequence or dataset-referencing SQL execution
  starts THE SYSTEM SHALL use one published generation for all required datasets.
- **FR11:** IF publication or verification fails THEN THE SYSTEM SHALL keep the
  previously published generation usable.
- **FR12:** WHILE a preview sequence or active work may use a generation's files
  THE SYSTEM SHALL retain them through the existing lifetime and until the work is
  confirmed ended, including after another generation is published.
- **FR13:** IF a selected generation's dataset files cannot be verified or
  recovered THEN THE SYSTEM SHALL return an explicit unavailable outcome without
  substituting another generation.
- **FR14:** WHEN no previous generation exists THE SYSTEM SHALL run the initial
  load through the single-file layout under ADR-0037, without reading any
  daily-partitioned data.
- **FR15:** WHEN preview, SQL or any continuation is requested THE SYSTEM SHALL
  enforce current application authorization before protected data access:
  Viewer national-only, Analyst and Admin all three datasets, with existing
  original-caller restrictions on continuations.

### Technical / Non-functional

- **TR1:** Each dataset file must exactly match today's modeled data and public
  projection in schema, types, values, row multiplicity, identifiers and date
  coverage. National percentages keep their behavior under
  [ADR-0031](../../adr/0031-show-national-percentages-without-discrepancy-flags.md).
- **TR2:** Raw source evidence, dispositions, ledgers, provenance and run
  reports remain recoverable and keep supporting replay and audit under the
  [connector contract](../data-connector/spec.md).
- **TR3:** Workers receive only the selected generation's authorized public
  dataset files, read-only, within existing isolation boundaries; raw/provenance
  data, operational data, credentials, unrelated files and network access stay
  excluded under [ADR-0008](../../adr/0008-local-parquet-file-cache.md) and the
  [analytical contract](../analytical-runtime/spec.md). [SQL inspection
  isolation](../../adr/0054-bounded-subprocess-sql-inspection.md) stays enforced.
- **TR4:** Preserve the [preview contract](../data-api/http-contract.md#dataset-preview):
  filters, ordering, default 100/maximum 500 rows, same-snapshot cursors, fixed
  15-minute lifetime and explicit loss/expiry errors.
- **TR5:** Preserve broad read-only SQL support and submitted semantics under the
  [data contract](../data-api/spec.md), without query rewriting.
- **TR6:** Preserve the [SQL continuation contract](../data-api/http-contract.md#submit-sql-and-read-pages-on-the-same-path):
  one retained execution and generation, fixed page size, fixed 15-minute expiry,
  explicit errors and 1,000-row/1-MiB total limits with explicit truncation.
- **TR7:** Reads use bounded scans of dataset files without whole-input import
  before each execution, under [ADR-0007](../../adr/0007-bounded-parquet-query-execution.md).
- **TR8:** Connector, verification, persistence and reads respect hard resource
  bounds; existing execution ceiling, single analytical slot and busy behavior
  are unchanged. Per-day bounds become per-dataset bounds.
- **TR9:** Success is functional: connector CLI and refresh runs, preview and SQL
  over current data complete within bounds. No latency targets are defined.
- **TR10:** Size for current data only: the six-month baseline of approximately
  27,600 observations. Growth and longer retention are not requirements.

## Inputs & Outputs

- **Inputs:** EIA source data; the previous generation's three modeled files, or
  none for the initial load; caller authorization; unchanged preview filters, SQL
  and continuation inputs.
- **Artifacts:** Per generation and dataset, one immutable modeled Parquet file
  (with provenance) and one immutable public projection Parquet file (public
  columns only): six files, plus existing evidence, dispositions, ledgers and
  manifest. Workers receive only public projection files.
- **User outputs:** Existing preview pages, SQL pages, generation identities and
  errors under the [data contract](../data-api/http-contract.md).

## Scope

### In scope

- Replacing daily modeled partitions with one file per dataset in connector
  modeling output, merge input, verification, persistence, recovery,
  publication and preview/SQL reads.
- Removing reader-side partition loading and request-time input construction.
- A fresh initial load for April 2–October 1, 2026 in the new layout, replacing
  the current data.
- ADR-0057 (accepted) and updating the connector plan
  and diagrams that describe daily modeled partitions.

### Out of scope (non-goals)

- Changes to EIA retrieval, validation, duplicate, replacement or retention rules.
- Runtime, cloud or engine migration; increased concurrency or changed busy
  behavior; new endpoints, durable query IDs or authorization changes.
- Supporting, reading or converting the daily-partitioned layout. Existing data
  in that layout is discarded.
- Broad deadline/cleanup/recovery refactoring.
- Production provisioning or deployment; refresh stays idle under
  [ADR-0056](../../adr/0056-user-directed-local-api-activation.md) until runs are
  explicitly directed.

## Assumptions

- User direction (October 6, 2026): one storage layout for modeled data, shared
  by connector steps 3–5 and readers; a large code change is accepted.
- The existing per-day merge rules can still run on rows grouped by day in memory;
  only stored layout changes. Mechanism is a `/plan` decision.
- Each generation writes all six dataset files; reuse of unchanged daily files
  across generations ends.
- No accepted ADR selected daily modeled partitions; that layout came from the
  [connector plan](../data-connector/plan.md). ADR-0001/0002/0007/0008/0037/0042
  remain valid as written. ADR-0050's day indexes are derived verification
  staging and can remain. [ADR-0057](../../adr/0057-single-file-modeled-datasets.md), accepted
  October 6, 2026, records this layout.
- [Automatic publication](../../adr/0003-admin-refresh-publication.md) and
  [interruption recovery](../../adr/0052-interrupted-refresh-recovery.md) still apply.
- Prior diagnostic tests do not verify this change.
- User direction (October 6, 2026): the user deletes the current data from S3 and
  reruns the initial load in the new layout. The operational publication and
  refresh records that reference the deleted generation must be reset so the
  next run starts with no previous generation. Preview/SQL are unavailable until
  the new generation publishes. EIA may return revised values versus the
  deleted data.

## Acceptance Criteria

- [ ] **AC1:** Successful CLI and refresh runs each store exactly one modeled and
  one public projection file per dataset (six total) for their candidate.
  (verifies FR1)
- [ ] **AC2:** New candidates contain no daily modeled partitions. (verifies FR2)
- [ ] **AC3:** A follow-up run merges against the previous generation's three modeled
  files. (verifies FR3)
- [ ] **AC4:** Absent keys, invalid replacements and wholly excluded datasets
  produce the same retained results as today. (verifies FR4)
- [ ] **AC5:** Verification rejects modeled values, origins or ledgers that do not
  match replayed evidence and the prior generation. (verifies FR5)
- [ ] **AC6:** A default CLI run persists and reads back the full candidate; a
  `--local-only` run keeps it locally. (verifies FR6)
- [ ] **AC7:** Production, verification or persistence failure never yields a
  successful run. (verifies FR7)
- [ ] **AC8:** Missing, mutated or mixed-generation dataset files cannot be
  published. (verifies FR8)
- [ ] **AC9:** No preview or SQL request builds or reprojects dataset files.
  (verifies FR9)
- [ ] **AC10:** After publication, each new sequence or execution uses that
  generation for all its inputs. (verifies FR10)
- [ ] **AC11:** A failed run leaves the previous generation served. (verifies FR11)
- [ ] **AC12:** A valid preview sequence keeps reading its original generation
  after a new publication, and active work's files are not reclaimed. (verifies FR12)
- [ ] **AC13:** Unverifiable selected files produce explicit unavailability.
  (verifies FR13)
- [ ] **AC14:** With no previous generation, an initial load for April 2–October 1,
  2026 produces and publishes six dataset files, and no code path reads daily
  partitions. (verifies FR14)
- [ ] **AC15:** Direct and continuation access follow current roles and ownership,
  including after revocation. (verifies FR15)
- [ ] **AC16:** Each dataset file's schema and row multiset match today's modeled
  data and public projection. (verifies TR1)
- [ ] **AC17:** National percentages keep their precision and presentation.
  (verifies TR1)
- [ ] **AC18:** Evidence, dispositions, ledgers and reports remain recoverable and
  replayable. (verifies TR2)
- [ ] **AC19:** Workers can read only authorized public dataset files.
  (verifies TR3)
- [ ] **AC20:** Preview filters, ordering, page sizes and 15-minute expiry are
  unchanged. (verifies TR4)
- [ ] **AC21:** Supported SQL keeps its semantics, including joins, aggregates,
  CTEs, subqueries and windows. (verifies TR5)
- [ ] **AC22:** SQL pages reuse one execution without re-execution, keep fixed
  expiry and respect total limits. (verifies TR6)
- [ ] **AC23:** Reads do not import the whole input before scanning. (verifies TR7)
- [ ] **AC24:** Resource exhaustion fails within existing bounds; analytical
  contention keeps single-slot busy behavior. (verifies TR8)
- [ ] **AC25:** CLI and refresh runs, first-page previews for each dataset, and
  SQL referencing all three datasets complete over current data. (verifies TR9)
- [ ] **AC26:** Current six-month data is handled within existing hard bounds.
  (verifies TR10)

## Open Clarifications

_None._
