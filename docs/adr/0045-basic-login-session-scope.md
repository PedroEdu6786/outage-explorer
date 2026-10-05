# ADR-0045: Keep the initial login session scope basic

Status: **Accepted by user direction**

Date: 2026-10-04

## Context and decision

After considering automatic token refresh and sign-in continuity after service
restarts, the user requested reducing scope. Retain the original one-hour
application-session baseline in ADR-0014/0017/0018, without automatic renewal.

- A successful sign-in starts a fixed one-hour application session by default.
  Activity and browser reopening do not extend its expiry.
- Closing and reopening the browser within that session preserves sign-in,
  provided the session remains valid and the user has not logged out.
- After expiry, require sign-in again. Do not implement automatic token refresh
  or refresh-token lifecycle management for this effort.
- Preserve current-session logout and independent concurrent sessions.
- Do not require uninterrupted sign-in across backend restarts or special
  session recovery after outages. Users may need to sign in again after an
  interruption; implementation must not bypass expiry or logout.

Cognito remains the credential/login provider. A provider issuing a refresh token
does not require the application to use it. Provider login state and application
session expiry remain distinct; no credential re-entry or forced Cognito SSO
logout policy is selected here.

## Consequences

The brief's tentative automatic-renewal direction is withdrawn. Login integration
and current-session invalidation still need design and verification. This scope
reduction does not alter seeded users, role access, durable operational storage,
or analytical-data recovery requirements. No runtime implementation is added.
