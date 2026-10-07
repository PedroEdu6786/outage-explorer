# Spec: Data browsing, SQL, and background refresh
> Status: draft · Slug: data-api

Design strategy: [implementation plan](plan.md). Its draft mechanisms and
verification gates do not change the accepted requirements below.

Phase 1 client artifacts: [OpenAPI v1](openapi.json), [synthetic fixtures](fixtures.json)
and [handoff](client-handoff.md). They freeze wire vocabulary, not endpoint
acceptance. [Runtime evidence](runtime-evidence.md) tracks the remaining gates.

## Problem

Users need to explore stored national, facility, and generator observations through
tables and their own SQL. Admins need to update that shared data without waiting
on a browser request or disrupting exploration. Frontend and backend work need
the same agreed behavior while user access is being completed.

## Goal

Deliver authorized table browsing, stable pages from one SQL execution, and an
observable background refresh of all three datasets with verified publication.

## Requirements

### Functional (EARS)

- **FR1:** WHEN any data or refresh operation is requested THE SYSTEM SHALL
  enforce the caller's current role before protected access: Viewer may browse
  and query national data; Analyst and Admin may browse and query all three
  datasets; only Admin may start refresh or inspect its status and diagnostics.
- **FR2:** WHEN an authorized user requests the catalog THE SYSTEM SHALL return
  only permitted datasets and their column names and types.
- **FR3:** WHEN an authorized user browses or queries data THE SYSTEM SHALL serve
  verified published observations, independently of upstream source availability.
- **FR4:** WHEN an authorized user browses a table THE SYSTEM SHALL return records
  within the selected inclusive date range, or all available dates when no range
  is supplied, newest observations first with deterministic ordering.
- **FR5:** WHEN an authorized user continues a table preview THE SYSTEM SHALL
  preserve its original caller, dataset, dates, ordering, page size and generation
  for the browsing sequence's fixed lifetime.
- **FR6:** WHEN national data is exposed for browsing and querying THE SYSTEM
  SHALL make calculated and reported percentages from the same stored national
  observation available as columns of that dataset, following the existing
  precision and presentation policy without discrepancy classifications.
- **FR7:** WHEN a user submits supported read-only SQL referencing permitted
  datasets THE SYSTEM SHALL execute it once against one authorized generation,
  preserving the supplied query's semantics.
- **FR8:** IF SQL writes data, changes schema or configuration, requests
  unauthorized or external data, or has unsupported or unresolved data access
  THEN THE SYSTEM SHALL reject it before execution.
- **FR9:** WHEN an authorized original caller selects a numbered SQL page THE
  SYSTEM SHALL return that page from the identified execution's retained result
  using its fixed page size, including repeat visits without re-execution.
- **FR10:** IF preview continuation or a retained SQL result is expired or lost
  THEN THE SYSTEM SHALL return an explicit unavailable outcome requiring an
  explicit new browsing sequence or SQL execution.
- **FR11:** WHEN retained query state expires or becomes orphaned THE SYSTEM
  SHALL reclaim its resources independently of further requests from the caller.
- **FR12:** WHEN a data operation returns an outcome THE SYSTEM SHALL distinguish
  empty results, total-result truncation, denied access, invalid requests, busy
  execution, unavailable data and unavailable continuation state.
- **FR13:** WHEN an Admin starts refresh THE SYSTEM SHALL acknowledge an admitted
  background run covering national, facility and generator observations without
  waiting for source retrieval and publication to finish.
- **FR14:** WHEN refresh is admitted THE SYSTEM SHALL record and expose the
  validated configured inclusive interval as that run's immutable interval,
  without accepting caller date or dataset overrides.
- **FR15:** WHILE admitted refresh work is executing THE SYSTEM SHALL continue
  independently of the initiating browser connection or session lifetime.
- **FR16:** WHEN an Admin inspects a refresh THE SYSTEM SHALL expose its progress,
  effective interval, dataset quality and retention accounting, safe failures,
  and confirmed publication outcome without presenting unavailable counts as zero.
