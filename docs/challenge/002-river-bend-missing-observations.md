# River Bend observations disappear despite NRC reporting power

Status: **observed source omission, corroborated for the saved 2013 and 2015
dates; upstream cause unconfirmed**. This is a second independent finding,
separate from [001's response-count discrepancy](001-facility-row-count.md).
It does not approve or implement a connector change.

## Concrete example

Facility **6462 — River Bend Station**, generator **1**, disappears from EIA's
facility and generator responses on **October 3–4, 2015**. NRC's annual file
reports **100% power** on both dates; its October 3 daily HTML independently agrees.

| Date | EIA generator rows | River Bend capacity MW | River Bend outage MW | NRC power % | EIA national capacity MW |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2015-10-02 | 99 | 967 | 0 | 100 | 101,001.4 |
| 2015-10-03 | 98 | Absent | Absent | 100 | 100,034.4 |
| 2015-10-04 | 98 | Absent | Absent | 100 | 100,034.4 |
| 2015-10-05 | 99 | 967 | 0 | 100 | 101,001.4 |

National capacity drops by exactly **967 MW** when the reactor disappears and
returns by the same amount. No other generator identity or capacity changes
across these three boundaries. The omission exists in the downloaded EIA
responses, before our validation/modeling. Each nonempty page is below the
5,000-row limit and retrieval ends with a successful empty boundary.

On October 3 national outage is **14,532.875 MW** and the reported share is
**14.53%**. The reported inputs yield approximately **14.527877%**: correct
arithmetic for a denominator that excludes River Bend. Do not silently add
967 MW or synthesize a missing row. Adjacent-date capacity establishes the
discontinuity, not an independently verified same-day capacity measurement.

## Scope and evidence

Downloaded **October 7, 2026 UTC** (October 6 locally), API version **2.1.14**,
daily frequency, all three measures, ascending natural-key ordering. Exact EIA
parameters/timestamps are saved. NRC URLs and byte hashes are saved; exact NRC
request timestamps were not captured. This is historical evidence.

| Inclusive interval | National / facility / generator rows | River Bend absent dates | NRC comparison |
| --- | --- | ---: | --- |
| 2013-06-25–2013-08-02 | 39 / 2,427 / 3,870 | 30 | All 30 have River Bend 1 at 100% power |
| 2015-10-01–2015-11-05 | 36 / 2,219 / 3,555 | 13 | All 13 have River Bend 1 at 100% power |
| 2017-07-01–2017-08-05 | 36 / 2,180 / 3,548 | 16 | EIA gaps observed; NRC 2017 not downloaded |
| 2007-01-01–2007-02-10, control | 41 / 2,706 / 4,264 | 0 | No River Bend omission in this control |

The 2013 gap covers June 25–July 24; River Bend appears July 25 with **969 MW**
and **0 MW outage**. The July 24 NRC daily HTML agrees with its annual file.
The 2015 sample has ten absent weekend dates and three absent weekdays; the
issue is not exclusively a weekend pattern. All dates and daily national values
are in the [report](evidence/historical-omissions/report.json).

Historical NRC **River Bend 1** maps explicitly to EIA `(6462, 1)`; the later
snapshot's **River Bend Station 1** identifier is not applied to these old files.
Sources: [NRC 2013 annual file](https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/2013/2013PowerStatus.txt),
[NRC 2015 annual file](https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/2015/2015PowerStatus.txt),
[July 24, 2013 daily report](https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/2013/20130724ps.html),
[October 3, 2015 daily report](https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/2015/20151003ps.html).

## Reconciliation and interpretation

All **152 dates** and **9,532 facility/day groups** in the four samples reconcile
exactly for capacity and outage, with **zero MW gaps**. This includes all 36 days
and 2,219 facility/day groups in the 2015 sample. A shared upstream omission
survives every cross-grain sum check.

These observations establish an EIA omission despite NRC reporting the reactor.
A historical identity mapping or ingestion problem is a hypothesis, not a
confirmed internal cause. NRC is EIA's stated status source, so this checks
EIA's representation of that source rather than independently measured physical
output. Sequential requests are not an atomic upstream snapshot.

Watts Bar 2 also appears intermittently near its licensing date. It is not
counted separately: commissioning context and a possible relationship to this
omission require investigation. Years, probes and denominator effects do not
turn one omission issue into several independent anomalies.

## Product treatment

Existing policy preserves usable reported national values and calculates the
metric from their same-day denominator. Missing entity rows must not become
zero-outage rows, inferred shutdowns or evidence of complete fleet coverage.
Initial loading has no older row to retain; the missing row remains absent.
[ADR-0037](../adr/0037-connector-initial-load-and-retention.md) retains a previously
stored valid natural key when its incoming replacement is absent; it does not
invent an observation for another date. Any retained exact-date row keeps its
provenance. Retained detail and newer national values do not independently prove
complete or reconciled fleet coverage.

A coverage alert against a verified historical roster could detect this class
of omission. That remains a proposal: no backfill, metric correction, roster
requirement or new quality gate was implemented. Sum checks alone cannot detect
an omission shared across the three routes.

## Reproduce offline

Python 3.12+ and the standard library suffice from a clean checkout:

```sh
python3 docs/challenge/evidence/historical_omissions.py > /tmp/historical-omissions.json
diff -u docs/challenge/evidence/historical-omissions/report.json /tmp/historical-omissions.json
```

The [compressed archive](evidence/historical-omissions/sources.json.gz) preserves
46 source/manifest files: complete sanitized EIA pages including empty boundaries,
three NRC annual files and three daily HTML reports. The
[manifest](evidence/historical-omissions/manifest.json) records byte hashes,
source URLs and original local bundle paths. Replay checks hashes, unique ordered
keys, contiguous offsets, numeric bounds, every capacity/outage aggregation,
missing River Bend dates and three daily/annual NRC controls. It performs no
network, database, S3, SQL-worker, refresh or publication operation.

Verification: replay and byte-identical report comparison, Ruff lint/format and
documentation links passed. Product code was unchanged; product tests and runtime
checks were not run.
