# Plan: Data browsing, SQL, and background refresh
> Status: draft · Slug: data-api · Spec: ./spec.md

## Approach

Extend the existing layered Flask monolith with application-owned catalog,
preview, query and refresh use cases, reusing current access checks and verified
connector artifacts. PostgreSQL owns refresh coordination and publication; S3
owns immutable generations; one bounded analytical execution produces either a
preview page or a retained SQL result. A separately supervised refresh process
claims durable admissions and reconciles lost owners without automatically
repeating interrupted source work. This plan selects draft interface and lifecycle
mechanisms; runtime enablement remains gated on isolation and resource evidence.
(FR1–FR30, TR1–TR9)

Grounding: current `AccessService.authorize` checks fresh sessions/roles and
trusted grain enums; HTTP composition already injects auth services and transport.
`CreateConnectorCandidate`, `CreateDurableConnectorCandidate`, Parquet schemas,
`CandidateManifest`, `GrainSummary` and S3 graph replay exist. Product SQL, cache,
result storage, durable refresh/publication and their HTTP endpoints do not.
Extend these seams rather than treating contributor receipts as published data.
See [structure](../../context/code-structure.md),
[contract discussion](http-contract.md), [analysis](design-notes.md), and
[connector plan](../data-connector/plan.md). No `CLAUDE.md` was found.

## Components affected

- **Domain dataset/query/refresh policies** — versioned public projections,
  cursor identity, bounded result rules and refresh transitions; reuse existing
  observation/retention arithmetic. (FR4–FR10, FR18–FR30, TR2–TR4, TR8–TR9)
- **Application access, catalog and preview services** — fresh authorization,
  permitted metadata, snapshot selection and date-only browsing. Catalog filters
  server-owned grain definitions; it must not pass an empty analytical grain set
  to the existing policy, which deliberately denies that set. (FR1–FR6, FR10,
  FR12, FR19–FR20, TR1–TR2)
- **Application query service and ports** — inspect references, authorize all
  grains, reserve capacity, prepare inputs, execute once and serve retained pages.
  (FR1, FR3, FR7–FR12, FR20, TR1, TR3–TR7)
- **Application refresh services and connector integration** — admission,
  execution, quality mapping, publication and recovery through narrow ports.
  Reuse connector services directly, not their CLI or bootstrap entry point.
  (FR13–FR30, TR8)
- **PostgreSQL operational adapters** — additive migrations, run records,
  coordination and publication transactions, using existing process-owned pool
  conventions and explicit migration tooling. (FR13–FR19, FR22–FR30, TR1, TR8)
- **S3 and verified local modeled cache** — resolve only published manifests,
  validate object identity/schema, pin generations and supply exact authorized
  files. Keep raw/provenance graphs outside analytical mounts. (FR3, FR5–FR8,
  FR18–FR24, TR5, TR7–TR9)
- **SQL inspection, isolated execution and result encoding adapters** — DuckDB
  dialect analysis, restricted runtime and bounded canonical tabular output.
  The API process never executes DuckDB. (FR7–FR12, TR3–TR7)
- **Ephemeral continuation/result adapters** — process-owned metadata, private
  result spool, capacity reservations, cursor validation and independent cleanup.
  (FR5, FR9–FR11, FR20, TR2–TR6)
- **HTTP schemas, routes and auth transport** — seven route/method contracts,
  shared safe errors, CSRF/CORS extensions and no-store responses. (FR1–FR17,
  FR29, TR1–TR4)
- **Bootstrap, settings and supervised entry points** — inert construction,
  explicit process lifecycle, periodic cleanup/reconciliation and separately
  bounded query/refresh resources. (FR11, FR13–FR15, FR25–FR30, TR5–TR8)

## Data model changes

### Durable operational records

