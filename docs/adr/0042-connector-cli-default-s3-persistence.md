# ADR-0042: Persist connector CLI output to S3 by default

Status: **Accepted by user direction**

Date: 2026-10-04

## Context

The contributor CLI builds verified local candidates, with S3 persistence exposed
as a separate operation in Phase 5. The user requested that running the connector
CLI store its data in S3 by default, without copying a manifest into a second command.

## Decision

The default candidate CLI operation collects EIA data, builds/verifies a local
candidate, and persists its complete immutable graph through the existing S3
application use case. Successful default execution requires complete S3 readback
and replay verification. Validate configured bucket/prefix/region before source
retrieval; credential resolution belongs to the injected SDK provider.

Keep `--local-only` as an explicit candidate-only opt-out. `make connector`
uses the durable default; `make connector LOCAL_ONLY=1` selects offline/local
behavior. Existing explicit `--operation persist/recover` commands remain useful
for retry and recovery without EIA. They cannot use `--local-only`.

A local success followed by S3 failure returns a failed durable outcome with a
safe error code and the verified local manifest reference for explicit retry.
It preserves local artifacts/reports and earlier S3 objects. Local JSON reports
still describe candidate creation, not a durable backend refresh outcome. A
verified receipt does not activate a generation or persist PostgreSQL outcomes.

The application coordinates candidate creation and persistence through injected
use cases; CLI parsing/output and bootstrap wiring retain their layer boundaries.
Imports/help perform no EIA, storage or SDK work. `.env` is not automatically
loaded; environment-only secrets and typed configuration rules remain unchanged.

## Alternatives and consequences

- Separate persist commands provide explicit staging control but did not meet the
  requested one-command workflow.
- Default S3 persistence meets that workflow and requires configured AWS access.
  Local-only remains available without AWS; controlled tests inject adapters.
- Default command success now means verified durable storage, rather than only
  local candidate verification. AWS failure must never silently fall back to a
  successful local-only result. Live/cloud verification remains separate evidence.
