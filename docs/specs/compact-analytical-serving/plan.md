# Plan: Single-file modeled datasets
> Status: accepted · Slug: compact-analytical-serving · Spec: ./spec.md

## Approach

- Replace daily modeled partitions with **one modeled Parquet file per dataset
  per generation** (national, facilities, generators), produced and verified by
  the connector in CLI and refresh runs, persisted/recovered with the manifest
  graph, and used as the next run's prior input (FR1–FR3, FR14).
- In the same build, write **one public-column projection file per dataset**,
  verified as an exact projection of the modeled file and bound to the same
  manifest. Workers receive only these files (TR1, TR3). Readers download,
  verify and pin them; they never project or rebuild (FR9).
- Keep the domain merge rules unchanged. The connector walks days in ascending
  order: it merges the incoming day groups (ADR-0050 staging stays) with prior
  day groups streamed from the sorted prior modeled file, and handles one day in
  memory at a time (FR4).
- Keep dispositions and ledgers in their current per-day layout and schemas.
  They are audit artifacts, not modeled data. This is the smallest change for
  TR2.
- Bump the manifest schema version so old-layout manifests are rejected
  explicitly. No code reads or converts them (FR2, FR14).
- Workers scan public files through DuckDB views over `read_parquet`, restricted
  to the exact staged paths with `allowed_paths`, then set
  `enable_external_access=false` and `lock_configuration=true`. No base table is
  created (TR7, TR3).
- Add an explicit, guarded operator CLI operation that clears the active
  publication pointer, so the next refresh admits as an initial load. Immutable
  history stays as it is (FR14).

## Components affected

- **Artifact and candidate ports** (`application/ports/artifacts.py`,
  `candidates.py`): new `public` artifact kind; manifest `public` collection;
  per-grain period coverage in `GrainSummary`; manifest schema version `2`
  (FR1, FR2, FR8, TR1).
- **Parquet schemas** (`infrastructure/parquet/schemas.py`): public schema per
  grain, derived from the modeled schema fields in `PUBLIC_DATASETS` column
  order, plus a public record projection (TR1, TR3).
- **Parquet storage** (`infrastructure/parquet/storage.py`): one immutable file
  with multiple bounded row groups. Existing per-batch round-trip,
  row-group-bytes and checksum checks stay (FR1, TR8).
- **Day merge orchestration** (`infrastructure/parquet/partitions.py`): replace
  the partition index, `prior_day` and the partition-driven `day_sequence` with
  an ordered merge walk over the interval days and the prior file's day groups
  (FR3, FR4, FR14, TR8).
- **Candidate builder/verifier** (`infrastructure/parquet/candidates.py`): build
  writes 3 modeled and 3 public files. Verification compares each file to the
  replay/merge output as one ordered stream. Unchanged-day reuse is removed.
  Per-dataset cumulative bounds are added (FR1, FR2, FR5, FR7, TR1, TR2, TR8).
- **Manifest codec** (`infrastructure/parquet/manifests.py`): v2 codec and
  validation. Each grain has exactly one modeled and one public ref, each with
  `partition=None`. Day-keyed dispositions/ledger stay. v1 is rejected
  (FR2, FR8, FR14).
- **Connector graph, persistence and recovery**
  (`infrastructure/parquet/connector.py`,
  `application/services/connector_artifacts.py`, `connector.py`): manifest
  dependencies include public refs. Readback, replay and `--local-only` behave as
  today (FR6, FR7, TR2).
- **Refresh execution** (`application/services/refresh_execution.py`): coverage
  and `DatasetSummary` start/end come from verified summaries, not
  `ref.partition`; schema version check updated. Publish order stays persist →
  publish (FR7, FR8, FR11).
- **Reader cache** (`infrastructure/local_cache/modeled.py`): replace the
  per-partition projection with download → content-identity, schema and
  row-count verification → install read-only → pin. Lifetime and eviction stay
  (FR9, FR10, FR12, FR13, TR3, TR7).
