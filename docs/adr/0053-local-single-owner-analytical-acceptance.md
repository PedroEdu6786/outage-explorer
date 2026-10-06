# ADR-0053: Use a single API owner for local analytical acceptance

Status: **Accepted by user direction**

Date: 2026-10-06

## Context

The analytical runtime has process-owned preview cursors and ephemeral query-ID
metadata. The delivered local supervisor supports one API serving process with
threads. The user accepted that recommendation while settling readiness decisions.

## Decision

- Use one API serving process with threads for local preview/SQL acceptance.
- Preserve one analytical execution slot, including preparation and unresolved
  cleanup ownership, under ADR-0013.
- Supervise refresh independently; API shutdown must not stop a healthy refresh
  worker, under ADR-0052.
- Reject reloaders, fork-inherited resources and multiple API serving processes
  in this local acceptance configuration.

This decision applies to local acceptance only. Final EC2 process topology,
supervision and recovery-ledger storage remain open deployment decisions.

## Alternatives and consequences

Multiple API processes would require reviewed routing or shared ownership for
preview cursors, retained results and admission. That additional design is deferred.
API restart still loses ephemeral cursor/query mappings without rerunning SQL.

The user separately authorized representative measurements and chose to measure
before approving latency/resource budgets. This topology decision approves no
budget and grants no API startup, endpoint activation, refresh, publication,
deployment or credential transfer. T4.3/T4.C and original T1.7/T1.C remain open;
Phase 5 requires complete matching readiness and separate enablement direction.
