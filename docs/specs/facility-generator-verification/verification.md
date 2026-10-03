# Facility and generator verification findings

Verified on 2026-10-02 against the fixed recorded September 2026 baselines.

| Measure | Facility | Generator |
| --- | ---: | ---: |
| Received / selected observations | 1,650 / 1,650 | 2,850 / 2,850 |
| Observed entities | 55 facilities | 95 facility/generator pairs |
| Baseline dates per entity | 30 | 30 |
| Excluded / duplicate / superseded rows | 0 / 0 / 0 | 0 / 0 / 0 |
| Unavailable dates within observed roster | 0 | 0 |
| EIA response total | 2,850 | 2,850 |

Facility total semantics remain unresolved: 2,850 advertised versus 1,650 received.
Both reports explicitly leave upstream completeness unverified. Matching
entity/date coverage is not proof that every upstream entity was retrieved.

The preserved snapshot hashes match the original recorded profile:

- Facility: `a0bae3e25ff11c0ed4e7721ecb0c79b4f4c798f95aa1e4111460157eec5376e9`
- Generator: `9f58a9cb19f19a585181f14c6d570d73b8de25310eefbfbdf041b1affeb23d93`

Both snapshots and all supporting artifacts are retained unchanged in versioned
bundles. See [contract v1](contract.md) and [ADR-0036](../../adr/0036-extend-verification-to-facilities-and-generators.md).

## Reproduce

From the repository root, after setup:

```sh
.venv/bin/verify-facility-data
.venv/bin/verify-generator-data
```

Equivalent module invocations:

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.facility_startup
.venv/bin/python -m outage_explorer.entrypoints.cli.generator_startup
```

Both installed and module commands ran successfully. Each writes `report.json`
and `report.md` to `build/{facility,generator}-verification/`. Generated reports
are ignored by Git; all replay evidence is included in the repository.

## Verification performed

`make check` passed on Python 3.14.6: dependency consistency, Ruff lint/format,
strict mypy, **314 tests**, and sdist/wheel builds. `git diff --check` passed.

- All 4,500 real detail rows were checked independently using integer-scaled
  original decimals and cross-multiplication, without using source percentages
  as an agreement gate. Source identifiers/names and every original value survive.
- Recorded metadata facets and all row fields support the bounded schemas;
  entity/date keys are unique and each entity's capacity is constant in the sample.
- Synthetic tests cover required values, invalid fields/units/numbers/dates,
  unknown attributes, identifier whitespace and leading zeros, same generator ID
  across facilities, names as mutable attributes, duplicate/revision A/B/A,
  percentage-only revisions and invalid later records.
- Coverage tests distinguish valid zero from missing and excluded entity-days,
  retain invalid-only entities and keep unknown identities/dates unassigned.
  Empty/unknown rosters still show all 30 dates and an explicit roster limitation.
- JSON/Markdown tests retain both percentages, escaped names, source positions,
  field-specific reasons and facility's total difference without percentage
  comparison flags. Corrupt/missing evidence, wrong datasets, invalid totals,
  out-of-period dates, failed CLI runs and output aliases are exercised.
- Fresh-interpreter CLI tests block network access, change the clock from 2026
  to 2035 and replay copied bundles from different paths; outputs are byte-identical.
- Exact startup-wrapper restrictions, negative fixtures and import/factory
  side-effect tests include both new commands. The existing national suite passes;
  newly generated national JSON and Markdown are byte-identical to prior reports.

No synthetic anomaly is claimed as observed in the real baseline. Historical
schema/coverage, physical operation, capacity vintage, source pagination,
cross-grain reconciliation, live ingestion, refresh, product authorization and
deployment remain outside this verification result.
