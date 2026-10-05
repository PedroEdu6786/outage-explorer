# ADR-0052: Reconcile interrupted refresh before explicit retry

Status: **Accepted by user direction**

Date: 2026-10-04

## Context

Background refresh must survive a browser disconnect, but that alone does not
define API, worker or host restart behavior. The user selected “Mark interrupted;
Admin retries” after publication reconciliation, with a healthy worker continuing
through an API-only restart.

## Decision

- A healthy background worker continues independently of an API-only restart.
- When a running refresh worker is lost, determine whether its publication
  committed before choosing a terminal outcome or permitting a replacement run.
- Confirmed publication remains successful. An unpublished interrupted run is
  marked `interrupted` and requires an explicit Admin retry.
- Do not automatically rerun source ingestion or resume source pagination after
  an interrupted run. Reconciliation of the existing run is automatic.
- API startup alone does not prove worker loss. Recovery must prevent a stale
  owner from publishing after its run is reclaimed.

## Alternatives and consequences

Automatic source restart could reduce manual intervention but would need bounded
attempts and backoff and could repeatedly consume upstream resources during a
persistent failure. Explicit retry lets Admin inspect the outcome first.

Worker supervision, durable ownership, status transport during database outages,
queued-but-unstarted recovery, and transaction/lease mechanics remain design
and verification work. No live restart or publication is performed by this ADR.
