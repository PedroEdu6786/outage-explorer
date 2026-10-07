# Challenge criteria and discussion index

Use this index to discuss what the challenge asks us to demonstrate and to
collect evidence for individual points. Each investigation has its own file,
with observations, explanations, product implications and open questions.
Discussion does not by itself change an accepted ADR or complete a requirement.

The first investigation confirms a facility response-count discrepancy and
reconciles the saved September samples. The accepted conclusion for the observed
requests is that EIA's facility `total` reflects generator records. Use actual
facility rows received across all successfully retrieved pages as our retrieved
count, preserving EIA's total separately. Counting before aggregation remains
the inferred internal explanation. [Point 002](002-river-bend-missing-observations.md)
adds corroborated historical River Bend omissions. [Point 003](003-cook-prolonged-outage.md)
adds a verified unusually long Cook Unit 1 outage. Three independent findings
are now documented, including an operating outlier within the user's expressly
accepted anomaly scope; broader challenge acceptance remains separate.

## Source and scope

Reviewed on October 3, 2026 against *Software Engineer — Technical Challenge*,
the supplied PDF (Part 2, PDF pages 4–5; deliverables, pages 7–8). The original
is outside this repository. The criteria below are a paraphrase so a clean
checkout does not depend on a contributor's Downloads directory. The
[project overview](../context/overview.md) records the current scope, and the
[backend specification](../specs/outage-explorer-backend/spec.md) translates it
into requirements and acceptance criteria.

The full challenge includes the web application, implemented in the separate
[web repository](https://github.com/PedroEdu6786/outage-explorer-web). The user
confirmed integrated acceptance complete on October 7, 2026; this records that
confirmation without claiming another automated verification run. Some extras, such as
broad analytical SQL and OAuth2, became project requirements through later
accepted decisions; keep those distinctions when discussing scope.

## Criteria to discuss

This is a navigation map, not a new implementation audit or completion score.

| Challenge area | What we need to demonstrate | Starting point |
| --- | --- | --- |
| Part 1 — Connector, US-01/06 | Three routes, pagination, required-field validation, Parquet, logging, safe reruns, documented failure behavior and an environment-supplied key | [Connector spec and status](../specs/data-connector/tasks.md); count semantics in [point 001](001-facility-row-count.md) |
| Part 2 — Model | Documented schema, ER diagram, keys, relationships, types, duplicate/invalid handling, backend-available Parquet or Delta | [Data model and ER diagrams](../context/data-model.md), [national contract](../specs/national-data-verification/contract.md), [detail contracts](../specs/facility-generator-verification/contract.md) |
| Part 2 — Daily fleet metric, US-08 | Implement and explain the daily fleet capacity offline share | [National verification](../specs/national-data-verification/verification.md), [metric meaning](../adr/0035-national-outage-capacity-meaning.md) |
| Part 2 — Reconciliation, US-07 | Compare all three grains over at least 30 days; identify period, entity, values and gap wherever they differ, with explanations | [Dedicated reconciliation](reconciliation.md): 30-day baseline plus historical, temporal, metric and identity analysis; 182 sampled dates, 11,182 facility/day groups and offline replay |
| Part 2 — Anomalies | At least three actual anomalies, each with a concrete period/entity/value example and product treatment; runnable queries or code | Three documented findings: response metadata, River Bend omissions and a verified prolonged Cook outage; each has runnable evidence and product treatment |
| Part 3 — Backend | Seeded personas, authentication, authorization before reads/execution, read-only SQL with every referenced table checked and results capped, Admin refresh, secrets excluded, rejection tests | [Backend specification](../specs/outage-explorer-backend/spec.md) |
| Part 4 — Web application | Login, permitted datasets, backend-paginated table and SQL input/results | Implemented in the [web repository](https://github.com/PedroEdu6786/outage-explorer-web); integrated acceptance user-confirmed October 7, 2026 |
| Delivery and live explanation | Runnable README, tests, ER diagram, DECISIONS.md, FINDINGS.md, Engineering Notes and incremental history; explain and change the solution live | [Decisions](../../DECISIONS.md), [ER diagrams](../context/data-model.md), [findings entry point](../../FINDINGS.md), [ADRs](../adr/), [devlog](../devlog/); final submission completeness is a separate review |

## Discussion points

| Point | Criteria | Evidence status | Discussion status |
| --- | --- | --- | --- |
| [001 — Facility advertised total exceeds returned rows](001-facility-row-count.md) | Part 1 pagination; Part 2 reconciliation/anomalies; US-07 | Confirmed in recorded samples and bounded live probes; internal cause inferred | Accepted discrepancy and received-row accounting; broader pagination evidence remains open |
| [002 — River Bend observations disappear](002-river-bend-missing-observations.md) | Part 2 reconciliation/anomalies; US-07 | EIA omissions on 43 dates corroborated by NRC; zero cross-grain MW gaps | Observed omission documented; upstream cause and any product change remain open |
| [003 — Prolonged Cook Unit 1 outage](003-cook-prolonged-outage.md) | Part 2 anomalies | 453 consecutive full-outage observations; longest completed run in the selected five-year NRC population; corroborated event context | Verified operating outlier within user-approved scope; valid source rows retained |
| [004 — Seasonal outages and event associations](004-seasonal-outages-and-events.md) | Part 2 temporal analysis and operating-event context | 6,940 national days over 2007–2025; monthly means, annual maxima and four event windows replayed offline; official sources corroborate event context | Expected seasonality with event-associated operating changes; no new data defect, cross-grain gap or additional counted anomaly established |

Use a new numbered file for each independent point. Link its input artifacts and
reproduction command. For findings, record the interval, entity identifiers,
actual values and gap, observed facts, hypotheses, existing product treatment,
proposals and remaining questions. Update this index with the conclusion after
discussion. Promote changed product/architecture decisions to an ADR when needed.

## Conclusion for the first finding

Point 001 is a real inconsistency in EIA response metadata. It is not evidence
that 1,200 facility observations were lost, and it is not a cross-grain MW
disagreement. Its Browns Ferry example supplies a concrete date, facility and
values. The user accepted documenting it as a discrepancy and using the actual
received facility-row count rather than EIA's advertised total. Its several
probes are one finding, not separate anomalies.

The received count covers all successfully retrieved pages, not just the first
page. Knowing that 50 rows arrived does not tell us whether a further page
exists; pagination completion needs separate evidence. Further investigation
or implementation must be proposed for review and explicitly approved before
execution.

The saved September samples have no capacity/outage reconciliation gaps. A zero-gap result
is still a result; we should preserve it and investigate further real periods
or other data properties for additional anomalies. Synthetic test cases and
unobserved missing-parent scenarios cannot fill the remaining findings.