- **FR17:** WHEN an Admin requests the active/latest refresh THE SYSTEM SHALL
  return the active run when present, otherwise the most recently admitted run,
  or explicitly indicate that no run exists.
- **FR18:** WHEN a publishable complete generation is fully verified THE SYSTEM
  SHALL activate all three datasets together automatically and report `succeeded`
  only after confirming publication.
- **FR19:** WHILE refresh is running or after a confirmed unpublished failure
  THE SYSTEM SHALL preserve the previously published generation for readers.
- **FR20:** WHEN refresh publishes a new generation THE SYSTEM SHALL keep
  existing preview and retained SQL sequences on their original generation.
- **FR21:** WHEN valid updates are merged with existing data THE SYSTEM SHALL
  preserve older valid rows for invalid replacements and absent source keys,
  including complete prior datasets for nonempty wholly excluded incoming
  datasets, under the accepted connector selection and retention policies.
- **FR22:** IF all three incoming datasets contain observations but all are
  excluded and previous valid data exists THEN THE SYSTEM SHALL report
  `retained` with exclusion reasons and no new publication.
- **FR23:** WHEN initial live loading is requested THE SYSTEM SHALL require
  usable output in all three datasets for April 2–October 1, 2026 inclusive
  before first publication.
- **FR24:** IF retrieval is empty, incomplete or failed, or resource/integrity
  checks fail THEN THE SYSTEM SHALL fail the refresh without publishing a
  partial generation or treating the failure as ordinary row exclusion.
- **FR25:** WHEN the API restarts while a refresh worker remains healthy THE
  SYSTEM SHALL allow that admitted work to continue.
- **FR26:** WHEN a running refresh worker is lost THE SYSTEM SHALL automatically
  reconcile its publication outcome before assigning a terminal result or
  permitting a replacement run.
- **FR27:** WHEN recovery confirms that a lost worker's run published THE SYSTEM
  SHALL recover `succeeded` without repeating source ingestion.
- **FR28:** WHEN recovery confirms that interrupted work did not publish THE
  SYSTEM SHALL mark it `interrupted` and require explicit Admin retry before
  another source run for that work.
- **FR29:** WHILE publication remains uncertain THE SYSTEM SHALL report an
  unresolved or unavailable outcome without asserting success or rollback.
- **FR30:** WHEN refresh ownership is recovered THE SYSTEM SHALL prevent the
  former owner from subsequently publishing.

### Technical / Non-functional

- **TR1:** Apply the existing [user-access specification](../user-access/spec.md)
  to direct requests and every continuation, including current access checks
  and original-caller ownership of SQL results. Possession of an ID or cursor
  grants no access. Diagnostic responses must not disclose protected data,
  credentials, storage locations or raw provider failures.
- **TR2:** Preview pages default to 100 rows with an initial configurable maximum
  of 500; opaque cursors expire 60 seconds after first-page creation without
  renewal, under [ADR-0015](../../adr/0015-dataset-preview-pagination.md).
- **TR3:** SQL `page` is a positive integer starting at 1; `page_size` defaults to
  100 with an initial maximum of 500 and remains fixed per execution. Reject
  invalid values and size mismatches. The retained result expires 60 seconds
  after completion without renewal; process/store loss may make it unavailable
  earlier. Preserve one execution's row order and multiplicity, including explicit
  SQL limits; pagination must not inject ordering, limits or offsets.
- **TR4:** The SQL output cap is 1,000 rows or 1 MiB (1,048,576 bytes) for the
  **whole retained result**, whichever is reached first, with explicit truncation.
  Page size never increases that allowance; byte limits must not skip rows or
  silently alter numbered page boundaries. [NEEDS CLARIFICATION: Q1 — finalize
  serialized byte accounting, schema/envelope overhead and oversized-row behavior.]
- **TR5:** Admit one analytical execution at a time initially and return a
  retryable busy outcome for contention. Enforce a 10-second execution deadline
  and isolate failures from unrelated operations, under
  [ADR-0013](../../adr/0013-initial-query-controls.md). Bound preparation, memory,
  temporary storage and total request time separately. [NEEDS CLARIFICATION: Q2
  — establish measured preparation/overall deadlines, memory and storage budgets,
  and safe combined query/refresh capacity.]
