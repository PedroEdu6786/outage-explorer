# ADR-0054: Inspect user SQL in a bounded subprocess

Status: **Accepted by user direction**

Date: 2026-10-06

## Context

SQL inspection currently runs inside the API process. Input-byte, AST-node and
depth caps do not independently enforce parser wall-clock, CPU or memory limits.
The user accepted a separate bounded subprocess before SQL endpoint enablement.

## Decision

- Execute untrusted SQL parsing and reference inspection in a separate subprocess
  behind the application-owned SQL-inspection port. Bootstrap owns concrete wiring.
- Give that subprocess only SQL and fixed inspection settings. It receives no
  application sessions, operational database/cloud credentials or analytical data.
- Bound admission/concurrency, wall-clock time, CPU, memory and transport output.
  Validate its complete response before using the inspected scope.
- Confirm subprocess termination before releasing its capacity. Uncertain death
  retains ownership and prevents unsafe reuse; there is no API-process fallback.
- Preserve submitted SQL, supported analytical semantics and safe error vocabulary.
  Authenticate before inspection and authorize the complete inspected dataset
  scope before analytical input access, including reference-free queries.
- Retain analytical-worker SQL reinspection as a separate defense.

Numeric parser budgets remain open for measurement and review. The existing
ten-second analytical execution ceiling is unchanged; it is not a new parser
allowance. The concrete launcher, protocol, lifecycle and runtime enforcement
require design, implementation and controlled/native verification before readiness.

## Alternatives and consequences

API-process parsing with byte/AST caps alone leaves an unenforced pre-launch
resource boundary. A bounded subprocess adds startup and ownership work but keeps
parser exhaustion outside the API's process. No parser HTTP service, broker,
additional product codebase or persistence stack is introduced.

This records an accepted approach, not a completed implementation or passed
readiness gate. No API startup, endpoint activation, refresh, publication,
deployment or credential transfer is authorized by this decision.
