# Facility advertised total exceeds returned rows

Status: **documented discrepancy; conclusion and received-row accounting
accepted by the user on October 3, 2026; EIA internal cause unconfirmed**.
See the [discussion index](README.md).

The saved facility response advertises 2,850 observations but contains 1,650.
The gap of 1,200 exists in the sanitized source snapshot before our validation
or modeling. Replaying all three grains and making eight bounded live requests
supports the accepted conclusion for the observed requests: the facility
endpoint's `total` reflects generator observations while its `data` array
contains facility aggregates. Our retrieved facility-row count is the number
of rows actually received across all successfully retrieved pages; EIA's
`total` is retained separately as source metadata.
We have not demonstrated lost facility data or obtained an EIA explanation.

## Challenge criteria

This investigation supports Part 1 pagination and Part 2 reconciliation and
anomalies (US-07; backend FR13/FR14 and AC11). The challenge asks for at least
30 days of cross-grain comparison and three real anomalies with concrete
examples, product treatment and rerunnable evidence. This document records one
response-metadata discrepancy accepted for our findings; multiple probes of
this issue are one finding. The [findings index](../../FINDINGS.md) lists all
three independent anomalies. The [dedicated reconciliation](reconciliation.md)
documents the complete 30-day MW comparison separately.

## Recorded evidence

The fixed samples cover **September 1–30, 2026 inclusive**, retrieved on
October 2 at approximately 01:57 UTC, API version 2.1.14. Each request used
daily frequency, `capacity`, `outage`, `percentOutage`, ascending period,
`offset=0` and `length=5000`. No facility facet was applied.

| Grain | EIA total | Rows in saved response | Observed entities | Rows per day |
| --- | ---: | ---: | ---: | ---: |
| National | 30 | 30 | One national series | 1 |
| Facility | 2,850 | 1,650 | 55 facilities | 55 |
| Generator | 2,850 | 2,850 | 95 facility/generator pairs | 95 |

Inputs are the versioned [national](../../data/verification/national-2026-09/manifest.json),
[facility](../../data/verification/facility-2026-09/manifest.json) and
[generator](../../data/verification/generator-2026-09/manifest.json) bundles.
The reproduction checks every artifact against its bundle hash, verifies unique
natural keys, and recalculates values from source rows using `Decimal`.
The [generated evidence report](evidence/facility-row-count.json) records source
hashes, timestamps, counts, every day's sums/gaps and the live-probe checks.

