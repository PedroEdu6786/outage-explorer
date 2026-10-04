# Spec: EIA data connector
> Status: draft · Slug: data-connector

## Problem
Recorded September 2026 observations now have reproducible national, facility,
and generator validation contracts. The product still lacks live retrieval,
durable analytical output, and a refresh lifecycle that preserves usable data
through failures and source revisions.

## Goal
Retrieve a selected recent period across all three outage routes, preserve its
evidence, and automatically publish verified modeled data through an authorized,
bounded refresh with an explainable outcome.

## Requirements
### Functional (EARS)
- **FR1:** WHEN a caller requests refresh or its outcome THE SYSTEM SHALL enforce application-owned Admin permission before admitting work or disclosing the outcome.
- **FR2:** WHEN an authorized refresh is admitted THE SYSTEM SHALL perform it independently of the initiating request's lifetime and expose its running and terminal outcome.
- **FR3:** WHILE a refresh owns publication rights THE SYSTEM SHALL prevent another refresh from publishing concurrently or replacing its data through stale ownership.
- **FR4:** WHEN retrieving a selected inclusive daily interval THE SYSTEM SHALL retrieve each of the national, facility, and generator routes through all pages required by the validated retrieval contract.
- **FR5:** IF retrieval fails, cannot progress, exceeds its configured bounds, or returns an unusable response envelope THEN THE SYSTEM SHALL leave the active generation unchanged and report the run failure separately from row exclusions.
- **FR6:** WHEN a source response is received THE SYSTEM SHALL preserve its sanitized raw observations, request identity, retrieval identity and time, dataset identity, declared interval, and recorded page/row order as replayable evidence.
- **FR7:** WHEN modeling received observations THE SYSTEM SHALL exclude rows that violate their declared versioned contract while retaining their raw evidence and field-specific reasons.
- **FR8:** WHEN valid observations repeat a natural key within a retrieval THE SYSTEM SHALL select one observation according to the declared reproducible ordering contract, collapse observations equal to the winner, and account for differing superseded observations.
- **FR9:** WHEN a successful refresh contains a valid observation for a previously stored key THE SYSTEM SHALL replace the older value with the newly retrieved valid value.
- **FR10:** WHEN an excluded incoming observation has a trustworthy key matching an older valid observation and no usable incoming replacement, or an older in-window key is absent from a successfully retrieved interval, THE SYSTEM SHALL retain the older valid observation with its original provenance, report invalid and absent retention separately, and allow other valid updates to publish.
- **FR11:** WHEN every incoming observation across all three datasets is excluded THE SYSTEM SHALL keep the active generation unchanged and report retention without publication; WHEN only some datasets have nonempty entirely excluded input THE SYSTEM SHALL retain their complete previous valid data and allow valid updates from the others to publish.
- **FR12:** WHEN producing a modeled generation THE SYSTEM SHALL enforce one row per natural key across the complete logical dataset, including retained rows and all output files.
- **FR13:** WHEN producing analytical output THE SYSTEM SHALL preserve the three source grains independently and calculate the national offline share from the selected national observation's reported capacity and outage.
- **FR14:** WHEN reporting retrieval and quality THE SYSTEM SHALL distinguish requested coverage, received rows, source-advertised totals, usable coverage, and unresolved source-completeness limitations.
- **FR15:** WHEN the known facility discrepancy of 2,850 advertised versus 1,650 received rows is encountered THE SYSTEM SHALL preserve it as a nonblocking documented limitation without fabricating rows or asserting upstream completeness from the observed roster.
- **FR16:** WHEN reporting refresh quality THE SYSTEM SHALL identify each dataset's received, excluded, duplicate, superseded, retained-old and resulting modeled counts, with excluded rows counted once and exclusion-reason occurrences counted separately.
- **FR17:** WHEN all required candidate data and evidence pass retrieval, modeling and storage-integrity checks THE SYSTEM SHALL automatically make that verified generation active and report the publication outcome without another Admin action.
- **FR18:** IF a refresh fails or publication cannot be confirmed THEN THE SYSTEM SHALL preserve the last confirmed generation and avoid reporting unconfirmed publication as success.
- **FR19:** WHEN publication occurs THE SYSTEM SHALL expose the complete new generation to new readers while existing readers retain their selected generation.
- **FR20:** WHEN the application restarts after successful ingestion THE SYSTEM SHALL retain access to published data and refresh outcomes without requiring another EIA extraction.