- **Worker engine** (`infrastructure/duckdb/previews.py`, `queries.py`): views
  over the exact staged files under `allowed_paths`, external access disabled,
  configuration locked. Query text and preview SQL shape are unchanged
  (TR3–TR7).
- **Worker runtime, settings and bootstrap** (`worker_runtime/*` image and
  profile identity, `settings.py` `ArtifactSettings`, `bootstrap.py`
  `CacheBounds`): byte bound sized for single files; row bounds read as
  per-dataset (TR8, TR10).
- **Publication reset operation** (new application use case, `RefreshStore` port
  method, PostgreSQL adapter, CLI entrypoint and startup wrapper registered in
  `tests/architecture`, Makefile target) (FR14).
- **Authorization paths** (`application/services/preview.py`, `queries.py`,
  `catalog.py`): no change; regression coverage only (FR15).
- **Documentation**: connector plan, diagrams, `docs/context/code-structure.md`,
  `architecture.md`, README; ADR-0057 consequences (scope item).

### Code removal inventory (FR2, FR9, TR7; spec "no code reads the old layout")

Delete, don't deprecate. No compatibility shims or old-layout branches remain.

- **`infrastructure/parquet/partitions.py`**: delete `PartitionIndex`,
  `index_modeled`, `prior_day` and the partition-driven `day_sequence` (replaced
  by the prior day stream and day walk). Delete the `incoming_day` unindexed
  replay fallback; all callers use ADR-0050 staging. **Keep** `stage_dates`
  (ADR-0050 raw day staging) and the merge/ledger logic, adapted to the walk.
- **`infrastructure/parquet/candidates.py`**: delete per-day modeled writes,
  reuse of unchanged modeled references from the base generation, and
  modeled-partition coverage/placement checks. Inherited *evidence* handling
  stays (provenance of retained rows).
- **`infrastructure/parquet/manifests.py`**: delete v1 modeled-partition decoding
  and validation; v1 manifests are rejected with an explicit error.
- **`application/services/refresh_execution.py`**: delete coverage and
  `DatasetSummary` start/end derivation from `ref.partition`.
- **`infrastructure/local_cache/modeled.py`**: delete the reader-side projection
  in `_load` (`modeled_from_record` use, per-record key/partition/coverage
  checks, per-partition `projection-{index}` files, Parquet writing). Narrow the
  `reclaim_private_cache` filename pattern to one file per dataset.
- **`infrastructure/duckdb/previews.py`, `queries.py`**: delete the
  `.create(...)` whole-input table import.
- **`infrastructure/analytical-worker/native-linux-validation/prepare-public-inputs.py`**:
  delete; it derives per-partition public projections from old-layout graphs.
  Update other validation helpers only where they assume many input files.
- **Tests and fixtures**: delete tests that assert daily modeled partitions,
  unchanged-day reuse, reader projection or per-partition GET counts; replace
  them with single-file equivalents. Keep retention/rerun behavior tests.
- **Keep unchanged**: domain `model_partition`/`merge_partition` (day-level
  rules), `stage_dates`, evidence/disposition/ledger codecs, worker staging and
  launcher.

## Data model changes

- **Modeled dataset file** (×3 per generation): today's modeled schema v1 per
  grain, unchanged columns and types. Rows sorted by (`period`, identity)
  ascending, which equals today's day-order concatenation. Bounded row groups.
  No daily objects.
- **Public dataset file** (×3 per generation): exactly the `PUBLIC_DATASETS`
  columns in declared order, with types taken from the modeled schema fields, the
  same row order, and statistics enabled for row-group pruning. Byte layout is
  deterministic for a pinned pyarrow version; verification compares records, not
  bytes.
- **ArtifactRef**: shape unchanged. `kind` adds `"public"`. Modeled and public
  refs carry `partition=None`. Disposition and ledger refs keep their day (or
  `None` for the malformed-date group).
