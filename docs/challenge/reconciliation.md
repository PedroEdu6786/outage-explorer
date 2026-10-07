# Cross-grain reconciliation and interpretation

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

## Extended analysis

The [extended report](evidence/reconciliation-extensions.json) adds calculations
from the same September baseline and replays the existing historical evidence.
Together the five nonoverlapping sample windows cover **182 sampled dates** and
**11,182 facility/day groups**. This is sampled coverage, not continuous history
from 2007 through 2026. These are additional analytical discussion points, not
additional anomalies or changes to product validation policy.

### 1. Matching totals can share an upstream omission

The historical replay covers these four additional intervals:

| Interval | Days | Facility/day groups | River Bend absent dates | NRC corroboration |
| --- | ---: | ---: | ---: | --- |
| 2007-01-01–2007-02-10 | 41 | 2,706 | 0 | Control interval |
| 2013-06-25–2013-08-02 | 39 | 2,427 | 30 | All 30 report 100% power |
| 2015-10-01–2015-11-05 | 36 | 2,219 | 13 | All 13 report 100% power |
| 2017-07-01–2017-08-05 | 36 | 2,180 | 16 | NRC 2017 not included |

Every capacity/outage aggregation matches across all **152 historical dates**
and **9,532 facility/day groups**. Nevertheless, River Bend is absent on
**43 NRC-corroborated dates** in 2013/2015 and another 16 observed 2017 dates
without that corroboration. Missing rows are not zero-outage observations.

This demonstrates why sum checks need a separate coverage interpretation.
Observed-roster continuity cannot detect a facility absent throughout an entire
sample; a verified historical roster or independent source is needed for that
claim. The [River Bend investigation](002-river-bend-missing-observations.md)
documents the identity mapping and evidence limitations.

### 2. The fleet percentage depends on its denominator

On **October 3, 2015**, national outage is **14,532.875 MW** and national
capacity is **100,034.4 MW**, producing **14.527877%** offline. Capacity on
October 2 is **101,001.4 MW**, a difference of **967 MW**, the adjacent-day
reported River Bend capacity.

Holding October 3 outage fixed and substituting that previous-day capacity
would produce **14.388786%**: a difference of **0.139092 percentage points**.
This is a denominator-sensitivity calculation, **not a corrected metric**.
Adjacent-date capacity is not an independently verified same-day measurement;
we do not backfill River Bend or alter reported national inputs.

The product's arithmetic can therefore be correct while the source denominator
has a coverage limitation. Both statements matter when explaining US-08.

### 3. Trace daily changes from units through facilities to the fleet

All **29 adjacent-day transitions** in September reconcile: generator outage
changes sum to the corresponding facility changes and fleet change. The report
lists each changed matched unit, per-facility attribution and residual gaps,
alongside added/removed observation keys. All September identity rosters are
stable. Missing observations in other inputs are reported separately rather
than assumed to have zero outage.

For **September 13→14, 2026**:

| Quantity | Change in outage MW |
| --- | ---: |
| Sum of unit increases | +860.516 |
| Sum of unit decreases | −1,817.071 |
| Net change | −956.555 |
| National outage: 9,060.809 → 8,104.254 MW | −956.555 |
| Attribution gap | 0 |

Examples of the underlying contributions:

| Facility / generator | Change in outage MW |
| --- | ---: |
| 6110 — James A Fitzpatrick / 1 | +692.080 |
| 6099 — Diablo Canyon / 2 | −469.560 |
| 6105 — Limerick / 2 | −403.956 |
| 880 — Quad Cities / 2 | −255.080 |

The selected examples are not the complete contribution list; the report
contains all changed units. The fleet's net improvement hides simultaneous
increases in outage elsewhere. These are changes in reported daily unavailable
capacity, not evidence of outage cause, restart timing or recovered energy.

### 4. Reconcile percentages with capacity weights

For a grain whose observations sum to the national capacity and outage:

`fleet share = 100 × sum(outage MW) / sum(capacity MW)`

This is the capacity-weighted average of the unrounded per-observation outage
shares. A simple mean gives a small plant the same weight as a large plant.

On **September 1, 2026**:

| Calculation | Offline percentage |
| --- | ---: |
| Simple mean of the 55 calculated facility percentages | 3.292100% |
| Facility capacity-weighted calculation | 2.780405% |
| Generator capacity-weighted calculation | 2.780405% |
| National calculation | 2.780405% |
| EIA reported national percentage | 2.78% |

Both weighted detail calculations equal the national calculation on all
30 dates. The report retains unrounded decimal calculations; the displayed
values above are rounded for readability. It does not add the source percentage
values, introduce disagreement flags or change the product's halfway-up,
two-decimal display policy.

### 5. Unit counts are a different measure from capacity offline

On **September 1, 2026**, the 95 generator observations contain:

| Reported observation | Count |
| --- | ---: |
| Zero outage MW | 84 |
| Outage greater than zero and less than capacity | 10 |
| Outage equal to capacity | 1 |

Thus **11 of 95**, or **11.578947%**, report nonzero outage, while only
**2.780405% of capacity** is reported offline. Counting affected observations
would answer a different question from US-08 and would conflate partial
reductions with full-capacity outages. Even an observation equal to full
capacity does not establish a full-day shutdown or an outage's duration.
The report supplies these categories for each date.

### 6. Generator IDs must be scoped to facilities

On September 1, generator ID **`1` occurs at 47 different facilities**. A join
or deduplication on `(period, generator)` would merge distinct units.
The correct identity remains `(period, facility, generator)`, and the
facility relationship uses `(period, facility)`. This is a concrete reason
for the natural keys in [DECISIONS.md](../../DECISIONS.md#d01-natural-keys-identify-observations-within-a-generation),
rather than a purely structural ER-diagram choice.

### 7. National agreement alone cannot rule out offsetting entity errors

The real baseline has no entity-level gaps. The extended report separately
records the number of mismatched facility/day groups, the signed sum of gaps
and the sum of their absolute values, for both capacity and outage.

An explicitly **synthetic regression test** adds 1.25 MW to one facility's
outage and subtracts 1.25 MW from another on the same date. National sums and
weighted fleet percentage still match, but two generator/facility comparisons
fail, with **2.50 MW of absolute gaps**. This demonstrates the need to reconcile
at the entity level before interpreting a zero national residual. It is a test
of the method, not a fourth real anomaly or a claim that those source rows are
incorrect.

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

Replay the extended calculations, including historical archive and NRC checks:

```sh
python3 docs/challenge/evidence/reconciliation_extensions.py > /tmp/outage-reconciliation-extensions.json
diff -u docs/challenge/evidence/reconciliation-extensions.json /tmp/outage-reconciliation-extensions.json
```

The extended command uses only committed inputs and the standard library. It
recalculates the historical report through its original integrity and pagination
checks, rather than trusting the saved historical summary. A synthetic fixture
mutation used by regression tests is never written back to the real evidence.