| Record | Fields and invariants |
| --- | --- |
| Refresh run | UUID, requester local user, operation/key digest, canonical request identity, immutable interval and nonsecret configuration/version snapshot, base generation, status/stage, timestamps, owner epoch, candidate manifest identity, bounded quality and safe failure. Unique requester/operation/key; admission is committed before acknowledgement. |
| Coordination singleton | Active run, monotonically increasing fencing epoch, owner identity, database-time lease deadline and active generation. One accepted/running/unresolved run occupies admission. |
| Published generation | UUID, unique publishing run, base generation, immutable manifest key/hash, verification version/time and dataset schema/count/coverage summaries. Publication history persists independently of which generation is active. |

Application ports define transaction boundaries; adapters take short row locks.
No transaction spans source retrieval, S3 transfer or analytical execution.
Publication atomically records the generation, switches the active reference,
marks the run successful and releases coordination. Compare run, epoch, unexpired
lease and expected base generation in the same transaction. Durable records
contain references/summaries, never analytical rows or query-ID metadata.
(FR13–FR19, FR22–FR30, TR8)

### Ephemeral records and public schema

- **Preview sequence:** opaque sequence identity, original user, grain,
  generation, normalized inclusive bounds, fixed ordering/page size, creation
  and fixed expiry. Authenticated opaque cursors carry sequence identity and
  page-start key; deterministic keys avoid a growing server list of every visited
  page. Bound sequence count/bytes independently from SQL results. (FR5, FR10–FR11,
  FR20, TR1–TR2, TR6)
- **Query result:** opaque query ID, original local user, referenced grains,
  generation identity, fixed page size, completion/expiry, column descriptors,
  retained count, truncation, private spool reference and bounded row offsets.
  Reservation counts include in-flight queries. No SQL text is needed to page.
  Keep payloads immutable; page readers hold short leases against concurrent
  cleanup. Expiry prevents new reads even if deletion is still finishing.
  (FR9–FR11, FR20, TR1, TR3–TR6)
- **Public schema v1:** stable relation names `national`, `facilities`,
  `generators` map to internal grains `national`, `facility`, `generator`.
  All expose `period` (date), `capacity_mw`, `outage_mw`,
  `reported_percentage` (decimal 38,12). Detail relations additionally expose
  `facility`, `facility_name` (strings); generators also expose `generator`
  (string). National additionally exposes `calculated_percentage_rounded`
  (decimal 38,2), `percentage_numerator`, `percentage_denominator`,
  `calculated_percentage_display`, `reported_percentage_display` (strings).
  These fields exist in the implemented modeled schema; verify nullability
  against each supported published schema. Hide storage/provenance fields.
  Bind the same projection to catalog, preview and SQL, without adding columns
  to a user's SQL projection or changing stored source schemas. (FR2, FR6, TR9)

## Interfaces & contracts

### HTTP and browser transport

| Operation | Input → output and boundary |
| --- | --- |
| `GET /api/datasets` | Current session → `generation_id`, permitted dataset descriptors: `id`, `sql_name`, `label`, `schema_version`, ordered `columns`, `supported_filters`, stored `coverage`. No publication → `503 data_unavailable`. |
| `GET /api/datasets/{dataset}/preview` | Initial optional `start_date`, `end_date`, `page_size`; continuation accepts only `cursor` → `dataset`, `generation_id`, `columns`, `rows`, fixed `page_size`, `page_cursor`, `next_cursor`, `has_more`, `expires_at`. |
| `POST /api/query` | JSON `sql`; URL `page` default 1, `page_size` default 100/max 500 → one execution's tabular result with `query_id`, `generation_id`, `page`, `page_size`, `retained_row_count`, `total_pages`, `has_more`, truncation/reason, limits and `expires_at`. Initial page may exceed 1; SQL is still executed only once. |
| `GET /api/query` | Required URL `query_id`, `page`; optional matching `page_size` → same result envelope, no execution. |
| `POST /api/refresh` | JSON `{}`, required `Idempotency-Key`, current Admin → durable receipt: `run_id`, status, `effective_interval`, `status_url`; new admission `202` with `Location` and `Retry-After: 3`. |
| `GET /api/refresh/{run_id}` | Current Admin and run ID → durable progress/outcome described below. |
| `GET /api/refresh/latest` | Current Admin → `run` containing the same outcome, or null; active/unresolved first, otherwise latest admission timestamp then UUID. |

