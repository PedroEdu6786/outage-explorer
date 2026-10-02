# ADR-0033: Fix the initial national verification period

Status: **Accepted**

Date: 2026-10-01

## Context

ADR-0009 selected a recent bounded period while leaving exact dates open.
The first implementation effort covers national observations and the daily
fleet offline share. The user accepted September 1–30, 2026, inclusive, as its
fixed verification baseline.

The recorded national profile contains 30 observations, one for each date,
with no duplicate dates. Its referenced local source snapshot is present and
its checksum agrees with the profile. Reported national capacity is constant
at 97,620.5 MW throughout the sample.

## Decision

- Use the recorded national observations for September 1–30, 2026, inclusive.
- Keep the baseline fixed for reproducibility. Verification reuses the same
  source evidence without fetching current EIA data or moving the interval.
- Account for every calendar date with a usable result or a visible coverage
  gap, including exclusion reasons when applicable. Do not invent missing
  observations, copy another day's value or substitute zero for a gap.
- State the limits of the evidence. In particular, this sample does not
  demonstrate behavior across historical national capacity changes or prove
  correctness across all source history. Broader historical verification can
  follow separately.

This chooses the initial national verification evidence only. It does not
restrict the eventual product's supported dates, select the live ingestion or
refresh window, establish all-route completeness, or complete the separate
cross-grain reconciliation and anomaly requirements.

## Alternatives and consequences

A rolling latest-month baseline would change the evidence between runs and
depend on live retrieval. Full-history verification would expand the first
effort beyond its agreed scope. The recorded bounded period provides a
reproducible starting point with explicit limitations.

The recorded profile is evidence, not a completed implementation or a guarantee
that every observation will satisfy the final contract. Future verification
must account for any exclusions without concealing reduced usable coverage.

## References

- [Requirements brief](../specs/national-data-verification/requirements.md)
- [Recorded source profile](../../data/exploration/eia-profile.json)
- [ADR-0009: Recent data coverage](0009-recent-data-coverage.md)
- [ADR-0027: Required national values](0027-national-required-values-and-positive-capacity.md)
