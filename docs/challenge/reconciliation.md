# Cross-grain reconciliation: September 2026

Status: **30-day recorded comparison complete; all observed capacity and outage
aggregations match**. This is the challenge's reconciliation result, separate
from the [three anomalies](../../FINDINGS.md).

## Period and inputs

The interval is **September 1–30, 2026 inclusive**. Recorded EIA API v2.1.14
responses were retrieved on October 2, 2026 and are versioned in this repository.

| Grain | Observations | Observed entities | Natural key |
| --- | ---: | ---: | --- |
| National | 30 | One national series | `period` |
| Facility | 1,650 | 55 facilities | `period`, `facility` |
| Generator | 2,850 | 95 facility/generator pairs | `period`, `facility`, `generator` |

The [saved report](evidence/reconciliation.json) identifies each source snapshot,
SHA-256, retrieval timestamp and API version. Replay verifies every artifact
against its source bundle manifest before calculating results.

## Method

1. Check unique natural keys and the exact 30-day interval in every grain.
2. Check observed-entity date coverage and same-day parent/child relationships.
3. Sum generator `capacity` and `outage` by `(period, facility)` and compare
   with the corresponding facility observation.
4. Independently sum facilities and generators by date and compare both totals
   with the national observation.

Both measures are in **MW**. Calculations use `Decimal` from the source numeric
strings, without rounding before comparison. A gap is **detail sum minus reported
parent value**. Percentages are not additive and are not summed.

For any generator/facility mismatch, `generator_to_facility_differences` records
the date/facility key, measure, reported facility value, generator sum and signed
gap. `daily_reconciliation` records every date's national values, both detail
sums and both gaps, including matching dates. Missing parents and facilities
without generators are reported separately, rather than replaced with zero.

## Results

| Comparison | Groups compared | Capacity gaps | Outage gaps |
| --- | ---: | --- | --- |
| Generators → facility | 1,650 facility/day groups | All zero MW | All zero MW |
| Facilities → national | 30 days | All zero MW | All zero MW |
| Generators → national | 30 days | All zero MW | All zero MW |

All observed entities have all 30 dates. There are no generator observations
without a same-day facility and no observed facility/day without generators.
**No cross-grain MW mismatch was found in this interval**, so there is no
observed mismatch cause to explain.

### Concrete examples

On **September 1, 2026**, facility **46 — Browns Ferry**:

| Observation | Capacity MW | Outage MW |
| --- | ---: | ---: |
| Generator 1 | 1,227.4 | 24.548 |
| Generator 2 | 1,207.7 | 724.62 |
| Generator 3 | 1,226.6 | 0 |
| Generator sum | 3,661.7 | 749.168 |
| Reported facility | 3,661.7 | 749.168 |
| Gap | 0 | 0 |

For the national comparison on the same date:

| Observation | Capacity MW | Outage MW |
| --- | ---: | ---: |
| All generators summed | 97,620.5 | 2,714.245 |
| All facilities summed | 97,620.5 | 2,714.245 |
| Reported national | 97,620.5 | 2,714.245 |
| Each detail sum minus national | 0 | 0 |

## Interpretation and product treatment

Matching sums establish internal consistency of these recorded observations;
they do not establish complete upstream coverage or physical accuracy. All three
grains can share an omission, as the historical
[River Bend investigation](002-river-bend-missing-observations.md) demonstrates.

EIA's facility response advertises 2,850 rows but returns 1,650. That is a
[response-count metadata discrepancy](001-facility-row-count.md), not a MW
reconciliation gap. Its inferred internal explanation must not be presented as
the cause of a nonexistent capacity/outage mismatch.

The product preserves the independently reported grains instead of rewriting
one to force agreement. These are fixed evidence results, not an automatic
quality guarantee for every subsequent published generation. See
[DECISIONS.md](../../DECISIONS.md#d03-preserve-independent-grains-and-report-reconciliation-gaps).

## Reproduce offline from a clean checkout

Python 3.12+ is sufficient. No dependencies, credentials, AWS, EIA calls, database
or running application are required. From the repository root:

```sh
python3 docs/challenge/evidence/facility_row_count.py --reconciliation-only > /tmp/outage-reconciliation.json
diff -u docs/challenge/evidence/reconciliation.json /tmp/outage-reconciliation.json
```

A successful replay produces no diff. Hash, key or interval violations fail the
command; observed value differences are reported, not hidden. The shared script's
default mode additionally replays anomaly 001's eight recorded probes, now also
versioned and hash-checked; see that investigation's reproduction instructions.
