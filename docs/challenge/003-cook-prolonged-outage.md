# D.C. Cook Unit 1: exceptionally long full-outage run

Status: **verified operating outlier, with corroborated event context**. This is
an unusual real event in the EIA data, rather than a corrupt observation or a
cross-grain mismatch. The user explicitly included verified unusual operating
events in the third finding's scope on October 6, 2026.

## Observation and concrete values

EIA generator **1** at facility **6000 — Donald C Cook** reports **100% outage
on 453 consecutive daily observations**, **September 21, 2008–December 17,
2009 inclusive**. On every date, reported outage MW equals that date's capacity
MW. NRC **D.C. Cook 1** reports zero power on all 453 dates.

| Date | Generator capacity MW | Generator outage MW | Generator outage % | NRC power % | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| 2008-09-20 | 1,009 | 0 | 0 | 100 | Positive-power observation before the reported evening trip |
| 2008-09-21 | 1,009 | 1,009 | 100 | 0 | First zero-power daily observation in this run |
| 2009-12-17 | 1,084 | 1,084 | 100 | 0 | Last zero-power observation in the run |
| 2009-12-18 | 1,084 | 1,051.48 | 97 | 3 | First positive-power observation after the run; still a partial outage |
| 2009-12-23 | 1,084 | 0 | 0 | 100 | Full reactor-power status reported |

Capacity changes during the run; requiring a constant MW value would split this
single full-outage sequence at capacity changes. The relevant condition is
`outage == capacity` with positive capacity, supported by reported 100% outage,
not identical numeric triples across the entire run.

## Why this is an operating anomaly

The saved NRC population covers **104 explicitly named units**, each with every
date from **January 1, 2008 through December 31, 2012**: **190,008 unit/day
observations**. Grouping consecutive zero-power observations yields **859 runs**.
Of these, **844 are complete within the sample**, with positive-power observations
immediately before and after the run. Fifteen boundary-censored runs are excluded
from the complete-run ranking.

Cook's **453 observations** form the **longest completed run in this selected
five-year population**. The next longest completed run has **195 observations**,
and the completed-run median is **7**. This is an empirical duration outlier,
not a fitted probability, a universal alarm threshold or a claim about all U.S.
nuclear history. The population includes all zero-power run types; its median
must not be described as the typical duration of a refueling outage.

Longer runs remain open at the sample boundary, including Crystal River 3 and
Fort Calhoun. They are not treated as completed events or assigned an inferred
end date. Cook was selected because both boundaries are visible and its status
is corroborated in EIA and NRC.

## Corroborated event context

NRC [event notification 44507](https://www.nrc.gov/reading-rm/doc-collections/event-status/event/2008/20080920en)
records Cook Unit 1's September 20, 2008 manual trip following a turbine-generator
malfunction, high vibration and a generator fire. The
[September 21 daily report](https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/2008/20080921ps.html)
reports zero power and references that event. The
[December 18, 2009 daily report](https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/2009/20091218ps.html)
reports 3% power and an increasing-power status.

The operator's [December 23, 2009 release](https://www.aeptexas.com/company/news/view?releaseID=1103)
also describes the long outage, turbine-blade damage and repair, and the return
to reactor power. It distinguishes reactor power from electrical output: full
reactor power after repair did not yet restore full electrical capability.
We therefore preserve EIA's reported status-based metric rather than treating
zero reported outage as independently measured full electrical output.

The NRC event and operator report supply cause/context; EIA's three outage
routes do not establish cause by themselves. NRC is EIA's stated status source,
so their matching percentages verify source representation, not an independent
measurement of physical output. The September 20 morning status and evening
trip are compatible; the daily record is not a full-day average.

## Product treatment

These are valid, positive-capacity observations. Preserve every dated record,
including the long sequence of full outages. Do not exclude it as bad data,
collapse observations across dates as duplicates, fill it with zero outage or
classify the reactor as retired merely because the run is long. Daily identity
includes the date. Use each observation's own capacity and retain source values
and provenance across refresh, as required by the existing validation and
retention policies.

The national fleet metric continues to use the reported national observation.
On September 21, 2008, national capacity is **100,754.9 MW** and outage is
**14,005.318 MW**; the reported share is **13.9%**. Cook's same-day facility row
has **2,069 MW** capacity and **1,009 MW** outage: Unit 1 is fully out while
Unit 2 reports zero outage. A generator's 100% outage is not a 100% facility
or national outage.

Counting consecutive qualifying observations is a reproducible analytical
query, not an automatic new product alert. No anomaly detector, event classifier
or historical ingestion change was implemented. **453 daily observations do
not establish 453 uninterrupted 24-hour periods or a measured lost-MWh total.**
Positive reactor power on December 18 also does not establish the time of
connection to the electrical grid.

## Reproduce offline

The [replay script](evidence/cook_long_outage.py) uses Python 3.12+ and the standard
library only; no credentials, network, database or application startup is needed:

```sh
python3 docs/challenge/evidence/cook_long_outage.py > /tmp/cook-long-outage.json
diff -u docs/challenge/evidence/cook-long-outage/report.json /tmp/cook-long-outage.json
```

The [compressed archive](evidence/cook-long-outage/sources.json.gz) contains 18
source/manifest files: complete sanitized EIA pages and empty boundaries for
the unfiltered national route and Cook-filtered facility/generator routes,
five NRC annual files, two NRC daily reports and the NRC event notification.
The [manifest](evidence/cook-long-outage/manifest.json) records URLs, hashes and
evidence limitations. Exact EIA parameters/timestamps are preserved. Downloads
occurred October 7, 2026 UTC (October 6 locally); individual NRC request times
were not captured.

Replay verifies all source hashes, unique ordered keys, page offsets/empty
boundaries, units and numeric bounds. It compares **3,654 Cook generator/day
observations** against NRC, reconciles both Cook units to the facility for
**all 1,827 dates**, recomputes every population run with censoring, and checks
the two daily-report boundaries. The [saved report](evidence/cook-long-outage/report.json)
contains counts, top completed runs and the exact example observations.

The compact EIA evidence is filtered to Cook and cannot replay whole-fleet
generator-to-national sums. The existing findings provide independent all-grain
reconciliation evidence. Verification of this finding passed offline replay,
byte-identical report comparison, Ruff lint/format, documentation links and a
credential scan of the source archive. Product code did not change; application
tests and live product checks were not run.
