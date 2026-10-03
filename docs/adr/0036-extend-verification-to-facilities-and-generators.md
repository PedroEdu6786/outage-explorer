# ADR-0036: Extend the national verification approach to facility and generator data

Status: **Accepted scope; policies carried forward from the user's extension request**

Date: 2026-10-02

## Context and decision

The user requested similar implementation for generators and facilities, with
similar requirements to completed national verification. Carry forward the fixed
September 2026 replay, required usable values and positive capacity, exact
arithmetic, percentage presentation and last-valid-source-record fallback from
ADR-0027/0031/0033/0034/0035 to these bounded verification contracts.

Facility keys are `(period, facility)`; generator keys are
`(period, facility, generator)`, supported by recorded metadata and unique sample
keys. Generator IDs are facility-scoped; `facilityName` is a required source
attribute, not identity. Source order is deterministic fallback, not verified
revision recency. This extends ADR-0034's previously national-only fallback.

Report every date for each observed identifiable entity; explicitly state that
the observed roster is not proof of upstream completeness. Keep the facility
response's advertised 2,850 total and actual 1,650 rows visible without inventing
missing records or claiming matching aggregates prove pagination completeness.

## Alternatives and consequences

Copying the national implementation twice would duplicate identical arithmetic
and evidence handling. Share those policies and adapters with explicit grain
contracts instead. Using date alone or generator ID alone would merge distinct
observations. Requiring live retrieval would make this baseline nonreproducible.

Separate reports preserve each source grain; national totals remain authoritative
for the fleet metric. This extends contributor verification, not runtime storage,
authorization, SQL, refresh or deployment boundaries. Historical contracts and
facility pagination/completeness still require separate investigation.