### Technical / Non-functional
- **TR1:** Use EIA daily `us-nuclear-outages`, `facility-nuclear-outages`, and `generator-nuclear-outages`; raw and modeled output are separate durable Parquet datasets under [ADR-0001](../../adr/0001-s3-parquet-duckdb.md) and [ADR-0002](../../adr/0002-analytical-dataset-contracts.md). Apply the accepted storage and dependency boundaries in [the structure guide](../../context/code-structure.md) and [ADR-0032](../../adr/0032-postgresql-on-rds.md); this specification selects no additional infrastructure.
- **TR2:** Reuse the established [national contract](../national-data-verification/contract.md) and [detail contracts](../facility-generator-verification/contract.md): required string fields, exact units, real dates, finite decimal values, positive capacity, opaque identifiers, and no implicit coercion or additional physical bounds. These are bounded application contracts, not historical upstream guarantees.
- **TR3:** Preserve source numeric strings and calculation precision alongside typed decimal analytical columns. Unsupported physical representations cause an explicit candidate/publication failure rather than silent rounding, truncation or source-row exclusion; verify concrete widths/scales during adapter implementation (ADR-0037). Present calculated and reported percentages from the same selected observation to two decimals with half-up rounding, without agreement flags or exclusion solely for a percentage difference (ADR-0031/0036).
- **TR4:** Retain evidence and contract/transformation identities sufficient to reproduce row selection, exclusions, retained-row provenance and derived values. Never retain credentials in source URLs, echoed requests, raw artifacts, logs or outcomes. Sanitized evidence must not be described as original wire bytes.
- **TR5:** Bound source requests, retries, elapsed retrieval time, memory, staging space and output size. [NEEDS CLARIFICATION: Q1 — establish measured connector resource limits and supported maximum interval before enabling production refresh.]
- **TR6:** Use 2026-04-02 through 2026-10-01 inclusive for the initial live load and explicit bounded intervals for subsequent refreshes, supporting at least 30 days for reconciliation. Retain prior keys absent from a successfully retrieved interval with original provenance and a distinct retention reason; publish other valid updates. No automatic rolling anchor or source-deletion policy is selected. September remains offline evidence. Q2 is resolved by [ADR-0037](../../adr/0037-connector-initial-load-and-retention.md); measured support for the initial interval remains an engineering gate.
- **TR7:** Publication requires verified data/artifact integrity across all three routes; a known failed or missing page remains a run failure. The facility total inconsistency alone remains nonblocking, not proof that retrieval is complete. Its [investigation resumed on October 3](../../challenge/001-facility-row-count.md) without changing that treatment. [NEEDS CLARIFICATION: Q3 — validate live pagination, termination and stable page/row ordering for all routes, independently of the facility total investigation.]
- **TR8:** The last-valid-record-in-recorded-order fallback is accepted for bounded national/detail verification (ADR-0034/0036); it does not prove live revision recency. [NEEDS CLARIFICATION: Q4 — establish live source ordering and contract applicability beyond the September baseline, including any trustworthy revision evidence, before claiming those guarantees.]
- **TR9:** Without a previous generation, fetch the initial interval live through the same validation and publication pipeline as refresh; all three datasets must produce usable output before initial publication. With previous data, retain complete prior datasets for nonempty entirely excluded routes and publish other valid updates; all-three-excluded input retains the active generation without publication. Empty/failed retrieval remains failure. Q5 is resolved by ADR-0037, superseding only ADR-0026's prior-seed assumption.
- **TR10:** Keep published snapshots and findings inputs available; automated authoritative-data deletion, historical browsing and recovery-policy design remain deferred (ADR-0010). Missing source keys and excluded replacement rows are different cases.

