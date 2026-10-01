# ADR-0006: Provide the daily fleet offline-capacity share ready-made

Status: **Accepted**

Date: 2026-10-01

## Context

User story: **As an Analyst, I want the share of total fleet capacity
offline per day, ready-made.** The user requested recording this meaning
after reviewing EIA metadata and sample records.

The question is: for each day, what percentage of the U.S. nuclear fleet's
reported capacity was offline? Fleet means the nuclear generators covered
by EIA's national dataset. This is a capacity measure, not a count or
percentage of reactors shut down. It is not an outage-cause classification.

## Options considered

| Option | Benefit | Limitation |
| --- | --- | --- |
| Require each Analyst to calculate the ratio | Minimal prepared model | Does not satisfy the ready-made user story |
| Expose only EIA's reported percentage | Direct source value | Does not independently reproduce the calculation |
| Calculate from national capacity/outage and retain EIA's percentage | Ready-made, reproducible metric with a source comparison | Requires explicit validity and comparison rules; selected |

## Decision

- Use the same day's national `outage` and `capacity` from
  `/v2/nuclear-outages/us-nuclear-outages/data/`, both in megawatts.
- Calculate `fleet_offline_share = outage / capacity` as a fraction;
  express the percentage as `100 * outage / capacity`.
- Retain EIA's `percentOutage` (already in percent) for comparison.
- Provide the daily metric through the backend's prepared analytical
  dataset, with `fleet_offline_share_daily` as the proposed SQL name.
  An Analyst can select a date range and use the result without deriving
  the formula or joining the source datasets. A chart or dedicated metric
  endpoint is not required; frontend remains deferred.
- Preserve the existing role policy: this national-only metric is also
  available to Viewers. The Analyst story does not restrict that access.
- Use reported national observations for the metric. Facility/generator
  aggregation is a separate reconciliation and does not replace the source
  national totals.

## Evidence and verification limits

Live metadata inspected on 2026-10-01 confirms daily frequency, no national
facets, `capacity`/`outage` in megawatts and `percentOutage` in percent.
Actual rows retrieved in that session:

| Date | Capacity (MW) | Outage (MW) | Calculated percentage | EIA percentage |
| --- | ---: | ---: | ---: | ---: |
| 2024-01-01 | 98,015.8 | 4,165.692 | 4.250021 | 4.25 |
| 2024-01-02 | 98,015.8 | 5,439.472 | 5.549587 | 5.55 |
| 2024-01-03 | 98,015.8 | 4,698.205 | 4.793314 | 4.79 |

The calculation matches all three reported percentages when rounded to
two decimals. This verifies field mapping, units and sample agreement;
it does not establish a universal rounding rule or full-history accuracy.
Reproduce the request with `frequency=daily`, `data[0]=capacity`,
`data[1]=outage`, `data[2]=percentOutage`, `start=2024-01-01`,
`end=2024-01-03`, `sort[0][column]=period`, `sort[0][direction]=asc`,
`length=5`, and an API key. These are observations from the retrieval date;
upstream revisions may change future responses.

EIA describes combining NRC daily status with annual and monthly generator
reports. Its product reports outage magnitude without outage causes.

## Consequences and remaining work

The user-story meaning and formula are accepted; source field mapping and
three-date agreement are verified. Q3 is **partially resolved**.

Detailed capacity-basis semantics, partial-output interpretation, missing
values, zero/invalid denominator handling, comparison tolerance and broader
historical checks still require explicit validation before implementation.
Verified keys, cross-grain reconciliation over at least 30 days and actual
anomaly findings also remain open. This decision does not mark AC10 or
implementation complete, or promise a value on days with unavailable data.

## References

- [EIA national dataset metadata](https://api.eia.gov/v2/nuclear-outages/us-nuclear-outages/?api_key=DEMO_KEY)
- [EIA national dataset browser](https://www.eia.gov/opendata/browser/nuclear-outages/us-nuclear-outages)
- [EIA methodology overview](https://www.eia.gov/todayinenergy/detail.php?id=60942)
- [Backend specification](../specs/outage-explorer-backend/spec.md)
- [ADR-0002 — Analytical dataset contracts](0002-analytical-dataset-contracts.md)
