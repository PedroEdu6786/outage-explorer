# ADR-0063: Refresh from a configured start through today

Status: **Accepted by user direction**

Date: 2026-10-07

Supersedes ADR-0051's configured end date and the data API plan's 183-day
admission ceiling for subsequent product HTTP refreshes.

## Context

The user requested a configured start date, an end date resolved to the current
date, and removal of the 183-day limit. Restarting the API every day to update an
end date would defeat that behavior.

## Decision

- Read `OUTAGE_REFRESH_START_DATE` at startup. Resolve today's UTC date for each
  new authorized admission, rather than at API startup. No caller date overrides.
- Stop using `OUTAGE_REFRESH_END_DATE` and the three `OUTAGE_REFRESH_*INTERVAL_DAYS`
  settings for HTTP refresh. Legacy values are ignored and should be removed.
- There is no fixed maximum number of days for subsequent HTTP refreshes.
  Snapshot the inclusive length in all three existing interval-budget fields;
  connector source/model adapters consume those frozen fields. Keep their durable
  schema so previously admitted runs remain executable with their original bounds.
- Preserve finite row, page, request, byte, memory, storage and deadline limits.
  A larger date range may exhaust these limits and fail without publication; this
  change does not certify arbitrary history fits the current resource profile.
- Idempotent replay returns the original interval before consulting the clock.
  A start after today is rejected before storing a run or fetching data.
- Preserve ADR-0037's explicit initial-load interval and CLI behavior. Without an
  active generation, initial loading still requires April 2–October 1, 2026;
  this change enables subsequent refreshes and does not bypass that policy.
- Today is the requested endpoint, not a claim that EIA already has observations
  for today. Missing observations retain the existing retention/validation policy.

## Alternatives and consequences

A rolling start would change the user's selected range. Discovering the latest
published EIA date requires extra source requests and is a different behavior.
UTC makes date resolution independent of host timezone. Operators can update the
start and restart the API to reduce a growing range when resource limits are hit.
No source fetch, service restart, initial load or publication is authorized here.