(FR1–FR17, FR29, TR1–TR4)

- Extend existing cookie/Origin/CSRF transport to these routes. Both POSTs
  require permitted Origin and application-validated session CSRF. Allow
  `Idempotency-Key` in refresh preflight; expose `Location` and `Retry-After`
  through CORS. Apply no-store and exact credentialed CORS to success/errors.
  Do not duplicate auth/session logic or assume route decorators authorize use
  cases. Reject duplicate/unknown parameters, unsupported bodies and malformed
  dates/integers. Bound SQL/request size before parsing. (FR1, FR8, FR12, TR1)
- First resolve a valid current identity, then perform server-side SQL reference
  analysis and authorize the complete grain set before manifest/cache access.
  Continuations validate ownership and reauthorize the stored grains before
  reading payloads. Unauthorized dataset guesses return generic unavailable;
  known denied operations return forbidden without leaking schemas. (FR1–FR3,
  FR8–FR10, TR1, TR7)

### Preview sequencing

- Each omitted date side is unbounded within the published coverage; reject
  reversed dates. Order by `period DESC`, then ascending facility/generator
  identifiers using a fixed binary UTF-8 comparison, preserving identifiers as
  strings. Source retrieval ordering remains independent. Use keyset continuation
  against verified natural keys; server-generated preview SQL may supply its own
  predicates/order/limit through the isolated executor. (FR4–FR5, TR2)
- Return a cursor for the current page, including page 1. Previous navigation
  resubmits a visited cursor; it never requests a fresh first page. A cursor
  cannot change user, dataset, filters, page size, generation or expiry.
  Its sequence expires 60 seconds after first-page creation. Empty filters
  return a valid empty page. A page-size/filter change starts a new sequence.
  (FR5, FR10, FR20, TR2)
- Preview is a bounded page read, not a retained SQL execution subject to the
  1,000-row history cap. It shares the single analytical slot and deadlines;
  bound each response's encoded bytes. If a modeled row cannot fit, fail with a
  resource error rather than skip it or change cursor position. (FR4–FR5, FR12,
  TR2, TR5)

### SQL inspection, execution and retention

- Use a parser adapter for the DuckDB dialect to resolve catalog references
  through CTE scopes, joins, subqueries and windows. Reject writes, multiple
  statements, configuration/extension changes, external scans, system catalogs,
  paths and unresolved dynamic access. Validate functions/reference-producing
  constructs, not just top-level statement type. Parser acceptance and engine
  compatibility require paired tests; do not invent broad exclusions to cover
  adapter gaps. A reference-free analytical expression still requires a current
  recognized role and a deliberate authorization path; the current empty-grain
  denial must never become an accidental bypass. (FR7–FR8, TR1, TR7)
- An execution port receives unchanged SQL, approved relation projections,
  exact verified read-only file handles/mounts and enforced limits; returns a
  completed bounded result or typed failure. Reserve capacity before downloads;
  one slot covers preparation through worker termination/reaping. Bound parsing,
  preparation and total request time separately; execution and result production
  have the accepted 10-second deadline. GET result paging takes no worker slot.
  (FR7–FR9, FR12, TR3–TR7)
- Recommend a Linux isolated worker launched with a minimal environment,
  network disabled, only approved modeled files read-only, private bounded
  temporary/output storage, hard memory/process limits and termination of its
  entire process group. DuckDB memory is below the hard ceiling; external access
  and extension loading are disabled. Concrete launcher feasibility is Phase 1
  evidence, not an assertion that a Python subprocess or SQL parser provides
  isolation. Unsupported local platforms can run pure/controlled tests; product
  SQL fails closed until a verified launcher is configured. (FR8, TR5, TR7)
- Freeze a canonical compact UTF-8 JSON retained document containing ordered
  column metadata, complete row arrays and fixed result metadata. Count braces,
  separators, escaped strings, schema and metadata once inside the 1,048,576-byte
  result budget; reserve bounded metadata space before appending rows. Maintain a
  separate bounded offset index and HTTP page envelope. Page envelopes repeat
  metadata but grant no additional result capacity. (FR9, FR12, TR3–TR4, TR6)