- **TR6:** Keep query continuation state ephemeral, bounded and independently
  expiring under [ADR-0022](../../adr/0022-ephemeral-query-pagination-state.md).
  Enforce per-user/global admission and storage limits without claiming an
  unconditional lifetime through state loss. [NEEDS CLARIFICATION: Q3 — accept
  or adjust the proposed three retained results per user and ten globally,
  including capacity-response and unexpired-result eviction policy.]
- **TR7:** Preserve broad read-only analytical support, including projections,
  filters, aggregates, joins, CTEs, subqueries and windows. User SQL has no access
  to operational identities/sessions, credentials, arbitrary files or network
  sources. Existing isolation and compatibility verification remain prerequisites
  for claiming these guarantees; narrowing support requires demonstrated reasons.
- **TR8:** Apply the [connector specification](../data-connector/spec.md),
  [initial-load/retention policy](../../adr/0037-connector-initial-load-and-retention.md),
  [configured-start/current-end policy](../../adr/0063-configured-start-current-end-refresh.md), and
  [interruption policy](../../adr/0052-interrupted-refresh-recovery.md).
  A durable candidate receipt alone does not establish active publication.
- **TR9:** National percentages retain calculation precision and use two-decimal,
  halfway-up presentation from the same national observation; do not replace
  national values with detail sums or introduce match/mismatch flags, under
  [ADR-0031](../../adr/0031-show-national-percentages-without-discrepancy-flags.md).

## Inputs & Outputs

- **Catalog:** current user → permitted dataset identities, columns and types.
  Coverage, where shown, describes stored observations rather than upstream
  completeness. Proposed public relation names are `national`, `facilities`
  and `generators`. [NEEDS CLARIFICATION: Q4 — freeze public names, column
  projection and lossless scalar/nested value representation, including duplicate
  SQL labels and temporal/non-finite/binary values.]
- **Preview:** permitted dataset, optional date range and page size; subsequent
  requests identify the same browsing sequence → columns, rows, original
  generation and continuation/expiry information. No identifier filters initially.
  [NEEDS CLARIFICATION: Q5 — finalize one-sided date bounds, equal-date ordering
  and previous-page navigation on the same generation; retaining visited cursors
  is the current proposal.]
- **SQL:** submitted `sql`, `page`, `page_size`; continuation identifies
  `query_id` and `page` → columns, rows, query/generation identity, effective page
  and size, remaining-page indication, truncation and expiry. User-selected
  interface constraint: page selection stays on `/api/query` as a query parameter,
  without a separate page endpoint. The method split and response envelopes in
  [http-contract.md](http-contract.md) remain proposals.
- **Refresh admission:** Admin action with no date or dataset selection → run
  identity, accepted state, effective configured interval and a way to retrieve
  progress. [NEEDS CLARIFICATION: Q6 — define configured-range ownership, validated
  maximum interval and change mechanism while preserving immutable admitted dates.]
- **Refresh status:** run identity, or active/latest lookup → run progress,
  dataset quality/retention, failure and publication outcome. `succeeded`,
  `retained` and `interrupted` have the accepted meanings in FR18, FR22 and FR28.
  [NEEDS CLARIFICATION: Q7 — finalize progress/quality fields and unknown-publication
  representation; proposed nonterminal `publication_unknown` and publication
  states `pending`, `published`, `not_published`, `unknown` are not yet accepted.]
- **Refresh retry/recovery:** automatic reconciliation precedes explicit Admin
  retry of interrupted unpublished work. [NEEDS CLARIFICATION: Q8 — decide recovery
  of accepted but unstarted work; automatically running its recorded request
  after restart is proposed, not an accepted source retry policy.]
  [NEEDS CLARIFICATION: Q9 — finalize admission idempotency, key/run retention and
  explicit retry identity/interval semantics; a fresh key/run using current
  configuration is proposed.]