EIA documents `total` as the number of eligible rows before pagination, `offset`
as the starting row and `length` as the requested number of rows, subject to the
5,000-row JSON maximum. Both 1,650 and 2,850 are below that maximum, so the
documented cap alone cannot explain this response. See the
[official API documentation](https://www.eia.gov/opendata/documentation.php)
and [EIA FAQ](https://www.eia.gov/opendata/faqs.php), consulted October 3, 2026.

## What the samples establish

- All natural keys are unique. Every observed entity has all 30 dates. The
  existing offline verifiers select all 1,650 facility and 2,850 generator rows,
  excluding, collapsing or superseding none.
- All 2,850 generator rows have a same-day facility. Every observed facility/day
  has generator rows; grouping them produces exactly 1,650 facility/day groups.
- Capacity and outage sums match for **all 1,650 facility/day groups** and for
  **all 30 days** at both detail-to-national comparisons, with exact zero MW
  gaps. Percentages are not added or used as an agreement gate.
- On every day, the roster contains 20 facilities with one generator, 31 with
  two, three with three and one with four: 55 facilities and 95 generators.
  Thus `(95 − 55) × 30 = 1,200`, exactly the advertised/received count gap.

These facts establish internal consistency of the observed samples. They do
not independently establish the complete upstream roster or physical accuracy;
all three routes could share an omission or source issue.

## A concrete facility example

For **September 1, 2026**, facility **46 — Browns Ferry**:

| Source row | Capacity MW | Outage MW |
| --- | ---: | ---: |
| Generator 1 | 1,227.4 | 24.548 |
| Generator 2 | 1,207.7 | 724.62 |
| Generator 3 | 1,226.6 | 0 |
| Sum of generators | 3,661.7 | 749.168 |
| Facility observation | 3,661.7 | 749.168 |

Three generator records describe one facility observation. The live filtered
facility request also advertises three rows while returning this one row. Its
count gap is two; its capacity/outage aggregation gap is zero.

## Live checks

Eight read-only requests ran on **October 3, 2026, 20:07:13–20:07:32 UTC**.
All returned HTTP 200 and API version 2.1.14. Their exact public request
parameters, retrieval times and sanitized response bodies are preserved in the
versioned [probe fixture](evidence/facility-row-count/live-probes.json). This is
a byte-identical copy of the original local investigation download.
API keys and credential-bearing echoed requests are omitted; these are not
original wire bytes. The historical verification bundles remain unchanged.

Unless specified otherwise, these probes request September 1 only, daily
frequency, all three measures, `offset=0`, `length=5000`, sorted by period then
facility ascending. The generator probe also sorts by generator ascending.

| Probe | Change to request | EIA total | Returned rows |
| --- | --- | ---: | ---: |
| Facility day | No facet | 95 | 55 |
| Browns Ferry facility | `facets[facility][]=46` | 3 | 1 |
| Browns Ferry generators | Generator route, same facet | 3 | 3 |
| Clinton facility | `facets[facility][]=204` | 1 | 1 |
| Facility day beyond observed rows | `offset=55` | 95 | 0 |
| Facility day page 1 | `length=50` | 95 | 50 |
| Facility day page 2 | `offset=50`, `length=50` | 95 | 5 |
| Facility month beyond observed rows | September 1–30, `offset=1650` | 2,850 | 0 |

The two small pages have no duplicate keys and their union equals the full
55-row response, including all values. That response equals the recorded
September 1 facility sample; Browns Ferry generator values and the two filtered
facility examples also equal their recorded counterparts. The empty month
boundary probe is additional evidence, not a new full-month retrieval.

## Explanation and alternatives

**Leading inference:** EIA's facility total is calculated at generator grain,
before grouping into facility rows, while offset/length act on facility rows.
The multi-generator and single-generator controls, exact grouping counts,
matching MW sums and page boundaries all support this explanation. We cannot
assert a specific SQL implementation or an EIA-confirmed defect.

| Alternative | Evidence and remaining limit |
| --- | --- |
| Our validation or deduplication lost 1,200 rows | The gap already exists in the saved response; the baseline verifiers discard no rows. This cannot explain the observed raw count difference. |
| Ordinary 5,000-row truncation | Requested length exceeds both counts. The single-facility and single-day controls exhibit the same pattern far below the cap. |
| More facility pages remain | No rows at day offset 55 or month offset 1,650; the two day pages equal the full response. This weighs against that explanation for these requests, not for all intervals. |
| Wrong date or facility filtering | The one-day multi-generator control advertises three while the single-generator control advertises one. Returned identities/dates and values match the recorded examples. |
| Source changed between observations | The checked live rows equal the earlier sample, and the discrepancy repeats. Retrievals are still separate requests, not an atomic upstream snapshot. |

## Product treatment

**Accepted reporting conclusion:** use the number of facility rows actually
received across all successfully retrieved pages as the retrieved-row count.
For the recorded September response, that count is **1,650**, while **2,850**
remains the separate EIA-advertised total. For Browns Ferry on September 1,
the count is **one facility row**, while EIA advertises **three**. Do not use
EIA's advertised total as the number of facility rows retrieved or fabricate
observations to make the counts equal. Received rows and selected modeled rows
remain separate counts when validation or deduplication changes the latter.

**Pagination clarification:** counting received rows tells us how much data
we have, not whether another page exists. Receiving the first 50 facility rows
does not reveal the five on the next page. After retrieving those pages, the
received count is 55; the saved boundary probe at offset 55 separately returned
zero rows. Counting and establishing the end of pagination are distinct checks.
Neither a received count alone nor this inconsistent EIA `total` establishes
that retrieval is complete. A failed page cannot be treated as a successful end.

Existing accepted policy in [ADR-0036](../adr/0036-extend-verification-to-facilities-and-generators.md)
and [connector FR15/AC14](../specs/data-connector/spec.md) keeps advertised and
received counts visible, retains otherwise usable observations, and does not
invent rows to close the gap. The discrepancy alone is nonblocking; a known
failed or missing page remains a failure. The national metric continues to use
reported national values. Offline verification already preserves these counts;
this investigation does not claim end-to-end refresh behavior is implemented.

**Discussion proposal:** retain this evidence when designing live pagination;
do not use `received == total` as the sole proof of completion or keep requesting
pages indefinitely to reach an inconsistent total. Still require bounded calls,
deterministic ordering, failed-page handling and explicit completion evidence.
These probes do not select a production termination rule or validate all three
routes over the initial six-month load.

## Reproduce offline

From the repository root, Python 3.12+ or the existing virtual environment is
sufficient; no network, API key, database or application startup is needed.
All required inputs are versioned: the September regression fixtures and the
eight sanitized [recorded probes](evidence/facility-row-count/live-probes.json).
Replay verifies the fixture manifests and the probe file's SHA-256 before use.
A clean checkout needs no local investigation downloads:

```sh
.venv/bin/python docs/challenge/evidence/facility_row_count.py
```

To compare the deterministic output with the checked-in report:

```sh
.venv/bin/python docs/challenge/evidence/facility_row_count.py > /tmp/facility-row-count.json
diff -u docs/challenge/evidence/facility-row-count.json /tmp/facility-row-count.json
```

The small script is investigation code for these fixed JSON bundles, not a
general ingestion path. It recalculates the reported comparisons and replays
the saved live responses; it does not make new live requests. The existing
three verifier commands separately establish validation/selection outcomes.
Successful reproduction establishes repeatability, not upstream completeness.

Verification on October 3: all three existing offline verifier commands passed,
along with 84 national/detail integration tests. Report replay was byte-identical;
an independent calculation scaled source decimals to integer thousandths and
confirmed every capacity/outage sum. Ruff lint/format for the investigation
script, application mypy, local documentation links and `git diff --check`
passed. No new live connector or product authorization claim follows from these
checks.

## Open discussion and follow-up

1. Does the observed counting behavior hold across other dates, facilities and
   multi-page intervals? Propose additional probes for review before executing
   any further investigation.
2. What completion evidence should the connector retain when totals disagree?
   Review page ordering/termination separately; the accepted received-row
   accounting does not select a production pagination rule.
3. EIA confirmation would distinguish inferred behavior from a documented
   upstream issue. No support request has been sent.

The user's approval covers recording this discrepancy and reporting conclusion
in documentation. Further investigation or connector changes require review and
explicit confirmation before execution.

The investigation is resumed by the user's October 3 request after its earlier
deferral during connector planning. It remains separate from implementing
pagination and does not make resolving EIA internals a connector prerequisite.