- Retain only the contiguous complete-row prefix fitting both caps. A bounded
  lookahead distinguishes exactly 1,000 rows from row truncation. At the first
  non-fitting row stop with `byte_limit`, never skip ahead; if row 1 is too large,
  return zero retained rows with explicit byte truncation, distinct from an empty
  query. Schema/fixed metadata alone exceeding budget yields
  `422 query_resource_limit`. Page 1 exists even for zero rows; row offsets fix
  all numbered boundaries. Reserve encoding scratch and bound nesting/cell/schema
  expansion before materializing arbitrarily large values. (FR9, FR12, TR4–TR6)
- Preserve duplicate labels using ordered column descriptors plus row arrays.
  Integer/decimal cells are strings; finite floats are JSON numbers, non-finite
  floats use `NaN`/`Infinity`/`-Infinity` strings under typed metadata. Temporal
  values use ISO strings, preserving timezone-free values and normalizing instants
  to UTC. Binary is base64; lists recurse, structs are field-ordered arrays and
  maps are key/value-pair arrays with recursive type metadata. Null remains null;
  pagination counts remain bounded JSON integers. Verify engine types before
  claiming support; representation failures are explicit, never lossy coercions.
  (FR6–FR9, FR12, TR4, TR7, TR9)
- Complete retention before returning any page. The fixed 60-second expiry
  starts at completion. Release input cache pins once SQL materialization ends;
  the immutable retained result needs its generation identity, not the original
  input files. Preview sequences retain generation references and may reload
  verified files from immutable S3 if evicted locally. Active file use is pinned.
  (FR5, FR9–FR11, FR20, TR2–TR6)
- Recommend one threaded API process owning the ephemeral stores and one
  analytical admission gate for this draft. Reject incompatible multi-process
  configuration unless shared ownership is explicitly designed; one replica
  alone does not make in-process limits global. Explicit startup/shutdown manages
  a cleanup loop; factory/imports start no threads. Private spool directories carry
  process-instance ownership; cleanup handles only proven dead/expired owners and
  never active readers or durable artifacts. (FR10–FR11, TR5–TR6)

### Refresh lifecycle and publication

- Resolve operator-managed `refresh.start_date`, `refresh.end_date` and
  `refresh.max_interval_days` in typed startup configuration, with candidate and
  S3 budgets validated together. Changes require controlled configuration reload
  at process restart, not a new endpoint. Persist resolved nonsecret settings and
  contract versions; queued work executes that snapshot. Initially cap the
  configurable interval at 183 days, matching the accepted initial interval and
  connector starting profile, subject to resource verification; a broader range
  needs evidence/config review. With no active generation require exactly
  April 2–October 1, 2026 rather than silently overriding configuration.
  (FR14, FR23–FR24, TR8)
- Validate an opaque 16–128-character ASCII key from letters, digits, hyphen and
  underscore. Scope its digest to local user and refresh operation. Same key
  returns the original frozen run before resolving changed current configuration;
  return `202` while nonterminal, `200` when terminal. A deliberate retry supplies
  a new key/run and uses current settings. Retain key binding with durable run
  records; no independent automatic key expiry or deletion in this effort.
  Admission conflicts do not queue a second refresh. (FR13–FR15, FR26–FR29, TR8)
- A separately supervised process polls/claims accepted work transactionally.
  Claim records running status and a fencing epoch before any source work.
  Accepted but unclaimed work is picked up after restart; a crash after claim
  follows lost-running-worker recovery even if retrieval had not yet begun.
  Its trusted run identity does not depend on the browser's surviving session.
  (FR13–FR15, FR25–FR28, TR8)
- Compose source retrieval, existing merge/verification, complete S3 graph
  persistence and durable readback through current connector ports. Restore the
  pinned published base through verified graph recovery when needed. Validate
  candidate/base/schema identity before the fenced publication transaction.
  Never publish an existing arbitrary S3 receipt or substitute a local-only
  success. Retained-all-excluded completes without moving the active pointer.
  (FR18–FR24, TR8–TR9)