- **CandidateManifest v2**: adds `public: tuple[ArtifactRef, ...]`;
  `schema_version="2"`. `base_modeled` holds the prior generation's 3 modeled
  refs.
- **GrainSummary**: adds `first_period: date | None` and
  `last_period: date | None` (min/max candidate row period), computed in build
  and recomputed by verification.
- **PostgreSQL**: no schema migration. The reset operation sets
  `refresh_coordination.active_generation_id` to NULL. `refresh_runs` and
  `published_generations` history stays immutable under the existing triggers.
- **Settings**: raise `ArtifactSettings.file_bytes` (initial unmeasured limit
  under ADR-0041, accepted 32,000,000). `row_group_rows`, `row_group_bytes` and
  `ModelSettings` 30,000-row values are unchanged and are now read per dataset.

## Interfaces & contracts

- `LocalParquetStore.write_file(kind, grain, rows) -> ArtifactRef`: exactly one
  object; row groups ≤ `row_group_rows`/`row_group_bytes`; file ≤ `file_bytes`;
  rejects empty input.
- Prior day stream: `(store, modeled_ref, bounds) -> Iterator[(date,
  tuple[ModeledRow, ...])]`. Strictly increasing keys, cumulative prior rows ≤
  `prior_rows`. Rejects unsorted or duplicate keys and refs whose
  partition is not `None`.
- Day walk: `(interval, prior_days) -> Iterator[date | None]`. Yields `None`
  first (malformed dates), then the ascending union of interval days and prior
  days.
- `ParquetCandidateBuilder.build(generation_id, evidence, bounds, prior) ->
  CandidateManifest` and `verify(candidate, bounds)`: same signatures, v2
  semantics.
- Public projection: `public_record(modeled_record) -> dict` in
  `PUBLIC_DATASETS` order, plus `public_schema(grain)`.
- `VerifiedModeledCache.prepare(generation, dataset) -> pin(files)`: unchanged
  port. `files` is exactly one `ApprovedFile` per dataset, whose sha/bytes/rows
  equal the manifest public ref and `DatasetSummary.rows`.
- Worker contract: `PreviewRead.files` and `QueryRead.relations` are unchanged.
  The engine exposes each dataset as a view named by `dataset.id` (preview:
  `approved`).
- Reset: CLI `reset-publication --expected-generation <uuid>` →
  `ResetActivePublication.execute(expected_generation_id) -> ResetOutcome
  {cleared_generation_id}` → `RefreshStore.clear_active_generation(expected)`.
  The adapter takes the coordination row lock and requires: `active_run_id` and
  owner are NULL; the latest run is terminal and not `publication_unknown`;
  `active_generation_id` equals the expected value. Otherwise it fails with an
  explicit error and changes nothing.

## Implementation phases

1. **Prerequisites**: done. ADR-0057 and all plan decisions accepted
   October 6, 2026.
2. **Contracts and codecs**: ports, manifest v2, public schema and projection,
   single-file writer, byte setting (FR1, FR2, FR8, TR1, TR8, TR10).
3. **Connector modeling and verification**: day walk, prior streaming, build
   writing 3+3 files, streaming verification, per-dataset bounds, reuse removed
   (FR1–FR5, FR7, FR14, TR1, TR2, TR8).
4. **Persistence, recovery and publication**: graph dependencies, S3 readback,
   `--local-only`, coverage from summaries in refresh execution (FR6–FR8, FR11,
   TR2).
5. **Readers**: cache load/pin without projection; DuckDB views with
   `allowed_paths`; worker image rebuild; new local review record for the
   changed image and profile identity under ADR-0055/0056 (lightweight, no new
   external or browser validation) (FR9, FR10, FR12, FR13, FR15, TR3–TR7).
6. **Reset operation**: use case, port, adapter, CLI and Make target,
   architecture rule registration (FR14).
