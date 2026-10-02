# ADR-0025: Include a visible quality report in the Admin refresh outcome

Status: **Accepted; detailed format and storage pending**

Date: 2026-10-01

## Context

ADR-0023 accepts excluding invalid source records from modeled output. The
user accepted the visible quality report after reviewing an example showing
received records, excluded rows, collapsed duplicates, modeled rows and
exclusion reasons. This promotes the report proposal in ADR-0023 to accepted
scope; the underlying validation and duplicate policies remain unchanged.

## Decision

Include a quality summary with the existing Admin-only refresh outcome:

- Records received, invalid rows excluded, identical repeats collapsed and
  resulting modeled rows, identifiable by source dataset.
- Exclusion reasons and their counts, making publication with exclusions
  explicit. Count excluded rows once even when several reasons apply; reason
  counts may overlap and must not be presented as disjoint row totals.
- Keep refresh success/failure and publication outcome distinct from row
  quality counts so a failed extraction is not presented as a complete dataset.

The report informs the Admin; it does not introduce a dashboard, candidate
approval or an additional publication gate. Automatic publication on successful
refresh remains the accepted behavior in ADR-0003. Detailed record information
remains subject to the existing Admin-only refresh access boundary.

## Alternatives and consequences

Logs alone make exclusions harder to inspect through the refresh API. A report
attached to the existing outcome makes them visible without another workflow.
Counts require defined accounting across validation, deduplication and modeling.

Exact response schema, persistence and retrieval details remain open. Usable
date coverage, bounded rejected-record examples and superseded-value counts
remain proposed additions, not required by acceptance of the basic summary.
No implementation is claimed; track delivery in FR2a and AC2a of the spec.

- [Backend spec](../specs/outage-explorer-backend/spec.md)
- [Backend plan](../specs/outage-explorer-backend/plan.md#duplicate-prevention-and-data-integrity)