## Inputs & Outputs
- Contributor configuration follows [ADR-0041](../../adr/0041-connector-defaults-and-json-configuration.md): typed resource defaults with optional partial `--config PATH` JSON overrides; explicit date/staging/prior flags win over file values. Effective dates/staging and the environment-only `EIA_API_KEY` remain required. Budget environment overrides are removed. Invalid or unknown configuration fails before storage/transport construction; defaults do not establish measured live limits.
- Inputs: an authorized refresh request; selected inclusive dates; current published observations and provenance; EIA metadata and daily response pages; configured resource bounds; versioned grain contracts.
- National natural key: `period`. Required source attributes: `period`, `capacity`, `outage`, `percentOutage`, `capacity-units`, `outage-units`, `percentOutage-units`.
- Facility natural key: `(period, facility)`; national attributes plus `facility` and `facilityName`. Generator natural key: `(period, facility, generator)`; facility attributes plus `generator`. Identifiers remain exact nonempty strings; names are attributes, not identity.
- Output: separately retained raw and validated modeled Parquet; generation identity and reproducibility evidence; refresh state and Admin quality outcome; national derived share and source percentage. Physical output schemas and transport shapes belong to the plan.
- Existing evidence: September 1–30, 2026 contains 30 national observations, 1,650 facility observations across 55 observed facilities, and 2,850 generator observations across 95 observed pairs. The [detail findings](../facility-generator-verification/verification.md) document the facility-total difference; the [resumed investigation](../../challenge/001-facility-row-count.md) adds bounded live controls. Observed coverage cannot establish entities missing from the whole sample.

## Scope
### In scope
- Live connector and modeled-output requirements for all three routes, reusable validation/selection, evidence preservation, retained-valid-row behavior, refresh authorization/coordination/outcomes, and verified publication.
- Implementable now: recorded/synthetic retrieval cases, contract-preserving transformation and artifact round trips, replayable provenance, quality accounting, refresh use-case behavior and publication failure scenarios.
- Required evidence before the corresponding live behavior is claimed: pagination/ordering, resource budgets, supported intervals, broader contract applicability and concrete adapter/runtime verification. Initial-load and absent/partial-exclusion product policies are accepted in ADR-0037. Engineering gates do not prevent work on independent components.
- The facility advertised-total investigation resumed at the user's October 3 request; resolving its upstream cause is not a prerequisite for this specification, planning or connector implementation.

### Out of scope (non-goals)
- Production code in this planning effort, deployment, cloud provisioning and publication of data during specification work.
- Full-history extraction, scheduled refresh, invented operating rosters, source-deletion semantics inferred from missing rows, and revision-recency claims based only on response order.
- New authentication design, general catalog/preview/SQL implementation, analytical sandbox implementation, frontend and Admin approval workflows.
- Cross-grain reconciliation findings and outage event/cause inference; this connector preserves their inputs without manufacturing anomalies or replacing national totals with detail sums.
- Snapshot-retention durations, automated generation deletion, disaster-recovery design, new services or a message broker.

## Assumptions
- The three completed offline verifiers are evidence for the bounded contracts and selection/arithmetic behavior, not proof of live ingestion, pagination, runtime authorization or publication correctness.
- Existing accepted Admin refresh, validity, duplicate/revision and retention policies remain unchanged. This specification adds no automatic latest-date selection or deletion policy.
- User direction to ignore the row inconsistency applies to the documented facility total discrepancy; it does not authorize accepting failed page requests, corrupt output or silent data loss.

