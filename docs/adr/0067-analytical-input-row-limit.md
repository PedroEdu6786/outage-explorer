# ADR-0067: Allow 100,000 rows per analytical input dataset

Status: **Accepted by explicit user direction**

Date: 2026-10-19

## Context

The local API's verified resource cache rejects published datasets above 30,000
rows, while current connector model defaults allow 100,000 rows. The user
requested raising the Colima-side row limit to 100,000.

## Decision

Raise the cache's preparation limit to **100,000 rows per dataset**, inclusive.
Reject larger publication descriptors before reading their resource objects.
This is an input admission allowance; public pagination and SQL output caps retain
their existing contracts. Preserve file/byte/time budgets, resource integrity,
authorization and worker isolation. Apply the source change through the existing
local rebuild and validation workflow.

## Consequences

The API can admit datasets between 30,001 and 100,000 rows for verified preparation.
Other resource bounds may still reject a request. This limit is an initial local
allowance, not a measured capacity or performance claim. Full capacity acceptance
remains deferred under ADR-0055.
