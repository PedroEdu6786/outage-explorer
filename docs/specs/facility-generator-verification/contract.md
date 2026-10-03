# Facility and generator observation contracts v1

These are bounded application contracts for the recorded September 1–30, 2026
baselines. They extend the [national contract](../national-data-verification/contract.md)
under [ADR-0036](../../adr/0036-extend-verification-to-facilities-and-generators.md).

## Evidence and schema

| Dataset | Recorded rows | Observed entities | Natural key | Required attributes |
| --- | ---: | ---: | --- | --- |
| Facility | 1,650 | 55 facilities | `period`, `facility` | National seven + `facility`, `facilityName` |
| Generator | 2,850 | 95 facility/generator pairs | `period`, `facility`, `generator` | Facility nine + `generator` |

Each sample has exactly 30 observations per entity and no duplicate keys. Recorded
metadata describes `facility` as plant code and `generator` as the facility's
generator ID. These are opaque, nonempty strings. Preserve leading zeros and
alphanumeric values; never coerce them to integers. Surrounding identifier
whitespace is rejected with `invalid_identifier`, never stripped to merge keys.
The source name is required, preserved verbatim and not part of the natural key.
The nine/ten recurring fields are strings throughout their respective samples.
This evidence does not establish upstream historical requiredness or uniqueness.

The [facility bundle](../../../data/verification/facility-2026-09/manifest.json)
and [generator bundle](../../../data/verification/generator-2026-09/manifest.json)
preserve the sanitized snapshots, metadata, profile and capacity research with
SHA-256 hashes. The original exploratory snapshot bytes/order are unchanged;
credential sanitization predates this work. No credential-bearing wire response
is claimed. Manifests identify each dataset, fixed period, route, request,
retrieval, snapshot, artifact hashes and bundle/contract/report versions.

## Validation, selection and calculation

The shared domain policy retains national's required fields: real ISO calendar
date, finite decimal-string `capacity`, `outage`, `percentOutage`, and exactly
`megawatts`, `megawatts`, `percent` units. Capacity must be positive. No missing,
null, non-string, whitespace-only or unexpected attributes are accepted. Decimal
parsing accepts ASCII decimal/exponent notation without surrounding whitespace,
nonfinite values, separators or numeric coercion. No additional physical bounds
are inferred; a reported percentage difference is not grounds for exclusion.

Validation precedes selection. Greatest recorded source position wins per natural
key. Earlier valid observations equal to the winner are duplicates; others are
superseded. Parsed equality includes date, identity, measurements and facility
name, so a rename is an attribute revision, not a new entity. Numerically equal
spellings collapse without losing source strings. A/B/A chooses the final A;
a later invalid record never replaces a valid earlier record. Source position
is a reproducible fallback, not evidence of revision recency.

For each selected observation, calculate exact `outage / capacity` and its
percentage using rational arithmetic. Display calculated and reported percentages
to two decimal places, half-up (ties away from zero). This is the daily share
for that facility or generator, including full outages and partial reductions;
it is not the ready-made national fleet metric or an average of percentages.

## Coverage and reporting

The entity roster consists of usable identifiers observed anywhere in the input,
including rows with invalid measurements, names or dates. For every roster entity,
show every one of the 30 dates, ordered by date and then exact text identifiers.
Link exclusions only when both identity and date are usable. Missing and entirely
excluded entity-days have a null result; valid zero outage has a zero fraction
and `0.00`. Unknown identifiers/dates remain in the global ledger. If no identity
can be established, show 30 unavailable dates and explicitly report unknown roster.
This coverage cannot detect entities missing from the entire bundle and does not
establish a historical operating roster.

Detail report v1 adds `dataset`, entity identity in coverage/source records, and
`source_accounting` to the national report's provenance, exact/source values,
dispositions, row counts, reason occurrences and limitations. It shows both the
response total and received rows, plus observed entities, unavailable entity-days,
roster availability and unverified upstream completeness. Reason occurrences may
exceed excluded rows; selected/excluded/duplicate/superseded partition source rows.
Names in Markdown tables are escaped; their original values remain in JSON.

The facility snapshot advertises **2,850** rows but returns **1,650**. Record that
difference prominently and do not invent 1,200 observations, suppress the usable
rows, or claim completeness from matching aggregates. The generator total of
2,850 matches received rows but likewise does not prove upstream completeness.
The source total must be a nonnegative ASCII integer string; malformed totals
are envelope errors, not row exclusions.

Both report formats are deterministic across clocks/locations. Dataset/route
confusion, invalid versions/provenance/envelopes, missing/corrupt artifacts, path
escapes and out-of-baseline interpretable dates fail the run. Ordinary row
exclusions/gaps are represented in a successful report. Output aliases cannot
overwrite evidence. Test modifications are labeled synthetic; real baseline
findings are reported separately. National report v1 retains its existing shape.

## Limits

Capacity is constant for each observed entity in this sample. It does not prove
historical capacity changes, exact capacity-data vintage, physical operation,
reactor shutdown proportion, full-day averages, outage duration, lost energy or
causes. No cross-grain reconciliation, national-value replacement, live fetching,
pagination repair, refresh, Parquet publication, operational database or product
authorization is implemented by these contributor commands.