7. **Dead-code sweep**: confirm every item in the removal inventory is deleted,
   no symbol or test references the old layout, and no unused imports, settings
   or fixtures remain (FR2, FR9, TR7).
8. **Documentation**: connector plan (date-partition sections), diagrams, code
   structure, architecture, README; devlog entry (scope).
9. **User-directed operation** (described here, not executed): stop API and
   refresh → reset pointer → user deletes S3 data and clears local
   connector staging and private cache → start new build → refresh initial load
   April 2–October 1, 2026 → CLI run with `--prior` → preview/SQL smoke
   (FR14, TR9).

## Dependencies & integrations

- pyarrow 25.0.1 (multi-row-group writer, statistics), duckdb 1.5.6. Probe on
  synthetic temp data with `.venv`, October 6, 2026: a view over `read_parquet`
  works after `allowed_paths=[file]`, `enable_external_access=false` and
  `lock_configuration=true`. Other files, `read_csv`, `COPY TO`, `INSTALL` and
  re-enabling settings raise errors. `information_schema` reports `VIEW`, and
  the plan shows `READ_PARQUET`.
- S3 through the existing `S3ArtifactStore` and transfer bounds. Downloads must
  allow the raised `file_bytes`.
- PostgreSQL `refresh_coordination` (reset). Docker/Colima worker image and
  reviewed runtime evidence identity.
- ADRs: 0007, 0008, 0023/0024/0026/0037 (unchanged rules), 0042, 0050 (staging
  stays), 0051, 0052, 0053–0056, and 0057 (accepted).

## Risks & tradeoffs

- **R1 Byte bound**: single files exceed today's 2 MB `file_bytes`. A synthetic
  17,385-row file was about 7.7 MB uncompressed, so the raised value is an
  unmeasured initial limit that affects every object kind.
- **R2 Engine-level restriction**: `allowed_paths` is DuckDB configuration.
  Container mounts (only the staged directory, read-only, no network) remain the
  primary boundary.
- **R3 Spill**: behavior with external access disabled still needs a bounded
  spill test. Exhaustion must fail inside existing bounds.
- **R4 Runtime evidence**: a changed worker image or profile invalidates the
  reviewed identity. Startup is blocked until a new local review record exists.
- **R5 Spec mismatch**: resolved; spec and ADR-0057 now state six files per
  generation (one modeled, one public projection per dataset).
- **R6 Reset misuse**: clearing the pointer while data is valid causes an
  unplanned initial load. Mitigated by the expected-ID guard, idle
  preconditions, and an operator-only CLI.
- **R7 Downtime and revisions**: preview/SQL are unavailable until the new
  publication. EIA revisions may differ from the deleted data.
- **R8 Out of scope**: the 58 s vs 40 s overall deadline gap and the cleanup
  defects (see `docs/specs/data-api/preview-flow.md`) are not addressed, and
  the live stall cause stays unresolved.
- **R9 Whole-file rewrite**: every refresh rewrites a few MB, and ancestor
  evidence replay during verification is unchanged.

### Alternatives considered

- Modeled file only, served to workers: rejected; it leaks provenance (TR3).
- Public file only, with provenance from ledger and evidence: matches the spec
  wording but makes merge rebuild prior rows from evidence. Larger, riskier
  change.
- Reader-side projection kept: rejected by FR9.
- One disposition/ledger file per dataset: fewer objects, but not needed;
  deferred.
- Coverage in ArtifactRef metadata or Parquet statistics: rejected in favor of
  verified summaries.
- Per-kind byte bound: more precise, but needs kind-aware object checks across
  stores.
- Reset via documented SQL or TRUNCATE: rejected; it bypasses guards and the
  immutable history.
- Temporary base tables with external access disabled afterwards: violates TR7.

## Test strategy

- **AC1**: integration tests (connector CLI, refresh execution) assert exactly 3
  modeled and 3 public refs, each with `partition=None`.