## Acceptance Criteria
- [ ] **AC1:** Direct use-case requests from Viewer, Analyst and an unassigned identity cannot admit refresh or read its outcome; denied requests perform no retrieval. An authorized Admin can request both. (FR1)
- [ ] **AC2:** Disconnecting the initiating client does not cancel admitted work; running and terminal outcomes remain observable. Competing or stale refresh owners cannot publish over the current owner. (FR2, FR3)
- [ ] **AC3:** A bounded multipage fixture for each route retrieves the selected interval without dropping page-boundary observations; live verification separately records the established pagination/termination contract. (FR4; TR7)
- [ ] **AC4:** Failed pages, repeated nonprogressing pages, invalid envelopes and exhaustion of each configured retrieval bound yield a run failure and preserve the active generation. The report does not count these as ordinary excluded rows. (FR5; TR5)
- [ ] **AC5:** Raw-artifact replay reproduces row positions, selection, validation and derived values across page boundaries; source strings and request/retrieval identities survive. Credential-bearing echoed requests are sanitized and no output artifact or outcome exposes their secrets. (FR6; TR4)
- [ ] **AC6:** Invalid required fields, units, identifiers, dates, numbers and unexpected attributes produce the established exclusions while valid zero-outage observations remain usable. (FR7; TR2)
- [ ] **AC7:** Identical repeats and A/B/A conflicts across pages select one reproducible winner under the declared order; processing completion order does not change it and a later invalid record cannot displace it. The result makes no revision-recency claim. (FR8; TR8)
- [ ] **AC8:** A newly retrieved valid value replaces an older stored value for the same key; repeating that refresh does not create duplicate modeled keys. (FR9, FR12)
- [ ] **AC9:** A mixed refresh retains identifiable older valid rows where no usable incoming replacement exists and separately retains prior keys absent from successfully retrieved input; both preserve original provenance and allow other valid updates. Invalid unknown keys are not matched by guesswork; retained-invalid and retained-absent counts are distinct. (FR10)
- [ ] **AC10:** With previous valid data and every incoming row excluded across all three routes, the active generation remains unchanged and the outcome explicitly reports no publication and exclusion reasons. If only some nonempty routes are entirely excluded, their complete previous data survives while valid updates from other routes publish. Without previous data, the live initial interval uses the same pipeline and publishes only when each dataset has usable output; a missing usable dataset, empty route or failed retrieval prevents publication. (FR11; TR6, TR9)
- [ ] **AC11:** A candidate containing duplicate natural keys across output files or retained/new rows cannot publish until modeled uniqueness holds. (FR12, FR17)
- [ ] **AC12:** All three grains retain their source observations independently; the national share uses the selected national capacity/outage and never facility sums. Exact inputs survive storage, zero is distinct from unavailable data, and percentages follow the existing presentation rule without comparison flags. (FR13; TR3)
- [ ] **AC13:** Coverage reports distinguish observed entities and usable dates from upstream completeness, retain missing/excluded gaps without zero filling, and expose source totals and received counts. (FR14)
- [ ] **AC14:** The recorded facility 2,850/1,650 discrepancy remains visible and does not alone block the connector or a candidate otherwise satisfying publication checks; known failed pages still prevent publication and no missing observations are invented. (FR15; TR7)
- [ ] **AC15:** Quality counts reconcile received rows into selected, excluded, duplicate and superseded dispositions; retained-invalid, retained-absent and carried-outside-interval counts are mutually exclusive and distinct from newly selected rows. Their sum with selected rows equals the final modeled total when publication is eligible; multiple reasons do not inflate excluded-row counts. (FR16)
- [ ] **AC16:** A complete verified generation becomes active automatically; new readers see all three datasets from that generation, while an existing reader still sees its prior generation. (FR17, FR19)
- [ ] **AC17:** Corrupt/unreadable or incomplete artifacts, partial uploads, interruption and an uncertain publication outcome never expose a partial generation or report unconfirmed success. (FR18)
- [ ] **AC18:** Published data and refresh outcomes remain recoverable after application replacement with EIA unavailable; published snapshots and pinned findings inputs are not automatically deleted. (FR20; TR10)

## Open Clarifications
- **Q1:** Establish measured connector resource limits and supported maximum interval before enabling production refresh.
- **Q3:** Validate live pagination, termination and stable page/row ordering for all routes. The [facility investigation](../../challenge/001-facility-row-count.md) supplies bounded evidence, not a general pagination contract.
- **Q4:** Establish live source ordering and contract applicability beyond the September baseline, including any trustworthy revision evidence, before claiming those guarantees.

## Resolved product decisions

- **Q2:** Initial interval is 2026-04-02 through 2026-10-01 inclusive, with explicit dates and no automatic rolling policy. Retain absent prior keys and publish other valid changes (ADR-0037).
- **Q5:** Initial live loading uses the refresh pipeline and requires usable output from all three datasets. Partial entirely-excluded routes retain complete prior data while other valid changes publish; all-three-excluded input preserves the active generation (ADR-0037).