- Heartbeats renew a database-time lease with owner/run/epoch comparison.
  Recovery serializes on the same coordination row, fences an expired owner and
  checks durable publication records. A matching committed generation/run proves
  success even after another generation becomes active. Otherwise confirmed
  unpublished running work becomes interrupted and releases admission; no source
  work is repeated. API restart alone does not reclaim a healthy owner. Stale
  owners may finish private work but every terminal/publication transition rejects
  their epoch. (FR25–FR30, TR8)
- A connection loss at commit is ambiguous. Reconcile using a fresh connection;
  serialize reconciliation with publication before concluding absence proves
  rollback. Use nonterminal `publication_unknown` / publication `unknown` while
  unresolved and keep admission occupied. If PostgreSQL cannot resolve session
  or status, return `503 service_unavailable`. Do not report an invented unknown
  object from an unavailable database. (FR26–FR30, TR1, TR8)

| Run status | Publication state | Meaning |
| --- | --- | --- |
| `accepted`, `running` | `pending` | Admitted or working |
| `succeeded` | `published` | Durable complete publication confirmed |
| `retained` | `not_published` | All incoming observations excluded; prior generation kept |
| `failed` | `not_published` | Confirmed failure before publication |
| `interrupted` | `not_published` | Lost worker, confirmed unpublished, explicit retry required |
| `publication_unknown` | `unknown` | Reconciliation has not established outcome |

Status returns effective interval, UTC timestamps, stage, all three dataset
entries, nullable quality/coverage and safe failure. Stages are `queued`,
`retrieving`, `modeling`, `persisting`, `verifying`, `publishing`, `finished`;
verification can recur around persistence, so stage is not a percentage.
Publication contains state, nullable generation ID, prior generation ID and
nullable no-publication reason; retention uses `all_incoming_rows_excluded`.
Map source quality and `GrainSummary` directly: received equals selected +
excluded + duplicate + superseded; modeled equals selected + retained-invalid +
retained-absent + carried-outside-interval for a publishable merge. Preserve
active/candidate distinctions and count excluded rows once despite overlapping
reason occurrences. Unknown counts remain null. Durable reports drive status;
best-effort connector log events cannot determine publication. (FR16–FR18,
FR21–FR24, FR29, TR8)

### Errors and capacity

Use the existing `error.code` / `error.message` envelope; optional bounded retry
seconds agree with `Retry-After`. Known result expiry returns 410; unknown/lost or
foreign query IDs return the same generic 404 because process loss cannot prove
prior ownership. Both require explicit resubmission. Preview continuation loss
returns generic 410 without confirming dataset existence. Page 1 of an empty
result returns 200; pages outside the retained range return 400. If an initial
POST requests an out-of-range page, include its owned query ID and expiry in
bounded error details so the caller can GET page 1 without repeating execution.
(FR9–FR12, TR1, TR3)

| HTTP | Codes / policy |
| --- | --- |
| 400 | `invalid_request`, `invalid_sql`, `unsupported_sql`, `page_out_of_range`, `page_size_mismatch` |
| 401 / 403 | Existing `unauthenticated` / `forbidden`; preserve the auth layer's generic CSRF denial |
| 404 / 410 | Generic dataset/query/refresh unavailable / continuation unavailable as above |
| 409 | `refresh_busy`, `idempotency_conflict` |
| 422 / 504 | `query_resource_limit` / `query_timeout` |
| 429 | `result_capacity_exhausted` for per-user retention admission |
| 503 | `query_busy`, global `result_capacity_exhausted`, `data_unavailable`, `service_unavailable` |

- Reserve worst-case retained bytes and a result slot before SQL execution.
  Do not evict unexpired results to make space. Capacity failure releases partial
  reservations; busy admission performs no execution. Three results/user and ten
  globally remain **test-profile proposals**, requiring quota review before
  enablement. Preview sequence reservations have their own bounded count/bytes;
  a SQL quota does not cap abandoned preview metadata. (FR11–FR12, TR5–TR6)
