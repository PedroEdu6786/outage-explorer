# ADR-0088: Keep refresh admission decisions in domain policy

Status: Accepted by user direction

Date: 2026-10-12

## Context

ADR-0087 moved atomic admission into the run repository, but that method also
contained the replay-before-busy decision and the initial-load start rule.
Those are domain decisions, even though their inputs must be read under the
repository's coordination lock.

## Decision

`domain.publication_policy.replay_or_require_available` decides whether to
return an existing requester/key run or reject a slot occupied by another run.
`require_initial_load_start` applies the configured start-date rule when there
is no base generation; publication uses the same helper. The repository reads
current values under its lock, invokes these pure rules, translates the domain
busy result to the existing application error, and performs the run insert and
slot reservation in its one decorated transaction.

## Consequences

The repository still owns queries, mapping and the atomic transaction. It no
longer defines replay priority or initial-load eligibility. Existing error
types, ordering, schema and persisted outcomes remain unchanged.
