# Facility and generator verification

Scope: extend the implemented national verification to the recorded facility
and generator datasets, as requested on 2026-10-02. Reuse the same offline
September 1–30, 2026 baseline and processing policies.

## Requirements

- **FR1:** WHEN a contributor verifies either dataset THE SYSTEM SHALL replay
  its versioned, checksum-verified snapshot offline, preserving source bytes,
  request identity, supporting metadata and source order.
- **FR2:** WHEN assessing rows THE SYSTEM SHALL require the national contract's
  seven measurement/date/unit attributes plus `facility` and `facilityName`,
  and additionally `generator` for generator rows. All are nonempty strings;
  identifiers are opaque text, never numeric coercions. Reject surrounding
  identifier whitespace rather than silently merging keys. Apply the existing
  date, numeric, exact-unit, unexpected-field and positive-capacity rules.
- **FR3:** WHEN selecting rows THE SYSTEM SHALL use `(period, facility)` or
  `(period, facility, generator)` and select the last valid source position per
  key. Names are attributes, not keys. Equivalent parsed rows collapse; other
  earlier valid rows are superseded. Invalid rows never replace valid ones.
- **FR4:** WHEN calculating THE SYSTEM SHALL preserve exact outage/capacity
  fractions and percentages and show calculated/reported percentages to two
  decimals, half-up, without percentage agreement flags or value correction.
- **FR5:** WHEN reporting THE SYSTEM SHALL account for each source row exactly
  once, separate exclusion rows from reason occurrences, and show every baseline
  date for each identifiable entity observed anywhere in the bundle, including
  invalid rows with usable identifiers. Gaps are unavailable, never zero.
  Unassignable identifiers/dates remain in the source ledger. Empty or entirely
  unidentifiable bundles retain 30 unavailable dates with an unknown roster.
- **FR6:** WHEN reporting THE SYSTEM SHALL show the response's reported total
  and actual received rows separately. Facility's recorded 2,850 versus 1,650
  remains an explicit unresolved completeness limitation. Observed-entity
  coverage does not prove a complete upstream roster or pagination.
- **FR7:** WHEN replaying identical evidence THE SYSTEM SHALL produce identical
  JSON and Markdown regardless of clock or checkout location. Wrong dataset,
  broken provenance/checksums, malformed envelopes, unsupported versions,
  out-of-period dates, arithmetic errors and report-write errors fail explicitly.
- **FR8:** THE SYSTEM SHALL preserve existing national behavior and layer/startup
  boundaries and keep evidence protected against output aliases.

## Acceptance

Verify all real rows independently using integer-scaled source decimals; test
entity separation (including repeated generator IDs across facilities), names,
invalid required fields, A/B/A, later invalid rows, zero versus gaps, unknown
identities, daily/empty coverage, integrity failures, deterministic offline CLI
replay, negative architecture fixtures and national regression behavior.

This scope adds contributor verification, not live ingestion, pagination repair,
cross-grain reconciliation, reference registries, HTTP data delivery, refresh,
authorization, persistence or deployment. Capacity vintage, historical keys,
physical operation, full-day averages, duration, energy and causes remain unproven.
