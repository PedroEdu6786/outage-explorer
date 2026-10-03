# Spec: Trustworthy national outage data and daily offline share
> Status: draft · Slug: national-data-verification

## Problem

Analysts and Viewers need explainable national nuclear outage figures, while
contributors need dependable data rules for subsequent connector and backend
work. Initial inspection of recorded EIA observations does not establish that
their derived daily results are correct and reproducible.

## Goal

Establish usable national daily observations and a reproducible offline-capacity
share for the fixed September 2026 baseline, with inspectable evidence and limits.

## Requirements

### Functional (EARS)

- **FR1:** THE SYSTEM SHALL document the national observation's daily grain,
  date, capacity, outage, units and usability rules, supported by recorded
  observations and source documentation.
- **FR2:** THE SYSTEM SHALL describe the metric as the daily share of
  EIA-reported nuclear capacity out of service, including full outages and
  partial output reductions.
- **FR3:** THE SYSTEM SHALL preserve original source evidence for every
  examined observation, including excluded and duplicate observations.
- **FR4:** IF an observation has a missing, empty or unusable required value,
  an uninterpretable date or number, incompatible units, or attributes outside
  its declared source contract, THEN THE SYSTEM SHALL exclude it from modeled
  observations and calculated results.
- **FR5:** IF reported capacity is not positive, THEN THE SYSTEM SHALL exclude
  the observation from modeled observations and calculated results.
- **FR6:** WHEN observations are excluded THE SYSTEM SHALL report excluded-row
  counts and the reasons for exclusion.
- **FR7:** WHEN identical usable observations repeat for a date THE SYSTEM SHALL
  retain one modeled daily observation.
- **FR8:** WHEN usable observations conflict for the same date within one
  retrieval THE SYSTEM SHALL select the last usable observation in recorded
  source order as that date's sole modeled observation.
- **FR9:** WHEN a usable daily observation is selected THE SYSTEM SHALL provide
  its offline share as that observation's reported outage divided by reported
  capacity, with the fractional value distinguished from its percentage
  equivalent of 100 times the fraction.
- **FR10:** WHEN a usable observation has zero outage THE SYSTEM SHALL produce
  a valid zero offline share.
- **FR11:** WHEN presenting a daily result THE SYSTEM SHALL show its calculated
  percentage beside the EIA-reported percentage from that same observation.
- **FR12:** THE SYSTEM SHALL present the two percentages without match/mismatch
  labels, discrepancy flags, warnings, alerts or discrepancy counts.
- **FR13:** THE SYSTEM SHALL provide traceability from each daily result to its
  recorded national inputs and any source-order selection needed to reproduce it.
- **FR14:** WHEN verifying the baseline THE SYSTEM SHALL account for each of
  September 1–30, 2026 with a usable daily result or a visible coverage gap,
  including exclusion reasons where applicable.
- **FR15:** IF a date has no usable observation THEN THE SYSTEM SHALL leave its
  result unavailable without inventing values, copying another day's value or
  substituting zero.
- **FR16:** THE SYSTEM SHALL report the examined dates, evidence and limitations:
  the sample's constant capacity does not demonstrate historical capacity
  changes; exact historical capacity-data vintage remains unverified; the metric
  does not establish reactor shutdown proportion, full-day averages, outage
  duration, lost energy or outage causes.

### Technical / Non-functional

- **TR1:** Verification must reuse the fixed recorded September 1–30, 2026
  national evidence without contacting EIA or advancing the baseline with time.
- **TR2:** Usable EIA-reported values are authoritative and must not be replaced
  with inferred values or reconstructed capacity estimates.
- **TR3:** Calculation precision must be preserved; percentage presentation
  uses two decimal places with exact halfway values rounded up.
- **TR4:** A difference between calculated and reported percentages alone must
  not invalidate an observation or fail verification; correctness depends on
  the agreed calculation from recorded inputs, not percentage agreement.

## Inputs & Outputs

- Input: recorded real EIA national daily observations for September 1–30, 2026,
  inclusive, with original source order and supporting source documentation.
- Recorded input fields are strings in the baseline; their required meanings are:

  | Field | Meaning / unit |
  | --- | --- |
  | `period` | Observation date; recorded as `YYYY-MM-DD` |
  | `capacity` | Reported national capacity in MW; positive |
  | `outage` | Reported national offline capacity in MW |
  | `percentOutage` | EIA-reported outage percentage |
  | `capacity-units` | `megawatts` |
  | `outage-units` | `megawatts` |
  | `percentOutage-units` | `percent` |

