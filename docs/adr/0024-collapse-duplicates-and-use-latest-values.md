# ADR-0024: Collapse duplicates and use the most recent observation value

Status: **Accepted direction; source identity and recency evidence pending**

Date: 2026-10-01

## Context

The user chose one modeled row for repeated observations and the most recent
value when an already recorded observation is later received with a new value.
Historical observation dates identify the observation, not when it was revised.

## Decision

- Collapse identical repeated observations into one modeled row per verified
  natural key, across the complete dataset rather than independently per file.
- For valid observations with the same key and different values, use the most
  recent value. A newly retrieved valid observation replaces the older stored
  value when a successful refresh becomes active. Retain raw evidence and the
  previous published generation under the existing retention direction.
- Exact equality normalization, natural keys and within-extraction recency
  evidence still need source inspection. Later page position alone is not a
  verified revision ordering. If conflicting rows occur in one extraction,
  use trustworthy source revision information if available; tie/missing-recency
  behavior remains open rather than silently choosing arbitrary first/last rows.

## Alternatives and consequences

Appending every repeat would duplicate observations in analytical results.
Rejecting every changed observation would prevent legitimate corrections from
becoming active. Keeping the latest value supports refreshes that update
previously ingested dates while existing queries retain their original snapshot.
This decision does not establish that EIA actually returns conflicting rows
within one extraction, or that it exposes a revision timestamp.

Invalid new observations follow [ADR-0023](0023-exclude-invalid-source-records.md);
latest-wins does not bypass validation. Whether to retain an older valid row
when its new source record is excluded remains an open interval-replacement
detail, distinct from accepting a valid correction.

- [Backend plan](../specs/outage-explorer-backend/plan.md#duplicate-prevention-and-data-integrity)