- Configure independent limits for API request/parser work, modeled cache,
  preparation, query memory/spill/output, spool/index, preview metadata, refresh
  staging and overall deadlines. Existing 10-second/1,000-row/1-MiB settings are
  accepted; other numerical limits require Phase 1 measurements. Fail closed
  when required runtime bounds are missing. Quantify API + refresh + analytical
  overlap and pinned old generations before enabling combined operation.
  (FR12, FR19–FR20, FR24, TR4–TR8)

## Implementation phases

1. **Contract and runtime feasibility** — freeze the selected wire/schema/encoding
   vocabulary with adapter fixtures; prove SQL reference extraction and Linux
   sandbox controls, measure preparation/query/storage/overlap workloads and
   record runtime/quotas as reviewed settings. Independent pure contract work
   proceeds while runtime gates remain open. (FR1–FR12, TR1–TR7, TR9)
2. **Durable generation and refresh coordination** — additive PostgreSQL models,
   configured/idempotent admission, latest/status reads and fenced publication
   repository verified with real transactions and failure injection. This becomes
   the shared publication implementation promised by the connector effort.
   (FR13–FR14, FR16–FR19, FR23, FR26–FR30, TR8)
3. **Supervised connector integration and recovery** — execute admitted all-grain
   work through existing verification/S3 services, quality mapping, automatic
   complete publication, queued claim and interrupted-owner reconciliation.
   Controlled artifacts establish behavior before any separately authorized
   live acceptance. (FR13–FR30, TR8)
4. **Authorized catalog and stable previews** — published-manifest resolver,
   bounded modeled cache, shared isolated execution port and cursor lifecycle
   support role-filtered schema and all-date/date-filtered browsing. (FR1–FR6,
   FR10–FR12, FR19–FR20, TR1–TR2, TR5, TR7, TR9)
5. **One-execution SQL and retained paging** — finalize parser/engine compatibility,
   canonical capped spool, admission, numbered pages and autonomous expiry/loss
   cleanup with exact ownership and current access. (FR1, FR3, FR7–FR12, FR20,
   TR1, TR3–TR7)
6. **HTTP integration and combined acceptance** — mount all contracts with existing
   browser transport, exercise real continuation/restart/publication races and
   verify selected combined budgets. Produce frontend contract fixtures and
   release evidence; deployment and frontend implementation stay separate.
   (FR1–FR30, TR1–TR9)

## Dependencies & integrations

- Existing user-access Phases 1–4 supply current-role authorization and browser
  transport; their [HTTP contract](../user-access/http-contract.md) and live/browser
  readiness gates continue to apply. Avoid changing concurrent auth work beyond
  deliberate transport/use-case integration. (FR1, TR1)
- Reuse Psycopg/process-local pools and explicit Alembic migration conventions;
  integration runs use disposable PostgreSQL, never SQLite. Coordinate ownership
  of deferred connector publication work to avoid competing schemas/state machines.
  (FR13–FR30, TR8)
- Existing Parquet/EIA/S3 implementations and verified schemas provide candidate
  and artifact ports; product cache contains only modeled approved projections.
  DuckDB and a dialect-aware parser remain new pinned/tested dependencies behind
  adapters. No dependency installation or live data access is performed by this
  planning work. (FR3, FR6–FR8, FR18–FR24, TR7–TR9)
- Production targets one EC2 replica; Linux sandbox/supervisor feasibility can be
  proved in a suitable local test environment without EC2 provisioning. Startup
  wrappers need narrow architecture-checker coverage, not generic exemptions.
  (FR11, FR25–FR30, TR5–TR7)

## Risks & tradeoffs

- **Parser/engine disagreement or sandbox escape** — defense in depth and real
  runtime denial tests gate SQL enablement. (FR8, TR7)
- **Crash/commit/lease races** — one fenced transaction model plus durable
  publication history and fault injection before releasing admission. (FR26–FR30)
- **Unmeasured resource overlap** — separate enforced pools/budgets and workload
  measurements; connector replay evidence does not size analytical execution.
  (FR19–FR20, FR24, TR5–TR6)
