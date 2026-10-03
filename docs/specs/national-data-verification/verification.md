# National verification findings

Implementation verified on 2026-10-02 using the fixed recorded September 2026
baseline. The user requested implementation directly from the spec and plan,
without creating an intermediate task list.

## Recorded evidence outcome

| Measure | Result |
| --- | ---: |
| Received national observations | 30 |
| Selected daily observations | 30 |
| Excluded observations | 0 |
| Collapsed duplicates | 0 |
| Superseded observations | 0 |
| Usable baseline dates | 30 of 30 |
| Coverage gaps | 0 |

The preserved national snapshot SHA-256 is
`b140ed2d61813f500089704506a52518914cc3bce7c1859f90ab04c50ad54e9c`,
matching the original source profile. Its bytes and source order are unchanged.
The [bundle manifest](../../../data/verification/national-2026-09/manifest.json)
identifies the retrieval, request parameters and supporting evidence hashes.

Example: September 1 reports capacity `97620.5` MW and outage `2714.245` MW.
The exact share is `542849 / 19524100`; its percentage is `542849 / 195241`.
The calculated display is `2.78%`, and the same record's reported display is
`2.78%`. Both remain visible without a percentage-comparison classification.

Run from the repository root:

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.startup
```

After installation, `.venv/bin/verify-national-data` is equivalent. Both were
executed successfully. Reports are written to `build/national-verification/`
as `report.json` and `report.md`; generated outputs are intentionally ignored
by Git and can be reproduced from the versioned bundle.

## Acceptance evidence

| Criteria | Verification |
| --- | --- |
| AC1–AC2 | Reviewed [contract v1](contract.md) against preserved metadata, all seven field profiles and capacity-semantics research; metadata/profile assertions pass. |
| AC3, AC13 | Byte/checksum checks, immutable loaded records, source positions and disposition ledger preserve replay evidence; corrupt/missing bundles fail. |
| AC4–AC6 | Synthetic tests cover every required field, invalid date/number/type/unit, unexpected fields, positive-capacity boundary and unique excluded-row counts. |
| AC7–AC8 | Identical and numerically equivalent duplicates, A/B/A, percentage-only changes, reverse processing order and later invalid rows select the last usable source position. |
| AC9–AC10, AC18–AC20 | All baseline ratios independently cross-multiplied using integer-scaled original decimals; deliberately wrong arithmetic fails. Synthetic tests cover exact/high-precision ratios, zero, halfway rounding and differing reported percentages. |
| AC11–AC12 | Serialized and rendered synthetic reports retain both selected percentages and contain no comparison/discrepancy diagnostics. |
| AC14–AC15 | Full, partial, empty and all-invalid coverage tests retain 30 ordered dates; unavailable values differ from valid zero; invalid dates stay unassigned. |
| AC16 | Rendered evidence-limit assertions cover historical coverage, capacity vintage, partial output meaning and all stated non-claims. |
| AC17 | Fresh-process CLI tests block network access, substitute 2026/2035 clocks and replay a copied bundle from a different working directory; both output files are byte-identical. |

`make check` passed on Python 3.14.6: dependency consistency, Ruff lint and
format checks, strict mypy, **205 pytest tests**, and sdist/wheel builds.
Architecture checks include CLI startup negative fixtures; existing HTTP and
fresh-interpreter startup checks pass. `git diff --check` also passed.

Tests for malformed/conflicting rows use explicitly labeled synthetic evidence;
no such anomalies were observed in the real 30-row baseline. Missing evidence,
invalid envelopes/versions, path escape, changed checksums/provenance, source
overwrite attempts and failed output writes return failures.

## Limits

This sample has constant reported capacity and establishes no historical
capacity-change behavior or exact capacity-data vintage. The results verify
processing and arithmetic against recorded inputs, not physical operation,
reactor shutdown proportion, full-day averages, duration, lost energy or causes.
Live ingestion, refresh/publication, facility/generator modeling, backend
authorization, SQL isolation and deployment remain outside this implementation.
