# Requirements: Trustworthy national outage data and daily offline share
> Status: agreed · Slug: national-data-verification

## Problem statement

We have recorded EIA national outage observations, but their initial inspection
does not yet establish consistent rules for which observations are usable or
enough verification to trust and explain the results derived from them.

This first effort serves two agreed goals: confidence that national outage
figures are correct and explainable, and a dependable foundation for the
connector and backend work that follows. Establishing the meaning and quality
of the data now keeps those later efforts grounded in the same expectations.

## Target user / context

Analysts need the daily share of reported U.S. nuclear fleet capacity that is
offline, ready to use and supported by evidence. This national measure is also
available to Viewers under the existing product scope. Contributors building
the connector and backend need an agreed interpretation of the observations
and their quality limitations.

This effort works from recorded real EIA national observations. It establishes
the verified data and measure; delivering them through the running backend is
a later effort.

The fixed verification baseline is September 1–30, 2026, inclusive, using the
recorded national observations. It does not advance automatically with today's
date. This selects evidence for the first effort, not the eventual product's
supported date range or the live ingestion/refresh window.

## Success criteria

Someone reviewing a national daily result can understand what it means,
reproduce it from the recorded source observations, and see the limitations
that affect its use. Contributors can build on the same documented data
meaning and quality rules without independently guessing what is valid.

## Acceptance criteria

- National daily observations have a documented meaning, including the date,
  reported capacity, offline capacity, units and what makes an observation
  usable, supported by source documentation and recorded evidence.
- EIA is the authoritative source for reported observations. Preserve its
  usable reported values; do not replace them with values inferred from our
  calculation. Required-value validation still applies.
- The daily offline share is ready-made from the same day's reported national
  offline capacity divided by reported national capacity. Its percentage is
  distinguishable from its fractional value and from the proportion of reactors
  shut down.
- Describe the measure as the daily share of EIA-reported nuclear capacity out
  of service, including full outages and partial output reductions. Use the
  reported national values in MW. It describes daily reported status, not how
  many hours a reduction lasted, energy lost throughout the day, or its cause.
  [ADR-0035](../../adr/0035-national-outage-capacity-meaning.md) records this
  meaning and its [supporting evidence](../../../data/exploration/eia-capacity-semantics.json).
- Explain the evidence boundary: EIA documents generator-capacity and reactor
  status inputs, but the exact capacity-data vintage for every historical API
  row is unverified. Preserve EIA's reported capacity rather than reconstructing
  or replacing it with another capacity estimate.
- Each calculated result is traceable to its recorded national inputs and can
  be independently reproduced without contacting EIA.
- Show the calculated percentage and EIA's reported percentage together for
  each daily observation, using the values from that same stored observation.
  No live EIA lookup is needed to produce these results.
- Preserve calculation precision; when presenting percentages at two decimal
  places, round exact halfway values up. Preserve the original reported value
  as source evidence.
- Do not add match/mismatch labels, discrepancy flags, warnings or discrepancy
  counts for the two percentages. A difference alone does not exclude an
  otherwise usable observation or cause either value to be replaced.
  [ADR-0031](../../adr/0031-show-national-percentages-without-discrepancy-flags.md)
  records this choice. Verification still establishes calculation correctness
  from the stored inputs; it does not require agreement with EIA's percentage.
- Unusable observations are excluded with visible counts and reasons, while
  their source evidence remains available. Missing or invalid values are not
  silently represented as zero.
- Date, reported capacity, outage, EIA's reported percentage and their units
  are required. Missing or unusable values, or incompatible units, exclude the
  observation even when a share could otherwise be calculated.
- Reported capacity must be positive. Zero, negative, missing or invalid
  capacity excludes the observation from both the modeled national data and
  calculated daily results, with its source evidence and coverage gap visible.
  It is not included as a modeled observation with an unavailable share.
- Zero outage with positive capacity yields a valid 0% share when the other
  required values are usable. An unavailable result is never presented as 0%.
  These accepted rules are recorded in [ADR-0027](../../adr/0027-national-required-values-and-positive-capacity.md);
  retaining older valid data during refresh remains a separate effort.
- Repeated identical observations do not count as additional daily observations.
  If otherwise valid EIA observations conflict for the same date within one
  retrieval, the last record in the recorded source order wins. Keep one modeled
  row for that date and retain the original source evidence. This is a fallback
  for an unexpected case, not grounds to exclude the day or a claim about source
  revision timing. Invalid records remain subject to the accepted exclusion
  rules. See [ADR-0034](../../adr/0034-last-national-record-wins.md).
- Verification describes the dates and evidence examined, so a result supported
  by a sample is not presented as a guarantee about all historical data.
- Verification accounts for all 30 calendar dates in the fixed baseline with
  usable daily results or visible coverage gaps and exclusion reasons where
  applicable. It uses the same recorded evidence on repeated runs, without
  contacting EIA or inventing observations to fill gaps.
- Describe the baseline's limits: reported national capacity is constant in
  this sample, so it does not demonstrate behavior across historical capacity
  changes. Broader historical verification remains separate. See
  [ADR-0033](../../adr/0033-fixed-national-verification-period.md).

## Non-goals

- Facility and generator modeling, cross-level reconciliation, and investigation
  of the facility response's unresolved row-count discrepancy.
- Live ingestion, refresh/publication workflows and replacement of previously
  stored observations; their existing quality policies remain applicable to
  those later efforts.
- Backend delivery, authentication, authorization implementation and deployment.
- Frontend work, charts, outage-cause explanations and new analytical measures.

## Open questions

_None._
