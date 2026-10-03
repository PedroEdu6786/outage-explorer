# Plan: EIA data connector
> Status: draft · Slug: data-connector · Spec: ./spec.md

## Approach

Build a separately supervised refresh entry point inside the accepted layered
Flask monolith, using application-owned ports for EIA, bounded Parquet work,
immutable S3 artifacts and PostgreSQL coordination. Reuse the existing pure
observation policies, preserve replayable evidence, and publish one manifest
covering all three grains through a short operational transaction. Implement
recorded/synthetic cases first; live pagination evidence and measured limits gate
live enablement, while the deferred facility total discrepancy does not block work.

**Decision status:** structures and mechanisms below are proposals, not additional
accepted ADRs. ADR-0001/0002/0003/0023–0027/0030–0037 and the spec constrain them.
This plan takes precedence over older *proposed* interval-deletion/latest-30-day
mechanisms in the [backend plan](../outage-explorer-backend/plan.md); neither is
selected here. [ADR-0037](../../adr/0037-connector-initial-load-and-retention.md)
accepts the initial live interval, absent/partial-exclusion retention and numeric
storage direction; phase 2 now implements and verifies the physical widths documented below;
cloud adapters and runtime mechanisms remain subject to their later gates. No deployment, source request or publication is performed by this plan.

## Components affected

- **Domain observations** — reuse `assess`, `select_daily`, `calculate` and
  `present_percentage`; add only interval-independent merge/accounting policies
  where behavior requires them. Keep `VerifyBaseline` and its September constants,
  report formats and evidence contracts unchanged. (FR7–FR13; TR2–TR4, TR8)
- **Application refresh services and DTOs** — authorize admission/status, orchestrate
  retrieval, modeling and publication, and produce durable bounded outcomes.
  Application owns transaction boundaries and policy gates. (FR1–FR20)
- **Application ports** — access checks, source pages, candidate construction,
  artifact storage and refresh repository contracts; no SDK/framework types cross
  these interfaces. (FR1–FR6, FR17–FR20; TR1, TR4–TR5)
- **EIA infrastructure** — allowlisted daily routes, metadata/page envelopes,
  sanitization, bounded transport/retries and recorded request order. (FR4–FR6, FR14–FR15)
- **Parquet infrastructure** — raw/evidence writers, partitioned transformations,
  retained-row merge, exact-value round trips and whole-generation verification.
  No operational analytical-row tables or API-process DuckDB. (FR6–FR16; TR1–TR4)
- **S3 infrastructure** — immutable uploads, explicit object verification and
  manifest retrieval; authoritative data never depends on local staging.
  (FR17–FR20; TR1, TR10)
- **PostgreSQL infrastructure** — run/outcome records, idempotent admission, fenced
  ownership and atomic active-generation publication. (FR2–FR3, FR17–FR20; TR1)
- **Entrypoints and bootstrap** — thin Admin HTTP admission/status, controlled initial-load
  CLI and supervised refresh worker; startup constructs dependencies without
  fetching EIA or starting refresh in imports/app factories. (FR1–FR3; TR1, TR9)

## Data model changes

### Analytical and evidence schemas (FR6–FR16; TR1–TR4, TR8)

All schemas are explicit and versioned. A generation manifest lists exact objects,
SHA-256 hashes, byte/row counts, partition keys, schema/contract/transformation
versions and referenced prior evidence. No prefix listing defines a dataset.
The following are physical Parquet types; required fields are non-null unless
marked optional. UTF8 means Parquet string, not an inferred numeric column.

