# Data findings

The [challenge discussion index](docs/challenge/README.md) maps criteria to
evidence and keeps individual investigations separate.

| Finding | Result | Status |
| --- | --- | --- |
| [001 — Facility response counts](docs/challenge/001-facility-row-count.md) | September 2026 advertises 2,850 and returns 1,650 facility rows. In the observed requests, EIA's facility total reflects generator records. | Documented discrepancy and received-row accounting accepted; upstream internal cause inferred |

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

The required three-anomaly deliverable is **incomplete**. This is one discrepancy;
two additional independent real findings remain to be established. Synthetic
test cases and multiple probes of the same issue are not additional anomalies.
