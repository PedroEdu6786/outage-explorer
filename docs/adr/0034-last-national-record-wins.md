# ADR-0034: Keep the last valid national record for a same-day conflict

Status: **Accepted**

Date: 2026-10-01

## Context

ADR-0024 left the resolution of conflicting observations within one extraction
open. The national verification discussion established EIA as the authoritative
source and rejected automatically excluding an entire conflicting day.

The user expects one national observation per date, but selected a fallback if
different records for the same day occur: "choose 1, last record wins".
No such conflict was observed in the recorded 30-day national baseline.

## Decision

- Collapse identical repeated national observations to one modeled row per date.
- If otherwise valid national observations for the same date conflict within
  one retrieval, select the last record in recorded EIA source order.
- Retain the original source evidence and enough ordering information to
  reproduce the choice. Replay of the same recorded evidence selects the same
  record; processing completion order does not redefine source order.
- Do not exclude the date solely because its valid observations conflict.
- Apply the existing required-value rules before choosing among usable records.
  A later invalid record does not displace a usable earlier record. All-invalid
  cases remain exclusions under the existing policies.

This resolves ADR-0024's within-extraction ambiguity for national observations.
It chooses a deterministic fallback rather than claiming that source position
proves revision recency. Across refreshes, newly retrieved valid values still
replace older stored values and invalid replacements retain previous valid
data under ADR-0024/0026. Other source grains remain outside this focused effort.

## Alternatives and consequences

Excluding the whole day would discard usable source data. Keeping both rows
would violate the selected daily grain. The user selected one source record
using last-record-wins, without requiring evidence of a revision timestamp.

The result is reproducible for the same recorded source order. A future
retrieval may change the order or values; this policy does not promise the
same winner across independent retrievals. Percentage agreement labels and
discrepancy flags remain excluded under ADR-0031.

## References

- [Requirements brief](../specs/national-data-verification/requirements.md)
- [ADR-0024: Duplicates and revisions](0024-collapse-duplicates-and-use-latest-values.md)
- [ADR-0027: Required national values](0027-national-required-values-and-positive-capacity.md)
- [ADR-0031: Percentage presentation](0031-show-national-percentages-without-discrepancy-flags.md)
