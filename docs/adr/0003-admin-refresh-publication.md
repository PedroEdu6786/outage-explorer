# ADR-0003: Publish completed Admin refreshes automatically

Status: **Accepted**

Date: 2026-10-01

## Context

The user chose a simple Admin refresh flow after considering a separate
review-and-publish step. Refresh takes time; the Admin should be able to
start it and see its outcome without approving a candidate dataset.

## Options considered

- Refresh and automatically publish on success: one Admin action with a
  completion status; selected for the current scope.
- Refresh, preview a candidate, then explicitly publish: adds an approval
  workflow that the user does not need now.

## Decision

The Admin starts a refresh. The backend performs it in the background and
automatically makes the updated data active on successful completion. The
Admin can check whether the refresh is running, succeeded or failed.

The previous published data remains available during refresh and after a
failed attempt. New queries use the updated data after publication; existing
queries finish on their original snapshot.

There is no candidate-review stage, approval action or separate publish
endpoint in the current scope. Routine data-integrity checks remain backend
responsibilities, with no additional Admin validation workflow.

## Consequences

Refresh authorization includes permission to make its successful result live.
Exact ingestion coverage, retention, job execution and operational persistence
mechanisms remain design details. This records product behavior, not a
completed implementation.

- [Backend plan](../specs/outage-explorer-backend/plan.md#refresh-and-publication)
