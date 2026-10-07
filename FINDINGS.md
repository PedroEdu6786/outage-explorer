# Data findings

The [challenge discussion index](docs/challenge/README.md) maps criteria to
evidence and keeps individual investigations separate.

| Finding | Result | Status |
| --- | --- | --- |
| [001 — Facility response counts](docs/challenge/001-facility-row-count.md) | September 2026 advertises 2,850 and returns 1,650 facility rows. In the observed requests, EIA's facility total reflects generator records. | Documented discrepancy and received-row accounting accepted; upstream internal cause inferred |
| [002 — River Bend observations disappear](docs/challenge/002-river-bend-missing-observations.md) | EIA omits River Bend on 43 checked 2013/2015 dates despite NRC reporting 100% power. On October 3–4, 2015 national capacity drops by 967 MW while all three grains still reconcile. | Source omission corroborated; upstream cause unconfirmed; no product change |

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

The required three-anomaly deliverable is **incomplete**. Two independent findings
are documented; one additional real finding remains to be established. Synthetic
test cases and multiple probes of the same issue are not additional anomalies.