| Dataset | Physical fields and meaning |
| --- | --- |
| `raw_observations_v1` | `dataset`, `run_id`, `retrieval_id`, `request_id`, `page_id`: UTF8; `source_position`, `page_index`, `row_index`: INT64; `retrieved_at`: UTC microsecond timestamp; `interval_start/end`: DATE; `value_json`: UTF8 containing one sanitized JSON value, including invalid non-object rows. Preserve JSON string contents and types without coercion. |
| `raw_pages_v1` | Same request/retrieval identities; offset/length/attempt/returned count: INT64; sanitized route/parameters/envelope metadata/API version: UTF8 JSON; source total: UTF8 integer string; received time: timestamp; ordered page digest and raw-row file references. One accepted page per offset; bounded attempt failures are separate evidence. Empty terminal pages are recorded. |
| `row_dispositions_v1` | Dataset/retrieval/source position; disposition enum as UTF8; optional winner position; optional trustworthy DATE and identity strings; reasons as LIST of STRUCT(`field`: UTF8, `code`: UTF8). Raw reference preserves original invalid data. |
| `national_daily_v1` | `period`: DATE; `capacity_source`, `outage_source`, `reported_percentage_source`: UTF8; `capacity_mw`, `outage_mw`, `reported_percentage`: DECIMAL(38,12); units: UTF8 constants checked against the source; exact calculation and provenance fields below. Key: `period`. |
| `facility_daily_v1` | National fields plus `facility`, `facility_name`: UTF8. Key: `(period, facility)`; name is an attribute. |
| `generator_daily_v1` | Facility fields plus `generator`: UTF8. Key: `(period, facility, generator)`. |
| Exact calculation fields | `share_numerator`, `share_denominator`, `percentage_numerator`, `percentage_denominator`: UTF8 integer strings; denominators positive and ratios reduced. `calculated_percentage_display`, `reported_percentage_display`: UTF8, half-up to two decimals; `calculated_percentage_rounded`: DECIMAL(38,2) matching the displayed calculated value, explicitly a presentation projection, not the exact ratio. Each grain derives from its own selected row. |
| Provenance fields | `origin_run_id`, `origin_retrieval_id`, `origin_request_id`, `origin_page_id`: UTF8; `origin_source_position`: INT64; original contract/transformation versions and raw object/row reference. Retained rows keep these fields unchanged. Current merge decisions belong to the generation ledger, not rewritten origin fields. |
| `merge_decisions_v1` | Dataset/key, action (`new`, `replace`, `retain_invalid`, `retain_absent`, `carry_outside_interval`), old/new evidence references as applicable, linked incoming exclusion references; distinguishes refreshed values from carried data. Full-dataset retention uses these mutually exclusive key-level actions without double counting. |