- **AC2**: manifest validation unit test rejects day-keyed modeled refs; built
  candidates contain none.
- **AC3**: rerun integration test asserts `base_modeled` equals the prior's 3
  refs and that merge reads only them.
- **AC4**: existing retention and rerun cases (absent keys, invalid replacement,
  excluded grain, carry outside interval) produce identical rows and ledgers.
- **AC5**: verification negative cases with a mutated value, origin, ledger row,
  row order or prior file.
- **AC6**: CLI test for default S3 persist plus full readback (fake or local S3
  adapter) and for `--local-only`.
- **AC7**: injected write, verify and persist failures yield an unsuccessful
  outcome.
- **AC8**: refresh publication rejects a missing, mutated or foreign public ref.
- **AC9**: cache test shows the installed file sha equals the manifest public
  ref and that no Parquet write happens in the reader path. The
  `modeled_from_record` import is absent from `local_cache`.
- **AC10**: catalog preview and query lifecycle tests show one generation for
  all inputs after a new publication.
- **AC11**: failed-run refresh test keeps the active generation.
- **AC12**: a pinned preview sequence survives a new publication, and pinned
  files are not evicted.
- **AC13**: a corrupt or missing public file returns `DataUnavailableError`
  with no fallback.
- **AC14**: an initial-load integration test with no base, plus a v1 manifest
  that is rejected; a reset operation test against PostgreSQL covers the
  guarded clear and the failure cases.
- **AC15**: existing role and continuation-owner tests rerun, including
  revocation.
- **AC16**: schema equality and row-multiset parity of modeled and public files
  against today's codec output.
- **AC17**: national percentage fields round-trip unchanged (ADR-0031 tests).
- **AC18**: graph restore plus replay verifies evidence, dispositions, ledgers
  and reports.
- **AC19**: worker unit tests (DuckDB) show other paths, `COPY`, `INSTALL` and
  setting changes fail; Docker runtime tests confirm the mount scope.
- **AC20**: preview contract tests (filters, order, 100/500, expiry) unchanged.
- **AC21**: SQL compatibility suite (joins, aggregates, CTEs, subqueries,
  windows) over views.
- **AC22**: query results and lifecycle tests: single execution, fixed expiry,
  1,000-row/1-MiB limits.
- **AC23**: engine test asserts `VIEW` table type, no base table, and a
  `READ_PARQUET` plan.
- **AC24**: bounded memory/spill exhaustion test plus the existing single-slot
  busy test.
- **AC25**: opt-in `tests/acceptance/test_query_runtime.py` and the
  user-directed live run (phase 9). Results are reported as run or not run.
- **AC26**: per-dataset bound tests at baseline sizes (30,000-row limits,
  raised byte limit), plus the phase 9 run.
- **Dead code**: repository search finds no references to the deleted symbols
  (`index_modeled`, `prior_day`, `PartitionIndex`, reader projection, `.create(`
  in worker engines); Ruff unused-import checks and mypy pass; coverage shows no
  orphaned old-layout branches.
- Always: Ruff, mypy, pytest including `tests/architecture`.

## Assumptions

- Current baseline about 27,600 rows (generators ~17,385, facilities ~10,065,
  national 183); no growth (TR10).
- Merged day output is already sorted by key, so concatenation in ascending day
  order yields a globally sorted file.
- The malformed-date group produces dispositions only, no modeled rows.
- HTTP refresh (ADR-0051 configured range) performs the publishing initial load;
  the CLI produces durable candidates only.
- Worker staging, ApprovedFile and the pin lifetime contracts stay unchanged.

## Open decisions

_None._ Resolved October 6, 2026: ADR-0057 accepted (D1); one modeled plus one
public projection file per dataset, six per generation, with spec and ADR
updated (D2); publication reset recorded in ADR-0057 (D3); initial `file_bytes`
32,000,000, unmeasured (D4).