- **Errors:** distinguish FR12 outcomes without protected details.
  [NEEDS CLARIFICATION: Q10 — finalize error/status mappings, empty/out-of-range
  page behavior, retry hints and browser-auth transport extensions.]
- The [requirements brief](requirements.md) supplies product grounding. The
  [endpoint contract](http-contract.md) and [design notes](design-notes.md) carry
  all proposed routes, response examples, encodings and resource recommendations
  into planning; linking them does not accept their unresolved choices.

## Scope

### In scope

- Authorized catalog and date-only previews, the national metric within national
  data, user-submitted SQL and retained numbered result pages.
- All-dataset background refresh, configured admission range, status/quality,
  active/latest rediscovery, complete publication and interruption reconciliation.
- Integration with existing user access, verified modeled data and connector
  policies; verification of the guarantees and bounds above before release.

### Out of scope (non-goals)

- Registration, user-management/seeding endpoints, per-user data copies or new
  permission models; facility/generator identifier filters in initial previews.
- SQL writes, operational-table queries, arbitrary external data sources,
  durable query history or reuse of results between executions.
- Separate per-dataset refresh, publication approval, scheduling, cancellation,
  automatic rerun of interrupted source work or a full refresh-history browser.
- Frontend implementation, infrastructure provisioning, deployment or live
  publication during specification work; automatic authoritative-data deletion.

## Assumptions

- This effort refines the existing backend scope: date-only initial previews,
  national metric placement, SQL paging defaults/lifetime and configured refresh
  supersede older open proposals on those points. Other accepted policies persist.
- Accepted product behavior can be planned while identified contract and resource
  questions remain explicit; unmeasured limits and proposed wire formats are not
  production guarantees.

## Acceptance Criteria

- [ ] **AC1:** Direct and continuation requests enforce Viewer national-only,
  Analyst/Admin all-dataset and Admin-only refresh access before protected work;
  revoked access and foreign query IDs cannot bypass it. (verifies FR1, TR1)
- [ ] **AC2:** Each role's catalog contains exactly its permitted datasets and
  their public column/type metadata. (verifies FR2)
- [ ] **AC3:** With upstream retrieval unavailable, published observations remain
  browsable/queryable; unpublished candidates are never served. (verifies FR3)
- [ ] **AC4:** Date bounds are inclusive; omitted dates show all coverage newest
  first with stable ordering. Initial preview supports only date filters.
  (verifies FR4)
- [ ] **AC5:** Preview defaults to 100 rows, supports the initial maximum 500,
  remains bound to its original sequence and expires exactly 60 seconds after
  first-page creation without extension by access. (verifies FR5, TR2)
- [ ] **AC6:** National preview exposes both percentage columns, and SQL may select
  them from the national relation with agreed precision/presentation and no
  discrepancy labels; SQL selecting other columns does not gain extra fields.
  (verifies FR6, TR9)
- [ ] **AC7:** Permitted joins, aggregates, CTEs, subqueries and windows match
  known inputs; execution preserves user SQL semantics. (verifies FR7, TR7)
- [ ] **AC8:** Writes, administrative changes and unauthorized, external or
  unresolved data references are denied before execution. (verifies FR8, TR7)
- [ ] **AC9:** First, middle, last, directly selected and revisited SQL pages
  reconstruct one execution's sequence, including duplicate rows and explicit
  ordering/limits; no continuation triggers another execution. (verifies FR9, TR3)
- [ ] **AC10:** SQL pages default to 100 and accept up to 500 rows; invalid
  page/size values and changed execution page sizes are rejected. The result's
  fixed expiry is 60 seconds after completion. (verifies FR9, TR3)
- [ ] **AC11:** Expired/lost previews and SQL IDs return explicit unavailability,
  never substituted page-1 data or a silent rerun. (verifies FR10)
- [ ] **AC12:** Abandoned expired results and orphaned state are reclaimed without
  another caller request, preserving active results and durable data.
  (verifies FR11, TR6)
- [ ] **AC13:** The frontend can distinguish empty, truncated, denied, invalid,
  busy, data-unavailable and continuation-unavailable outcomes. (verifies FR12)