- **Exact decimal representation:** retain source strings and exact rational pairs,
  plus verified v1 DECIMAL(38,12) numerical measurement columns for usable analytics
  (26 integer digits, 12 fractional places). Before writing, prove each parsed
  measurement fits exactly; reject any required rounding, overflow or truncation
  with `representation_error`, a candidate/run failure that preserves active data,
  never a row exclusion or a narrowed domain validation rule. All three baseline
  profiles fit this v1 representation; the sample does not prove historical
  fit. Numeric calculated percentage has only the accepted two-decimal presentation
  rounding; no finite decimal purports to exactly represent a repeating ratio.
  Overflow in that DECIMAL(38,2) projection is also a representation error.
  Source notation and rational outputs remain authoritative for precision/replay.
  Typed decimals plus original strings and explicit representation failure are
  accepted by ADR-0037; verify exact representability of each candidate before publication; phase 2 verifies these
  physical widths against recorded and adversarial inputs. A valid source value beyond
  its range requires a reviewed schema change, not silent loss. Arrow documents scaled
  integer decimal precision in [decimal128](https://arrow.apache.org/docs/python/generated/pyarrow.decimal128.html).
  (TR2–TR3)
- Arithmetic expansion can exceed operational limits even for valid inputs.
  Inspect bounded coefficient/exponent complexity before `calculate`; exceeding
  configured arithmetic/field/row/byte budgets fails the **run** with a resource
  error, never `invalid_number` or silent truncation. Budget values and supported
  range need measurement under Q1; no fabricated production limits. (FR5; TR5)
- Sanitize before persistence/logging: construct request identity from allowlisted
  route and nonsecret parameters; omit authentication, untrusted headers and raw
  exception text. Recursively redact credential keys and actual configured secret
  values from echoed metadata/row values, recording redaction paths. Unchanged
  observation strings retain exact content; any redacted observation is marked in
  evidence and cannot silently acquire a different modeled meaning. Bound parsing
  and sanitization before output. Artifacts are sanitized evidence, never original
  wire bytes; their checksums describe exactly the bytes stored. (FR6; TR4)
- Metadata and sanitized page evidence also preserve source warnings and schema
  descriptors. Raw artifacts/ledgers are Admin evidence, not user SQL inputs.
  Date partitions and bounded row groups support streaming; no sparse coverage
  cell is written as a fabricated zero observation. (FR13–FR15; TR1, TR4)

### Verified local physical implementation (phase 2, 2026-10-02)

`infrastructure/parquet/schemas.py` defines v1 metadata (`kind`, `grain`,
`version`) for raw, pages, dispositions, modeled and merge-ledger files. The
selected library is **PyArrow 25.0.1**; runtime and development resolution pin
that exact version. Measurement columns use decimal128(38,12), and the rounded
calculated percentage uses decimal128(38,2). Tests verify exact edges, source
notation, trailing zeros, low Decimal context precision and failure on scale or
precision loss. Source strings and reduced rational integer strings remain
independent evidence. An unrepresentable otherwise-valid value raises
`RepresentationError`, without adding a source exclusion.

The implementation groups immutable provenance in an `origin` STRUCT containing
all `Origin` fields, including grain, run/retrieval/request/page/evidence identity,
UTC microsecond timestamp, page/row/source positions and contract/transformation
versions. Modeled files expose DATE32 `period`, flat UTF8 `facility` and `generator`
where applicable, an exact ordered `identity` list, and `facility_name` (required
for detail grains, null for national). Dispositions use nullable date/identity,
UTF8 status, nullable INT64 winner and a list of field/code reasons. Merge ledgers
store current and nullable old origins plus incoming exclusion positions.

Raw values are bounded UTF8 JSON containing their original parsed JSON types and
string contents, including invalid observations. Raw/page intervals are DATE32.
Every accepted page has a record, including empty pages, its metadata/parameters
as sanitized JSON, advertised total as UTF8, INT64 offset/length/attempt/count and
ordered full raw-object references. The page object's SHA-256 covers that ordered
reference sequence. Sanitization and transport acceptance remain source-adapter
responsibilities; these local tests provide already sanitized inputs.

The local store writes uncompressed Parquet with explicit schemas, no dictionary
encoding, page checksums, bounded batches/row groups and content-addressed SHA-256
identities. Atomic local installation refuses conflicting existing bytes. Reads
verify bytes/hash/schema/counts and footer row-group limits before yielding rows;
read-ahead and threaded decoding are disabled. Caller-supplied caps cover encoded
fields/JSON depth, batch and row-group rows/bytes, file bytes and cumulative
session objects/bytes. One bounded file buffer can coexist with the bounded
Arrow batch; these are operational guards, not measured production process/RSS
limits. Exceeding a cap fails explicitly. Failed candidate staging is local and
unpublished; durable failed-run evidence/lifecycle handling remains phase 4.

Candidate construction stages bounded raw batches into date partitions, then
selects complete bounded day groups in authoritative source-position order. It
loads at most one configured prior day group at a time, streams historical date
partitions, and reuses unchanged modeled references. Missing days in a nonempty
route retain old rows; a wholly empty route fails. The bounds on incoming/prior/
output rows apply per complete day group. Incoming observed-entity cardinality
uses the output-row cap, reason occurrences are capped per route, and the full
reference graph has an explicit object/byte cap. No accumulated history rows are
materialized together.

Canonical versioned JSON manifests are also immutable objects and can be reloaded
using their exact reference with EIA disabled. They carry all modeled/disposition/
ledger references, raw/page dependencies, verified quality summaries and the
pinned base manifest/hash plus its exact modeled references. Verification checks
those base references, replays every current date group, binds retained rows back
to their original selected raw evidence, and compares complete modeled rows,
dispositions and ledgers. This rejects coherent value/ledger tampering even when
new objects have valid schemas and hashes. Independent read-only verification
rescans bounded evidence batches by date; this trades additional sequential I/O
for bounded row memory and requires measurement/optimization before live enablement.

The result is a local **candidate**, or an explicit `retained_all_excluded`
decision. No API endpoint, active pointer, S3 upload, PostgreSQL write or initial
live load is performed here. An immutable local manifest is replay evidence,
not authoritative production publication.

### Operational metadata (FR2–FR3, FR16–FR20; TR1, TR9–TR10)

| Record | Proposed fields/invariants |
| --- | --- |
| Refresh run | Run UUID, requester reference, idempotency key and canonical request hash, dates, configuration/contract versions, base generation, state/stage, timestamps, owner epoch, candidate reference, terminal reason and bounded quality summary. Unique `(requester, idempotency_key)`; original requested identity is immutable. |
| Refresh coordination singleton | Active owner/run, monotonically increasing epoch, lease deadline and active-generation reference. Short row-locked transactions serialize admission, claim, heartbeat, recovery and publication; time comparisons use database time. |
| Generation | UUID, base generation, immutable manifest key/hash, per-dataset schema/count/coverage summary, verification identity/time and publication time. Only verified generations can be referenced as active. |
| Evidence references | Manifest/quality-ledger references and inherited provenance dependencies; retain published snapshots and findings inputs. PostgreSQL stores references/summaries, not analytical observations or query-ID metadata. |

Quality summaries are bounded; full dispositions live in Parquet. Counts use
nonnegative integers with checked overflow. Received rows partition exactly into
`selected + excluded + duplicate + superseded`. Count excluded rows once; reason
counts use `(field, code)` occurrences. `retained_invalid` counts distinct prior
keys retained for invalid incoming replacements, independent of number of bad
rows; `retained_absent` counts prior in-window keys without any trustworthy
incoming key. Outside-interval keys belong only to `carried_outside_interval`.
`modeled = selected + retained_invalid + retained_absent + carried_outside_interval`
for a publishable merge; replaced old rows are not counted again. Full-dataset
retention follows those same categories. Report candidate modeled counts
separately from active counts when no publication occurs. (FR16; AC15)

## Interfaces & contracts

### Admission, execution and outcomes (FR1–FR3, FR17–FR20)

- `RequestRefresh(principal, start_date, end_date, idempotency_key)` returns
  `RefreshReceipt(run_id, state, status_reference)` after application-owned Admin
  authorization and durable admission. Dates are explicit, inclusive and bounded;
  use the verified prior generation when present. With none, admit controlled
  initial live loading for 2026-04-02 through 2026-10-01 inclusive through the
  same pipeline; every dataset must have usable output before initial publication.
  No implicit clock-based date window or separate September seed is required.
- `GetRefreshOutcome(principal, run_id)` rechecks Admin permission before lookup
  or evidence access. DTO includes requested/received/usable coverage, all route
  quality summaries, limitations, stage, publication status and confirmed generation.
  Denial must not reveal run existence or initiate analytical/source reads.
- Proposed HTTP mapping: `POST /refresh` → 202, `GET /refresh/{run_id}` → outcome;
  malformed dates → 400, denied → 403, conflicting idempotency/admission
  → 409, unavailable operational service → 503. Handlers translate only.
  Authentication/session mapping is an existing separate integration dependency.
- Same idempotency key and identical canonical request returns its original run;
  changed parameters conflict. A new key during occupied ownership is busy. The
  worker claims durably accepted work independently of client disconnection.
- Run states: `accepted`, `running`, `succeeded`, `retained`, `failed`, `interrupted`;
  `retained` has the explicit reason `all_excluded` for an unchanged prior generation.
  Partial-route retention can accompany `succeeded` when other valid updates publish;
  initial loading with an unusable dataset fails without creating an active generation.
  Stages: retrieval, modeling, verification, upload, publication. `succeeded` means
  confirmed publication; `retained` means unchanged confirmed active generation.
  While commit confirmation is unavailable, report `publication_unknown`, not
  success or a fabricated failure/rollback. (FR11, FR18)
- `ExecuteRefresh(run_id, owner_epoch)` operates only after fenced claim. Admission
  authorizes the request; restart does not manufacture a new caller or request.
  Accepted-but-unclaimed work may be claimed after restart. Expired running work
  is reconciled and marked interrupted if unpublished; no automatic page-resume
  or automatic rerun. Explicit retry uses a new run/key. (FR2–FR3, FR18–FR20)

### Source and artifact ports (FR4–FR8, FR14–FR18; TR1, TR4–TR8)

| Port operation | Input → output / failure boundary |
| --- | --- |
| `AccessPolicy.require_admin` | Verified application principal → authorized identity; denial/unavailable policy fails closed. |
| `SourcePages.fetch_metadata / fetch_page` | Dataset, explicit interval, page request, retry/deadline budget → sanitized metadata/page DTO; transport/envelope/progress/budget errors are run failures. |
| `CandidateBuilder.build / verify` | Ordered raw references, contracts, interval, pinned base manifest, bounds → candidate manifest draft and quality ledger; merge ambiguity, duplicate keys or resource failure cannot publish. |
| `ArtifactStore.put_immutable / verify / read` | Server-generated reference, bounded bytes/stream, expected hash → verified reference; mismatch/existing-different-object fails. No caller-provided arbitrary URLs/paths. |
| `RefreshRepository.admit / claim / heartbeat / transition / publish / reconcile` | Run/request/epoch and expected base generation → durable state; stale owner, conflict or uncertain commit has explicit results. Publication commits active reference and successful outcome together. |

- Use allowlisted `us-nuclear-outages`, `facility-nuclear-outages` and
  `generator-nuclear-outages`, daily frequency, all three measurements, explicit
  start/end, offset and length. Propose ascending period then opaque facility then
  generator sorting as applicable. EIA documents offset/length, multi-column sort
  and at most 5,000 JSON rows; route-specific paging stability is still a live
  evidence gate, not established by general [API documentation](https://www.eia.gov/opendata/documentation.php).
- Retrieve routes/pages sequentially initially. Assign each accepted page a stable
  index and each received row a monotonically increasing route-local source
  position before modeling. Retry the same offset without appending failed attempts
  as new rows. Original page/row sequence defines the fallback winner, not task
  completion time or an invented revision timestamp. (FR8; TR8)
- Proposed termination: begin offset zero, advance by received count, and continue
  through short pages until a successfully received empty page. Record that empty
  page and every requested offset. Never stop solely because received count reaches
  advertised total. Confirm this behavior with small-page live captures on every
  route before enabling it; general docs do not prove this termination contract.
- Detect repeated nonempty page payloads at advancing offsets, nonadvancing cursors,
  invalid totals/envelopes, unexpected route/frequency, interpretable out-of-window
  dates and unsupported ordering behavior as run failures. Preserve malformed rows
  for ordinary assessment when the enclosing response remains usable. Zero rows
  for an entire requested route is `empty_source` failure, not all-excluded success.
- Capture each page's advertised total as a nonnegative ASCII integer string;
  never add repeated totals across pages. Report changed totals and count mismatch.
  Draft `facility_total_diagnostic_v1` makes a facility advertised-total mismatch
  diagnostic only, regardless of magic numeric values. It exempts no requested
  page, envelope, resource, progression or integrity check. National/generator
  inconsistencies require failed retrieval pending reviewed evidence. (FR14–FR15)
- Retry transient connection/read errors, HTTP 429 and 5xx within a configured
  attempt cap and total deadline; bounded exponential backoff with jitter honors
  Retry-After only within those bounds. Do not retry other 4xx or malformed data
  blindly; reject redirects away from the allowlisted host. Cap request/page bytes,
  rows, pages, attempts, elapsed time, interval days and staging/output bytes.
  A killed resource-bounded worker becomes interrupted on recovery. (FR5; TR5)

### Modeling, merge and initial live load (FR7–FR16; TR2–TR3, TR6, TR8–TR9)

- Stream raw evidence into date partitions under bounded staging; collect only a
  bounded day/grain assessment group, then call existing `select_daily` once for
  that complete group. Global source positions preserve cross-page A/B/A behavior.
  Reuse `assess` and `calculate`; never call the fixed-window `VerifyBaseline` on
  arbitrary live intervals. Exceeding a group/buffer budget fails the run.
- Validate before selection; equality includes parsed values, identity/date and
  facility name. Invalid date/identity prevents matching; never infer a key. Retain
  observed identifiers for coverage even where measurements/date are invalid;
  no complete historical entity roster is claimed. (FR7–FR8, FR14)
- Stream-merge each affected date partition against the pinned base generation:
  valid incoming winners replace existing keys; otherwise trustworthy incoming
  excluded keys keep matching old valid rows and origin provenance. Preserve old
  partitions outside the requested dates by immutable references. Check uniqueness
  across the complete logical manifest, including file-boundary adjacent keys and
  retained/new rows; bounded sorted merge avoids loading accumulated history.
- If prior in-window keys have **no** incoming trustworthy key after successful
  retrieval, retain their values and original provenance as `retain_absent`,
  report the absence separately from invalid replacements, and publish other
  valid changes when all integrity checks pass. Absence never implies deletion.
  (FR10; TR6, TR10; ADR-0037)
- Nonempty incoming data with every row excluded across all routes gives accepted
  `retained/all_excluded` when previous data exists. If only a subset of routes
  has nonempty entirely excluded input, retain those complete prior datasets and
  publish valid changes from other routes. Partition their retained keys into
  invalid, absent and outside-interval categories without overlap. Empty or
  failed retrieval is never made publishable by this fallback. (FR10–FR11; TR9)
- A controlled initial live load uses 2026-04-02 through 2026-10-01 inclusive
  through the same retrieval/modeling/storage/publication pipeline. Require an
  empty active pointer, usable output in all three datasets, verified artifacts
  and an authorized explicit invocation. No previous generation means no fallback
  for an entirely excluded dataset; fail without publication. The September
  bundles remain offline regression evidence, not mandatory initial product data.
  (TR6, TR9; ADR-0037)

### Publication and recovery (FR3, FR17–FR20; TR1, TR10)

- The worker heartbeats a database-time lease; every durable transition checks the
  owner/run/epoch. Reclaiming expired ownership increments the epoch. Old workers
  may finish private work but cannot publish; no database lock spans network or
  Parquet work. PostgreSQL supports the proposed short row-lock transactions;
  exact isolation/retry behavior must be tested against the pinned version.
  See [PostgreSQL locking](https://www.postgresql.org/docs/current/explicit-locking.html).
- Upload server-generated immutable run/generation keys, then read back objects
  in bounded batches to verify hashes, byte counts, Parquet schema/readability,
  row counts and exact-value round trips. Do not treat an ETag as SHA-256. Complete
  global-key and ledger checks before uploading/verifying the final manifest.
  Use conditional create to prevent overwrite; same-key retries require identical
  verified content. [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
  support this proposal; IAM and bucket configuration remain deployment work.
- In one short transaction, lock coordination, require current unexpired owner
  epoch and unchanged base active generation, register the verified generation,
  update the active reference, store final quality outcome, mark run succeeded and
  release ownership. Failed comparison aborts; never publish stale-base output.
  S3 writes stay outside the transaction and are not rolled back by PostgreSQL.
- A reader resolves the active generation once, then uses only that manifest's
  complete file set. New readers see the committed generation; existing references
  keep the prior generation. Retain all published objects and dependencies for
  now; this connector does not implement query continuations or deletion policy.
- On uncertain commit, reread durable run/generation records after reconnecting.
  Confirmed successful run plus matching publication record resolves success even
  if a later run is now active. Otherwise fenced recovery resolves expired ownership
  and marks unpublished work interrupted. Never blindly republish or undo a newer
  active pointer. Database outage leaves outcome unknown and prevents new claims.
- Crashes before commit leave an unpublished candidate; crashes after commit leave
  recoverable success. Retain accepted sanitized evidence and failed-candidate
  references where available; bound staging and fail early if evidence cannot be
  stored. Disposable local orphan cleanup cannot delete authoritative S3 inputs.

## Implementation phases

1. **Contract-preserving transformation** — exact Parquet schemas, replay, bounded
   selection/merge/accounting with recorded and synthetic data; existing verifier
   outputs remain stable. Unambiguous cases work; policy gates are explicit.
   (FR6–FR16; TR1–TR4, TR6, TR8–TR10)
2. **Bounded source adapter** — fixture-backed multipage/retry/sanitization behavior,
   explicit request/termination contract; collect separate live evidence before
   claiming route guarantees. Facility total diagnosis is not a prerequisite.
   (FR4–FR6, FR14–FR15; TR5, TR7–TR8)
3. **Durable refresh and generation commit** — PostgreSQL integration migrations,
   fenced coordination, immutable artifact verification, publication and crash
   reconciliation; local/controlled adapter tests precede cloud proof.
   (FR2–FR3, FR17–FR20; TR1, TR10)
4. **Authorized orchestration and initial live load** — direct use-case authorization tests,
   independent supervised worker, thin transport and explicit initial-load rehearsal;
   connect verified application identity/permission ports before exposing refresh.
   (FR1–FR3, FR9–FR11, FR16–FR20; TR9)
5. **Live enablement evidence** — measure supported >=30-day reconciliation windows
   and budgets, including the accepted initial interval; validate live paging/order
   and applicability before enabling those paths. Rehearse replacement with EIA
   unavailable and complete relevant Ruff, mypy and pytest checks. (TR5–TR9; AC18)

## Dependencies & integrations

- Pin **PyArrow 25.0.1** for explicit Parquet schemas and bounded batch/row-group I/O;
  phase 2 verifies exact round trips locally. Its
  [Parquet documentation](https://arrow.apache.org/docs/python/parquet.html) describes
  these capabilities. The implementation pins the runtime and development dependency. (TR1, TR3, TR5)
- EIA credential, configured HTTP adapter; S3 SDK/bucket; PostgreSQL driver,
  migration tooling and local PostgreSQL must be selected/pinned before adapter
  implementation. Existing project has health/offline verification only. (TR1)
- Existing authorization/session work supplies verified identity and authoritative
  permissions; ECS supervision and resource enforcement remain runtime gates.
  Fake ports support independent implementation, never proof of production access
  checks, RDS, S3 or process limits. (FR1–FR3; TR5)

## Risks & tradeoffs

- Offset pagination can drift while EIA changes; small-page live evidence and
  fail-closed progress checks bound claims, but cannot prove upstream snapshot
  consistency or revision recency. (FR4–FR5; TR7–TR8)
- Fixed physical numeric columns cannot cover every accepted finite decimal;
  exact companions preserve evidence, while representation errors stop publication
  until a reviewed schema can represent those otherwise-valid inputs. (TR2–TR3)
- Huge valid decimals or large entity-days can exhaust resources; preflight
  complexity and enforced budgets fail runs without misclassifying rows. (TR5)
- PostgreSQL/S3 cannot share a transaction; immutable verified artifacts plus
  fenced metadata commit and reconciliation prevent partial visibility. (FR18)
- Accepted absence/partial-exclusion policies can retain old data; report their
  origin and retention reason explicitly rather than implying freshness. (TR6, TR9)
- Retaining authoritative evidence grows storage; bound each run and do not
  silently introduce lifecycle deletion to solve capacity pressure. (TR5, TR10)

### Alternatives considered

- Fixed DECIMAL columns without exact companions/representability checks: rejected
  because the accepted grammar has no fixed precision/scale ceiling. (TR2–TR3)
- In-place Parquet updates or interval deletion on missing keys: rejected because
  readers need immutable generations and absent keys retain prior valid data
  under ADR-0037. (FR19; TR6)
- Request-owned threads or a broker: the former cannot establish independent
  supervision; the latter adds infrastructure outside accepted scope. (FR2; TR1)

## Test strategy

- **AC1–AC2:** direct application calls with denied roles and fake I/O spies;
  PostgreSQL competing admissions/claims, stale epoch and lease-expiry races;
  worker/client disconnect integration demonstrates independent execution.
- **AC3–AC4:** bounded page fixtures for all routes exercise full/short/empty
  pages, boundary duplicates, retry identity, repeated payloads, malformed totals,
  ordering failures and each resource cap. Separate live evidence records actual
  paging behavior; mocked requests do not satisfy that live gate.
- **AC5–AC7:** replay cross-page raw Parquet and compare observable dispositions,
  source strings, exact values and references; use credentials in echoed/nested
  payloads, invalid types/fields/units/dates/identifiers, A/B/A, renamed facilities,
  equivalent decimals and late invalid rows. Existing verifier behavior remains.
- **AC8–AC11:** real Parquet merge fixtures exercise repeated refresh, valid
  revisions, identifiable invalid replacements, unknown keys, all-excluded cases,
  retained-absent rows, complete prior-dataset retention for partial all-exclusion,
  initial loading without prior data, and duplicate keys split across output files.
- **AC12:** exact rational and half-up boundary cases, zero/negative permitted
  measurements, exponents and long coefficients survive round trips; independent
  expected arithmetic proves national values never derive from detail sums. Test
  exact representability boundaries and otherwise-valid overflow/scale excess:
  candidate failure preserves active data and does not inflate excluded counts.
- **AC13–AC15:** observed-roster/missing-day cases and multiple reasons verify
  coverage and accounting identities. The recorded facility mismatch and a
  differently sized synthetic facility mismatch both remain visible/nonblocking;
  pair each with failed-page cases that still prevent publication.
- **AC16–AC17:** real PostgreSQL transactions plus artifact fault injection at
  upload, readback, manifest verification, precommit, commit acknowledgment and
  recovery; two pinned readers observe complete different generations. An unknown
  commit response never becomes reported success without durable reconciliation.
- **AC18:** reconstruct services/local staging from durable metadata/artifacts
  with EIA disabled; published data, outcomes and inherited evidence remain usable.
  Rehearse cloud adapters separately; local substitutes cannot prove AWS behavior.
- Run existing architecture gates and regression tests; extend only a necessary
  narrow worker/CLI startup exception. Add behavior tests rather than new mirror
  or file-layout tests. Documentation checks alone prove no runtime guarantees.

## Assumptions

- Initial live dates are explicitly 2026-04-02 through 2026-10-01 inclusive;
  subsequent refreshes also use explicit bounded dates. No rolling anchor is
  selected, and September remains offline verification evidence. (TR6; ADR-0037)
- Facility advertised-total differences alone are deferred diagnostics. Known
  failed pages, corruption and exhausted budgets remain failures. (FR15; TR7)
- Proposed ports, concrete storage schemas and lease mechanism are reviewable
  design choices. ADR-0037 accepts the product policies; writing this plan does
  not itself accept additional architectural boundaries. Independent phases can
  proceed while engineering evidence is collected.

## Open decisions

- **Q1:** measure concrete interval/request/arithmetic/memory/disk/output limits
  and enforceable worker budgets before production enablement; support the
  accepted >=30-day reconciliation use case without inventing measurements.
- **Q3–Q4:** validate route-specific termination, ordering/ties, source drift and
  contract applicability beyond September. No recency or upstream-completeness
  claim follows from recorded order. Facility total investigation stays deferred.
- Pin adapter libraries/PostgreSQL tooling and verify proposed implementation
  mechanisms during their affected phases; session mapping and ECS resource
  enforcement remain separate runtime integration work. No new auth design,
  deletion subsystem or cloud deployment is selected here. Verify the concrete
  numeric physical widths/scales before publication; typed decimals plus source
  strings and explicit representation failure are already accepted.

## Resolved product decisions

- **Q2:** ADR-0037 accepts the initial 2026-04-02 through 2026-10-01 interval,
  explicit dates without an automatic rolling anchor, and retention of absent
  prior keys while other valid changes publish.
- **Q5:** ADR-0037 accepts initial live loading through the refresh pipeline,
  usable output from all three datasets before first publication, and complete
  prior-dataset retention for partially all-excluded refreshes. All-three-excluded
  input retains the active generation without publication.
