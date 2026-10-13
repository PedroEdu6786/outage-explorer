# ADR-0084: Keep publication eligibility policy outside the repository

Status: Accepted by user direction

Date: 2026-10-12

## Context

ADR-0082 put successful publication in one repository transaction, preserving
the lock and atomic writes. The repository also decided whether the active,
admitted and candidate bases matched and whether an initial load had the
required start date. Those are publication rules, not query construction.

## Decision

Put those rules in the pure domain `publication_policy.require_publishable_base`.
The repository reads the run and active base under the coordination lock,
passes domain values to the policy, validates stored base descriptors, and
performs the same atomic writes. It translates the domain's changed-base
result to the existing `StaleRefreshOwnerError` contract. The publication store
continues preflight validation and uncertain-commit reconciliation.

## Consequences

Database reads, mapping, transaction scope and writes remain in infrastructure.
The policy has no ORM, connection or application-error dependency. Publication
behavior, error messages, commit-loss recovery, schema and history are unchanged.
