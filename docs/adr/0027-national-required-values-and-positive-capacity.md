# ADR-0027: Require complete national observations and positive capacity

Status: **Accepted; detailed value validation remains pending**

Date: 2026-10-01

## Context

The national-data-verification requirements discussion resolved missing values
and invalid capacity before formal specification. The user accepted the
recommended exclusions and the distinction between an unavailable result and
a valid zero-outage day.

The recorded September 1–30, 2026 national profile has no missing required
attributes or zero-capacity observations. This supports the usual record
shape, but does not establish an upstream guarantee about all observations.

## Decision

- Require a usable date, capacity, outage, EIA-reported percentage and units.
  Missing or unusable required values, or incompatible units, exclude the
  national observation. In particular, a missing or unusable source percentage
  excludes the observation even if capacity and outage alone permit calculation.
- Require positive national capacity. Zero, negative, missing or otherwise
  invalid capacity excludes the observation from modeled national data and
  calculated daily results. Do not retain it as a modeled observation with an
  unavailable share.
- Zero outage with positive capacity produces a valid 0% offline share when
  the observation otherwise satisfies the required-value rules.
- Preserve excluded source evidence and report counts, reasons and coverage
  gaps. Do not substitute zero for unavailable results or guess missing units.
- Existing refresh retention rules in ADR-0026 remain applicable to the later
  refresh effort; exclusion here does not authorize deleting older valid data.

This resolves the national missing-value and denominator questions from
ADR-0006 and applies ADR-0023's required-field direction. It does not establish
the detailed parsing contract, measurement bounds beyond positive capacity,
rounding/comparison tolerance or resolution of conflicting observations.

## Alternatives and consequences

Allowing a calculated share without the source percentage would preserve more
usable calculations, but would depart from requiring the consistently present
comparison attributes. Keeping an invalid-capacity observation with an
unavailable share would preserve a modeled row but weaken the selected
usable-observation boundary. Both alternatives were discussed and not selected.

Exclusion reduces usable date coverage, which must remain visible. A source
percentage of zero remains a present value; it is not treated as missing.

## References

- [Requirements brief](../specs/national-data-verification/requirements.md)
- [Recorded source profile](../../data/exploration/eia-profile.json)
- [ADR-0006: Daily fleet offline share](0006-daily-fleet-offline-share.md)
- [ADR-0023: Invalid source records](0023-exclude-invalid-source-records.md)
- [ADR-0026: Retain existing valid data](0026-retain-valid-data-on-invalid-refresh.md)
