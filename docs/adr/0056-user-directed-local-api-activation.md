# ADR-0056: Activate local endpoints using accepted service assumptions

Status: **Accepted by explicit user direction**

Date: 2026-10-06

## Context

The user approved the matching analytical/parser reports and containment limits,
confirmed Analyst access and existing S3 publication, then instructed:
“assume all works, stop validating the services and enable api endpoints”.

## Decision

Activate the local API on the existing native Linux runtime using the reviewed
profiles. This direction supplies the separate startup/activation authorization
and supersedes further external-service and browser acceptance as preconditions
for this local activation. Stop additional Cognito, PostgreSQL and S3 probes.
Previously missing or unsuccessful checks remain recorded as such; service
availability is user-assumed, not newly verified.

Retain application authorization, bounded subprocess SQL inspection, worker
isolation, exact profile checks, hard resource bounds and lifecycle cleanup.
Normal startup enforcement stays enabled. Use the configured trusted application
identity for the API; parser and analytical workers receive no cloud credentials.
Refresh remains idle. No source refresh, publication, production deployment,
benchmarking or push is authorized by this local activation.

T4.L3 and remaining user-access service/browser checks remain incomplete evidence,
but no longer block this local startup. T4.LC records this scoped exception;
original full checkpoints and unperformed Phase 5 functional checks stay open.

## Alternatives and consequences

Continuing pre-start service validation was explicitly rejected by the user.
The API may return bounded service-unavailable responses if an assumed dependency
is unavailable. Activation establishes a running local listener and configured
endpoints; it does not claim successful authenticated data requests or release
acceptance.
