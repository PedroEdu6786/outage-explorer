# National observation contract v1

Scope: contributor verification of the recorded September 1–30, 2026 national
baseline. This contract does not claim an upstream guarantee across all history.
It implements [the spec](spec.md) and ADR-0027/0031/0033/0034/0035.

## Evidence and requiredness

The [recorded national metadata](../../../data/verification/national-2026-09/metadata.json)
declares daily frequency, `YYYY-MM-DD`, no facets, and three measurements with
their units. The [recorded field profile](../../../data/verification/national-2026-09/profile.json)
(`routes.us`) finds all seven attributes present as strings in all 30 records,
with no missing values and unique `period` values. Metadata supplies meanings;
the complete sample profile and accepted required-value policy supply the
application's requiredness rule. The sample does not establish historical
nullability or key uniqueness.

| Source attribute | Modeled meaning | Required value |
| --- | --- | --- |
| `period` | National observation date; one selected observation per day | Real calendar date, exactly `YYYY-MM-DD` |
| `capacity` | EIA-reported national nuclear capacity | Finite decimal string, strictly positive |
| `outage` | EIA-reported national nuclear capacity out of service | Finite decimal string; zero is valid |
| `percentOutage` | EIA-reported outage percentage | Finite decimal string, required even when the ratio is calculable |
| `capacity-units` | Capacity unit | Exactly `megawatts` |
| `outage-units` | Outage unit | Exactly `megawatts` |
| `percentOutage-units` | Reported percentage unit | Exactly `percent` |

Every field is required, non-null, and a JSON string. No other attributes are
allowed. Numbers accept ASCII decimal notation with an optional sign, decimal
point and base-ten exponent. Surrounding whitespace, separators, underscores,
NaN and infinities are invalid. No numeric coercion, unit inference or value
replacement occurs. No additional outage or percentage bounds are inferred.

The metric is the **daily share of EIA-reported nuclear capacity out of service,
including full outages and partial output reductions**. The
[recorded research](../../../data/verification/national-2026-09/capacity-semantics.json)
preserves the source citations and findings supporting this meaning. Embedded
generator examples are supporting research only; verification does not load
or model a facility/generator dataset.

## Validation and selection

- Original sanitized response bytes remain in `national.json`; its SHA-256 and
  request identity are recorded in `manifest.json`. Supporting JSON documents
  are also preserved byte-for-byte and hashed. Sanitization predates this work
  and removed echoed request credentials; this is not the original wire response.
- Each source reference is the snapshot identity plus zero-based position in
  `response.data`. Invalid rows are excluded with field-specific reasons:
  `not_object`, `unexpected_attribute`, `missing`, `not_string`, `empty`,
  `invalid_date`, `invalid_number`, `incompatible_unit`, `nonpositive_capacity`.
- Excluded-row counts count each row once. Reason counts count occurrences,
  which may exceed the excluded-row count. An invalid date is recorded in the
  global ledger; its intended date is never inferred.
- For each date, select the usable record with the greatest source position.
  Earlier usable records equal to that winner are `duplicate`; different ones
  are `superseded`. Equality includes all parsed measurements and the date;
  units have already been validated. Equivalent decimal spellings compare
  equally, but original source strings remain intact. A/B/A selects the final
  A; a later invalid row cannot displace it. Selection does not establish
  revision recency.
- Every baseline date appears in coverage. Missing or wholly excluded dates
  have `result: null`, with linked exclusions where applicable. A valid
  zero-outage result has an exact zero fraction and `0.00` percentage.
- Missing files, checksum failures, malformed JSON/envelopes, unsupported
  versions, inconsistent provenance, or any interpretable date outside the
  fixed interval fail the verification run. These are bundle errors, not
  ordinary coverage gaps. Explicit alternative bundles are labeled `synthetic`
  when used for tests; they do not silently replace the recorded baseline.

## Calculation and output

The exact fractional share is `outage / capacity`. Its percentage is that
fraction multiplied by 100. Decimal inputs retain their source strings;
exact rational outputs carry integer-string numerators and positive
integer-string denominators. Neither calculation depends on binary floating
point or finite decimal division precision.

Both calculated and reported percentages are displayed to two decimals using
decimal half-up rounding (ties away from zero). For example, `1.235%` becomes
`1.24%`. This presentation policy makes no assertion about EIA's own rounding.
The two values come from the same selected record and receive no comparison
classification. A difference alone does not fail verification.

JSON report v1 contains the evidence manifest and its hash, per-record
dispositions, row and reason counts, 30 ordered coverage entries, exact/source
values, display percentages, metric meaning and evidence limitations. Markdown
provides readable results, exclusions, evidence identities and source links.
Run timestamps and absolute local evidence paths are excluded from report
content, so replay at another time or location is byte-identical.

## Evidence limits

The 30-day sample has constant capacity; it does not demonstrate behavior across
historical capacity changes or all source history. Exact historical capacity-data
vintage remains unverified. Daily reported status does not establish reactor
shutdown proportion, full-day averages, outage duration, lost energy or causes.
This verification checks processing and arithmetic against recorded EIA inputs;
it does not independently prove physical operation. Product authorization,
refresh/publication, storage and SQL isolation remain separate work.