- Output: at most one usable observation per date, its preserved reported values,
  ready-made fraction and percentage, and the reported percentage shown alongside.
- Verification evidence: documented observation meaning and rules, traceable
  source inputs/order, exclusion counts/reasons, date coverage and evidence limits.

## Scope

### In scope

- National observation meaning, usability, duplicate handling and same-retrieval
  conflict selection.
- Daily offline-capacity share, percentage presentation and reproducible
  verification against the fixed recorded baseline.

### Out of scope (non-goals)

- Facility/generator modeling, cross-level reconciliation and the facility
  response's unresolved row-count discrepancy.
- Live ingestion, refresh/publication and replacement of previously stored data.
- Backend delivery, authentication, authorization implementation and deployment.
- Frontend work, charts, outage-cause explanations and new analytical measures.
- Full-history verification or selection of eventual supported dates and live
  ingestion windows.

## Assumptions

- The [agreed requirements](requirements.md) and accepted national-data decisions
  remain authoritative; this specification formalizes their focused scope.
- Recorded input shapes describe this evidence, not an upstream guarantee for
  all historical observations.

## Acceptance Criteria

- [ ] **AC1:** The documented daily grain, required values, units and usability
  rules are supported by inspectable source documentation and recorded evidence.
  (verifies FR1)
- [ ] **AC2:** The metric description explicitly includes full outages and
  partial output reductions in EIA-reported national capacity. (verifies FR2)
- [ ] **AC3:** Original evidence remains inspectable for retained, excluded,
  repeated and conflicting observations. (verifies FR3)
- [ ] **AC4:** Missing/empty required values, uninterpretable dates/numbers,
  incompatible units and unexpected attributes each cause exclusion; missing
  `percentOutage` excludes a row even when its ratio is calculable. (verifies FR4)
- [ ] **AC5:** Zero or negative capacity produces neither a modeled observation
  nor a calculated daily result. (verifies FR5)
- [ ] **AC6:** Excluded-row counts and reasons account for the excluded source
  observations without counting one row twice merely for multiple reasons.
  (verifies FR6)
- [ ] **AC7:** Repeating an identical usable observation leaves exactly one
  modeled observation for its date. (verifies FR7)
- [ ] **AC8:** Conflicting usable records select the last usable record in
  recorded source order on replay; a later invalid record cannot displace it.
  (verifies FR8)
- [ ] **AC9:** Each daily fraction independently reproduces `outage / capacity`,
  and its explicitly identified percentage reproduces 100 times that fraction.
  (verifies FR9)
- [ ] **AC10:** An otherwise usable zero-outage observation with positive
  capacity produces zero fraction and 0.00%. (verifies FR10)
- [ ] **AC11:** Each displayed daily result contains both percentages from the
  same selected stored observation. (verifies FR11)
- [ ] **AC12:** Verification output contains no percentage-agreement labels,
  discrepancy flags, warnings, alerts or discrepancy counts. (verifies FR12)
- [ ] **AC13:** A reviewer can reproduce each result and conflict selection
  from the recorded inputs and source order identified by its evidence.
  (verifies FR13)
- [ ] **AC14:** Coverage accounts for all 30 baseline calendar dates with either
  a usable result or a visible gap and applicable exclusion reasons. (verifies FR14)
- [ ] **AC15:** A missing or wholly excluded day's result remains unavailable,
  distinct from a valid zero result, without a fabricated replacement. (verifies FR15)
- [ ] **AC16:** Verification states the examined dates/evidence and every
  limitation in FR16 without claiming full-history or physical-operation proof.
  (verifies FR16)
- [ ] **AC17:** Repeated verification with EIA unavailable reproduces the same
  recorded September baseline even when the current date changes. (verifies TR1)
- [ ] **AC18:** Retained reported measurements and percentages equal their
  selected source values, with no inferred replacement. (verifies TR2)
- [ ] **AC19:** Presentation preserves unrounded calculation evidence and rounds
  percentages to two decimals, including exact halfway values such as 1.235%
  displayed as 1.24%. (verifies TR3)
- [ ] **AC20:** An otherwise usable observation with unequal calculated/reported
  percentages remains usable and does not fail verification for that difference;
  an incorrect calculation fails arithmetic verification. (verifies TR4)

## Open Clarifications

_None._