- **Quota friction during interactive SQL** — configurable reservations preserve
  active results, but the proposed 3/10 test limits need explicit review; do not
  quietly add early eviction or a discard endpoint. (FR9–FR12, TR6)
- **Process-local state/topology coupling** — proposed one-process ownership is
  explicit and validated; restarts yield unavailable continuations and safe orphan
  cleanup. Multi-process serving requires a separate ownership decision. (TR5–TR6)
- **Encoding size/precision surprises** — count canonical bytes, bound schema and
  recursive values, retain only whole-row prefixes and test the actual engine.
  (FR6–FR9, FR12, TR4, TR7, TR9)
- **Cross-effort drift** — reuse connector/access seams and synchronize reviewed
  API contract/ADR status during implementation; this draft does not turn earlier
  proposals or candidate receipts into runtime guarantees. (FR1, FR18, TR1, TR8)

### Alternatives considered

- Broker/separate refresh service — unnecessary for one replica and durable
  PostgreSQL claim/reconciliation; retain one release. (FR13–FR15, FR25–FR30)
- Rerun SQL for numbered pages or keep a live engine cursor — violates stable
  one-execution paging or holds scarce execution resources for 60 seconds.
  (FR7, FR9, TR3, TR5)
- Durable query metadata/shared cache service — unnecessary durability and an
  additional stack for the accepted ephemeral single-replica scope. (TR6)
- Evict unexpired SQL results when full — breaks the promised paging window
  during normal resource pressure; use explicit admission failure. (FR9–FR11, TR6)

## Test strategy

- **AC1, AC2:** application policy spies plus real PostgreSQL role changes and
  HTTP role matrices; prove denial before manifest/cache/engine/outcome lookup,
  foreign IDs and current-role changes on every continuation.
- **AC3, AC20, AC21:** integration with controlled S3 and a real published
  generation; disable EIA, publish replacements and fail refresh while old
  preview cursors and SQL result pages retain identical contents.
- **AC4, AC5:** seeded real Parquet preview tests for inclusive/one-sided bounds,
  string identifier ties, 100/500 limits, cursor tampering/revisits, fixed clock
  expiry and only date filters. Check page response byte failure without skipping.
- **AC6:** exact modeled precision/rounding fixtures through catalog, preview and
  actual SQL; no discrepancy flags or appended fields in custom projections.
- **AC7, AC8:** parser/real DuckDB compatibility corpus for joins, CTEs,
  subqueries/windows and duplicate outputs; adversarial unauthorized/external
  access, system catalogs, multi-statements, functions and hidden references.
  Real launcher tests attempt file/network/credential access and process escape;
  test doubles cannot close isolation acceptance.
- **AC9, AC10, AC32:** real execution counts, complete retained sequence versus
  all/revisited/direct pages, empty/out-of-range initial requests, fixed size/TTL,
  explicit SQL ordering/limits, exact 1,000-row boundary, UTF-8/schema overhead,
  large/nested values and oversized first/later rows. No added SQL pagination.
- **AC11, AC12:** fake-clock expiry and real spool/store-process loss, orphan
  cleanup and concurrent-reader races; no silent rerun, durable deletion or
  active-file removal. Exercise per-user/global and preview-metadata admission.
- **AC13, AC18:** HTTP envelope/status/preflight tests distinguish all required
  outcomes, active/latest/no-run selection and lookup outage; check error secrecy,
  idempotency retries, initial out-of-range recovery and Retry-After exposure.
- **AC14, AC15, AC16:** blocked-source worker harness shows prompt durable 202,
  immutable settings, all-grain claim, disconnection/session expiry independence,
  override rejection and idempotent repeat under changed configuration.
- **AC17, AC22, AC23:** reuse connector disposition/ledger fixtures with persisted
  outcomes; prove conservation counts, overlapping reasons, partial dataset
  retention and retained-all-excluded without publishing a generation.
- **AC19, AC24, AC25:** real PostgreSQL publication plus real Parquet and controlled
  S3 replay; initial interval enforcement/all-grain usability, tampered/missing
  objects, failed pages and exhausted budgets leave the active reference unchanged.
