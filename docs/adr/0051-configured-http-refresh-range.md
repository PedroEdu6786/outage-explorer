# ADR-0051: Use a configured range for HTTP refresh

Status: **Accepted by user direction**

Date: 2026-10-04

Refines ADR-0037's interval selection for the product HTTP endpoint. Preserves
explicit bounded connector intervals, initial-load policy, and CLI overrides.

## Context

During the data API requirements discussion, the user selected “Always use a
configured range” instead of having Admin choose start and end dates per request.
The earlier backend plan proposed date fields in the refresh request.

## Decision

- The Admin HTTP refresh action uses the backend's configured inclusive start
  and end dates. The request accepts no date or dataset overrides.
- Each run refreshes national, facility and generator observations together in
  the background. Resolve and validate the interval at admission and retain it
  with the run, so later configuration changes cannot alter admitted work.
- Admission and status responses expose the effective interval for transparency.
- Preserve the accepted initial live interval, April 2–October 1, 2026 inclusive.
  Subsequent runs use the configured bounded interval. Configuration ownership,
  field names and change mechanism remain design questions.
- This does not select a rolling range, latest-date discovery, scheduling, an
  HTTP configuration-management endpoint, or different connector CLI behavior.
- Preserve all existing authorization, verification, retention, resource-bound,
  and automatic complete-generation publication requirements.

## Alternatives and consequences

Dates supplied by Admin permit ad hoc refreshes but are outside the user's chosen
HTTP interaction. A configured interval makes refresh a single action and keeps
date selection in controlled backend setup. Updating the interval requires a
configuration change; the frontend cannot override it.

The choice defines product behavior without implementing configuration or a
worker, measuring supported intervals, or authorizing any live run/publication.
