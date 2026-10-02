# ADR-0023: Exclude invalid source records from modeled data

Status: **Accepted direction; field contracts and report design pending**

Date: 2026-10-01

## Context

The user resumed the deferred data-quality discussion and selected exclusion
of unusable records rather than failure of an entire refresh for each bad row.
Exact EIA field contracts still require source documentation and data inspection.

## Decision

- Derive mandatory fields from the API documentation first. Where it does not
  specify requiredness, inspect collected records and require recurring
  attributes and attributes that help identify unique observations. Interpret
  recurring attributes as consistently present across the inspected records,
  not simply seen twice; record the evidence in the versioned contract.
  An observed pattern is an application requirement, not an upstream guarantee.
- Validate empty records/values, date fields that cannot be interpreted as
  dates, numeric fields that cannot be interpreted as numbers, and unexpected
  attributes outside the declared source-record schema. Additional attributes
  mean schema drift; do not silently extend the modeled contract.
- Exclude invalid records from modeled output and retain their raw evidence.
  Account for exclusions in the refresh validation outcome. A bad row alone
  does not block publication of the remaining valid records.
- This does not make failed page retrievals, corrupted files or failed uploads
  acceptable. Extraction and storage integrity checks remain separate.

## Alternatives and consequences

Failing a whole refresh for any invalid record is no longer the selected row
policy. Silent coercion to zero or silent exclusion would hide source problems.
Exclusion lets usable records proceed but can reduce analytical coverage.
Unexpected attributes could cause widespread exclusion until the contract is
reviewed; accepting them automatically is not selected.

The exact field list, empty-value representation and permitted nullable fields,
numeric/date parsing rules, and verified natural keys remain to be established.
Whether an entirely excluded dataset can publish remains open. Behavior when
a new invalid record has the same key as a previously valid record also needs
an explicit refresh rule; do not silently treat rejection as source deletion.

## Proposed quality report

The user requested an explanation, not a new report product. Propose extending
the existing Admin-only refresh outcome with per-route received, excluded,
duplicate-collapsed, superseded and modeled-row counts, exclusion reasons,
requested/usable date coverage and bounded examples linked to retained raw
evidence. Keep row totals distinct from reason counts because one excluded row
can violate several rules. Exact schema, storage and examples remain proposed.
No dashboard, Admin approval step or new access permissions are introduced.

- [Backend plan](../specs/outage-explorer-backend/plan.md#duplicate-prevention-and-data-integrity)