- **AC26, AC27, AC28, AC29, AC30, AC31:** independently managed API/worker processes,
  database transaction barriers and connection fault injection around commit,
  heartbeat and recovery. Cover healthy API-only restart, queued-unclaimed claim,
  claim-before-first-fetch loss, stale-owner publish, historical success after
  later publication, unknown commit and explicit-new-key retry with current dates.
- **AC33:** real launcher deadline/kill/reap tests and contention including
  previews; show health/status remain available. Measure cold/warm preparation,
  memory/spill, encoded results and concurrent refresh rather than inferring
  operational safety from static checks.
- All implemented phases run relevant Ruff, mypy, pytest and import-boundary
  checks, retaining negative fixtures and narrow startup exceptions. Run real
  adapter tests where transactions, serialization and runtime controls matter;
  record unavailable live/environment checks explicitly. This plan itself is
  checked for links and FR/TR/AC coverage, not presented as runtime evidence.

## Assumptions

- **Q1:** canonical retained document accounting, bounded separate page/index
  overhead and contiguous-prefix truncation are the design recommendation;
  actual serializer/engine tests freeze reproducible byte fixtures. (TR4)
- **Q2:** numeric preparation/overall/memory/cache/spill/overlap limits and exact
  Linux launcher require Phase 1 evidence. Independent domain/application/schema
  work may proceed; runtime activation may not. (TR5, TR7)
- **Q3:** no unexpired eviction; count in-flight reservations. Three/user and
  ten/global are proposed test-profile values, not user-approved production
  settings; preview metadata limits also need selection. (TR6)
- **Q4:** public v1 projections and encoding above are draft design choices
  grounded in implemented schemas; recursive engine values require representative
  compatibility evidence. (FR2, FR6–FR9, TR7, TR9)
- **Q5:** omitted-side unbounded filters, binary identifier ties and visited
  `page_cursor` navigation resolve the contract without adding identifier filters
  or arbitrary numbered preview jumps. (FR4–FR5, TR2)
- **Q6:** operator-owned startup configuration and a provisional 183-day maximum
  preserve the existing initial interval; this is an admission starting limit,
  not a measured capacity claim. Queued configuration snapshots contain no secrets.
  (FR14, FR23, TR8)
- **Q7:** explicit publication enum/nonterminal unknown state and typed connector
  quality mapping are recommended; database unavailability remains an HTTP error,
  not invented progress. (FR16, FR22, FR29)
- **Q8:** accepted-but-unclaimed work can start after restart; any claimed run
  that loses its owner must reconcile before manual retry. This draft makes the
  boundary observable with a committed claim before retrieval. (FR25–FR30)
- **Q9:** scoped durable idempotency, no independent key expiry and fresh-key
  retries using current configuration are recommended. No run-retention purge
  is introduced without a separate retention policy. (FR13–FR15, FR26–FR29)
- **Q10:** method split, error mappings, empty/out-of-range handling and auth
  transport extensions above are the selected draft contract. Initial out-of-range
  requests retain an owned result for GET recovery. (FR1, FR9–FR12, TR1, TR3)

## Open decisions

- **Runtime evidence gate:** choose and verify the concrete Linux launcher,
  supervision mechanism and measured budgets/deadlines before enabling real SQL
  or asserting safe combined operation. Proposed single API-process ownership
  needs a reviewed runtime record; it is not an existing accepted mandate.
  (TR5–TR7)
- **Capacity review:** accept or adjust retained-result and preview-sequence
  quotas using the interactive-use tradeoff and measurements; 3/user and 10/global
  remain proposals. Independent phases are not blocked. (TR6)
- **Compatibility gate:** pin parser/engine versions and verify all advertised
  scalar/nested encodings and reference forms. Demonstrated limitations must be
  documented before narrowing broad read-only support. (FR7–FR8, TR7)

Other Q1–Q10 items have concrete draft choices above; implementation must keep
the formal spec/HTTP contract and any required ADRs synchronized when those
choices are reviewed. No product clarification blocks this draft's independent
implementation phases, and no deployment or live publication is authorized here.