- [ ] **AC14:** An Admin receives a run acknowledgement before source work finishes;
  the admitted run covers all three datasets. (verifies FR13)
- [ ] **AC15:** Admission/status show the configured interval; changing configuration
  after admission cannot change it, and request overrides cannot alter it.
  (verifies FR14)
- [ ] **AC16:** Closing the initiating browser or expiring its session does not
  cancel admitted work; inspecting it still requires current Admin access.
  (verifies FR15, FR1)
- [ ] **AC17:** Progress/outcomes accurately distinguish selected, excluded,
  duplicate/superseded and retained records, safe failures and publication;
  overlapping exclusion reasons do not inflate excluded counts.
  (verifies FR16, TR8)
- [ ] **AC18:** An Admin without the original ID can rediscover the active run,
  otherwise the latest admitted run, and distinguish no runs from lookup failure.
  (verifies FR17, FR12)
- [ ] **AC19:** A fully verified publishable generation activates all datasets
  together without another Admin action; confirmed publication yields `succeeded`.
  (verifies FR18)
- [ ] **AC20:** Existing published data remains available during refresh and after
  a confirmed unpublished failure. (verifies FR19)
- [ ] **AC21:** A new publication does not change existing preview pages or
  retained SQL page contents. (verifies FR20)
- [ ] **AC22:** Invalid replacements, absent prior keys and some wholly excluded
  nonempty datasets retain valid prior data while other valid changes may publish.
  (verifies FR21)
- [ ] **AC23:** All-three-excluded nonempty input with prior data reports `retained`,
  explicit exclusions and no new generation. (verifies FR22)
- [ ] **AC24:** First publication uses April 2–October 1, 2026 inclusive and cannot
  succeed without usable data in each of the three datasets. (verifies FR23)
- [ ] **AC25:** Empty/failed/missing retrieval, resource exhaustion and corrupt or
  incomplete artifacts prevent publication of a partial generation.
  (verifies FR24, TR8)
- [ ] **AC26:** Restarting only the API leaves a healthy admitted worker running.
  (verifies FR25)
- [ ] **AC27:** Lost-worker recovery establishes publication outcome before
  declaring terminal state or permitting replacement work. (verifies FR26)
- [ ] **AC28:** Confirmed committed work recovers `succeeded` without source
  reretrieval, including when a later generation is now active. (verifies FR27)
- [ ] **AC29:** Confirmed unpublished interrupted work reports `interrupted` and
  does not rerun source work until an Admin explicitly retries. (verifies FR28)
- [ ] **AC30:** An unconfirmed commit produces an unresolved/unavailable outcome,
  never a fabricated success or rollback. (verifies FR29)
- [ ] **AC31:** A former owner cannot publish after ownership recovery.
  (verifies FR30)
- [ ] **AC32:** Total SQL output respects both 1,000 rows and 1 MiB across all pages
  with explicit truncation, without skipped retained rows or shifted boundaries.
  (verifies TR4)
- [ ] **AC33:** Competing execution receives a retryable busy response; execution
  exceeding ten seconds terminates without disabling unrelated operations.
  (verifies TR5)

## Open Clarifications

- **Q1:** Serialized byte accounting, schema/envelope overhead and oversized-row behavior.
- **Q2:** Measured preparation/overall deadlines, memory/storage budgets and combined query/refresh capacity.
- **Q3:** Retained-result quotas, capacity outcomes and unexpired-result eviction policy; three per user/ten global remain proposals.
- **Q4:** Public names, column projection and lossless scalar/nested representation, including duplicate labels and temporal/non-finite/binary values.
- **Q5:** One-sided date bounds, equal-date ordering and previous-page preview navigation.
- **Q6:** Configured-range ownership, maximum interval and change mechanism.
- **Q7:** Progress/quality fields and unknown-publication representation; exact proposed enum values remain open.
- **Q8:** Recovery of accepted but unstarted work after restart.
- **Q9:** Refresh idempotency, key/run retention and explicit retry identity/interval semantics.
- **Q10:** Error/status mappings, empty/out-of-range pages, retry hints and browser-auth transport extensions.
