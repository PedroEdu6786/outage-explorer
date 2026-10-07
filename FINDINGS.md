# Data findings

The [challenge discussion index](docs/challenge/README.md) maps criteria to
evidence and keeps individual investigations separate.

## Reconciliation

The [dedicated reconciliation analysis](docs/challenge/reconciliation.md)
documents September 1–30, 2026: all 1,650 generator/facility groups and all
30 daily detail/national comparisons have zero capacity/outage gaps. It includes
concrete values, the comparison method, gap semantics, evidence limits and a
clean-checkout offline reproduction command with a separate saved report.

The [extended analysis](docs/challenge/reconciliation.md#extended-analysis)
adds historical samples (182 dates and 11,182 facility/day groups including the
September baseline), daily change attribution, weighting/denominator examples,
partial-outage counts, identity scoping and offsetting-error diagnostics.
Its [offline replay](docs/challenge/evidence/reconciliation_extensions.py)
recomputes the saved source evidence; synthetic method tests remain separate
from the three real anomalies.

## Anomalies

| Finding | Result | Status |
| --- | --- | --- |
| [001 — Facility response counts](docs/challenge/001-facility-row-count.md) | September 2026 advertises 2,850 and returns 1,650 facility rows. In the observed requests, EIA's facility total reflects generator records. | Documented discrepancy and received-row accounting accepted; upstream internal cause inferred |
| [002 — River Bend observations disappear](docs/challenge/002-river-bend-missing-observations.md) | EIA omits River Bend on 43 checked 2013/2015 dates despite NRC reporting 100% power. On October 3–4, 2015 national capacity drops by 967 MW while all three grains still reconcile. | Source omission corroborated; upstream cause unconfirmed; no product change |
| [003 — Prolonged Cook Unit 1 outage](docs/challenge/003-cook-prolonged-outage.md) | September 21, 2008–December 17, 2009: 453 consecutive 100%-outage observations, the longest completed zero-power run in the selected 2008–2012 NRC population. | Verified operating outlier; NRC event context corroborated; valid observations retained |

Use the actual facility rows received across all successfully retrieved pages
as our retrieved-row count: **1,650** for the recorded September response.
Preserve EIA's **2,850** separately as source metadata. A count of received rows
alone does not establish that every page was retrieved; for example, 50 rows
on a first page do not reveal five more on a second page.

The [reproduction script](docs/challenge/evidence/facility_row_count.py) and
[saved report](docs/challenge/evidence/facility-row-count.json) reconcile all
30 September days and all 1,650 observed facility/day groups: capacity and
outage gaps are zero across the three recorded grains. This does not prove
upstream completeness or validate live connector pagination generally.

Finding 002 adds four historical intervals spanning 152 dates and 9,532
facility/day groups, with zero capacity/outage aggregation gaps. Its
[offline replay](docs/challenge/evidence/historical_omissions.py) includes
compressed, hash-verified inputs in the repository. Matching sums do not establish
complete coverage when every grain shares an upstream omission.

Finding 003 records a verified unusual operating event, within the user's
explicitly accepted anomaly scope. Its [offline replay](docs/challenge/evidence/cook_long_outage.py)
verifies the full Cook sequence against NRC, ranks completed runs across 104
units and preserves concrete values and documented event context.

**Three independent anomalies are documented**: two source-data discrepancies
and one verified operating outlier. Each has concrete observations, product
treatment and runnable evidence. This completes the three-finding documentation
target; it does not claim completion of the full challenge or product runtime
acceptance. Synthetic cases and repeated probes are not additional findings.
