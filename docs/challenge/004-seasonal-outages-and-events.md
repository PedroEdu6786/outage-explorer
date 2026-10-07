# Seasonal nuclear outages and documented event associations

Status: **observed seasonal pattern with documented operating-event context**.
This investigation explains recurring rises and falls in national offline
capacity. It establishes neither a source-data defect nor a cross-grain
reconciliation gap, and does not increase the three-anomaly completion count.

## Scope and method

Computed from saved EIA national responses for **January 1, 2007–December 31,
2025**, covering **6,940 unique daily observations**, with no missing dates.
Use complete calendar years to avoid bias from the incomplete 2026 year.
The source archive also contains 2026 observations through October 2; these
are validated but excluded from the monthly averages and annual ranking.

Each monthly mean pools all daily reported outage MW for that calendar month
across the 19 years, then divides by 1,000 for GW. This is an average of daily
status observations, not measured energy lost. Annual maxima rank outage MW;
where tied, replay selects the earliest date. National identity is `period`.
No facility or generator identity is inferred from the national series.

| Month | Mean offline capacity GW |
| --- | ---: |
| January | 3.95 |
| February | 7.13 |
| March | 14.55 |
| April | 20.14 |
| May | 14.22 |
| June | 5.75 |
| July | 3.21 |
| August | 3.16 |
| September | 7.68 |
| October | 18.45 |
| November | 13.94 |
| December | 5.56 |

All 19 annual maxima fall in March–May or September–November. April and
October averages are approximately six times the July/August values.

## Explanation of the recurring pattern

EIA documents that operators schedule refueling and maintenance in spring and
fall, when electricity demand is lower, to maintain availability during summer
cooling and winter heating demand. Individual reactors generally refuel every
18–24 months; staggered fleet schedules produce two national peaks per year.
This explains the recurring seasonal shape, but does not classify every
individual observation as planned maintenance.

Source: [EIA, Nuclear power plants undergo seasonal scheduled outages,
May 23, 2011](https://www.eia.gov/todayinenergy/detail.php?id=1490), reviewed
October 7, 2026.

## Concrete weather-event associations

Values below are national observations from the archived source pages. The
change is the later national outage MW minus the earlier value, **not the MW
attributable to the event**. Simultaneous maintenance, recoveries and unrelated
failures can contribute. Cross-grain gaps are **not evaluated** here.

| Event | Earlier national outage MW | Later national outage MW | National change MW |
| --- | ---: | ---: | ---: |
| April 2011 tornado outbreak | 2011-04-27: 28,474.584 | 2011-04-28: 31,093.354 | +2,618.770 |
| Hurricane Sandy | 2012-10-29: 27,842.61 | 2012-10-30: 32,719.784 | +4,877.174 |
| Hurricane Florence | 2018-09-13: 5,943.128 | 2018-09-17: 14,242.048 | +8,298.920 |
| Hurricane Helene | 2024-09-26: 10,645.504 | 2024-09-28: 15,074.768 | +4,429.264 |

- **2011 tornadoes:** EIA reports that transmission-line damage took all
  three Browns Ferry units, almost 3.5 GW, offline during an already active
  refueling season. The documented plant impact supports a weather contribution;
  it does not equal the net national change.
  [EIA](https://www.eia.gov/todayinenergy/detail.php?id=1490).
- **Sandy:** EIA documents East Coast reactor shutdowns associated with the
  hurricane. The October 30 value is the largest daily outage MW in this
  2007–2025 sample. Extended outages at San Onofre, Crystal River, Fort Calhoun
  and Turkey Point had already elevated 2012 outage levels.
  [EIA, November 2, 2012](https://www.eia.gov/todayinenergy/detail.php?id=8611).
- **Florence:** NRC's September 20 report records Brunswick 1 shut down for
  Florence and Brunswick 2 increasing power. The same report identifies
  concurrent refueling outages at other units. The full national increase
  must not be assigned to the hurricane.
  [NRC daily report](https://www.nrc.gov/documents-reports/document-collections/events-reports-associated-with/power-reactor-status-reports/2018/20180920ps).
- **Helene:** EIA describes Hatch 1 offline and Hatch 2 at 80% power because
  storm damage reduced grid demand, and Catawba reductions associated with
  electrical equipment damage. Nuclear output can fall because the surrounding
  grid is disrupted even when the plant itself has no significant damage.
  [EIA, November 5, 2024](https://www.eia.gov/todayinenergy/detail.php?id=63624).

External event sources were reviewed October 7, 2026. They supply event context;
the national source pages alone contain no cause codes. Facility/generator
contributions during these windows have not been replayed in this investigation.

## Additional documented causes to consider

Heat can restrict cooling: NRC event 48181 records Millstone 2 entering a
required shutdown on August 12, 2012 after its ultimate heat-sink water
temperature exceeded 75 degrees Fahrenheit.
[NRC event report](https://www.nrc.gov/reading-rm/doc-collections/event-status/event/2012/20120813en).
This is supporting context, not a quantified national heat attribution here.

Non-weather events can extend maintenance: EIA documents a 131-day Fermi 2
refueling outage in 2020 because of COVID-related work delays, and an 89-day
Grand Gulf refueling/maintenance outage during turbine-control modernization.
[EIA, September 18, 2020](https://www.eia.gov/todayinenergy/detail.php?id=45176).
These examples do not establish that all 2020 deviations were pandemic-driven.

## Classification and product treatment

The broad seasonal cycle is expected operating behavior. Short event-related
jumps or prolonged outages are candidates for further operating-anomaly
investigation, but a large value alone does not prove invalid data. Preserve
valid source observations under the existing validation/retention policy; do
not smooth, replace, exclude or label them automatically from this analysis.

Reconciliation asks whether generator/facility/national values agree for the
same dates and identities. This national-only temporal analysis does not
answer that question. Existing cross-grain evidence remains in
[the reconciliation analysis](reconciliation.md); it must not be extrapolated
to every date in these event windows. Matching sums also cannot establish cause
or upstream completeness, as finding 002 demonstrates.

Under [ADR-0035](../adr/0035-national-outage-capacity-meaning.md), offline capacity
includes partial reductions as well as full outages. It is not shutdown count,
household blackout count, a full-day average or lost MWh. The figures describe
saved EIA responses, not an audit of the current published generation or an
independent measurement of physical output. No product behavior or accepted
architectural boundary changes.

## Reproduce offline

The standard-library replay runs without credentials, network or application
startup:

```sh
python3 docs/challenge/evidence/seasonal_outages.py > /tmp/seasonal-outages.json
diff -u docs/challenge/evidence/seasonal-outages/report.json /tmp/seasonal-outages.json
```

The [source archive](evidence/seasonal-outages/sources.json.gz) preserves five
sanitized EIA pages, including empty boundary responses, from two historical
retrievals. Original page hashes were checked against their local retrieval
manifests before packaging. The [manifest](evidence/seasonal-outages/manifest.json)
records archive and page hashes. Exact request parameters, retrieval timestamps
and source numeric strings remain in the pages. The archive is contributor
research evidence, not a new product persistence format.

Replay verifies hashes, source inventory, successful recorded responses,
unique dates, finite numeric values, positive capacity, checked outage bounds,
MW units and complete analysis-period coverage. The
[saved report](evidence/seasonal-outages/report.json) recomputes monthly means,
annual maxima and event-window changes. External event narratives are linked
above and are not independently verified by offline replay.
