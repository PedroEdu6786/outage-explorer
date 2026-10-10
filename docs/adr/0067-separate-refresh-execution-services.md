# ADR-0067: Separate refresh execution responsibilities into application services

Status: **Accepted** (explicit user direction, October 10, 2026)

## Context

Extracting private methods made `RefreshExecution.execute` shorter but left one
class responsible for baseline restoration, candidate validation, persistence,
publication metadata and run lifecycle. The user requested distinct services
with independently testable responsibilities.

## Options

- Keep private helpers in `RefreshExecution`: fewer modules, but dependencies and
  resource rules remain concentrated in the coordinator.
- Inject focused application services: more explicit interfaces and wiring, with
  each responsibility testable independently and limited to its own dependencies.

## Decision

Use three services within the existing layered monolith:

- `RestoreRefreshBaseline` reads the pinned generation and run, restores its
  exact resources, and checks the restored baseline identity.
- `PrepareRefreshCandidate` constructs the frozen request, invokes candidate
  building, verifies identity and coverage, and validates retain/publish outcomes.
- `PrepareRefreshPublication` checks the durable persistence receipt and builds
  publication metadata from its exact descriptors and verified coverage.

`RefreshExecution` depends on application-owned protocols for these services. It
owns the committed claim check, run progress and quality reporting, terminal
outcomes, final atomic publication call, and exception classification.

Bootstrap constructs a `RefreshPipeline` for each run inside the existing resource
context. Each service receives only its required ports/callables, bounds and
clock. The factory owns staging, transports, workers and cleanup for the full run;
services do not create another resource lifecycle or construct each other.

## Consequences

- Resource rules can be tested without constructing `RefreshExecution`; the
  coordinator can receive substitute services through the same protocols.
- Services share the admitted run's bounded resources through explicit startup
  wiring. Candidate and publication preparation have no operational database port.
- Ownership is checked before resource work. Progress and quality updates retain
  their ordering, including recording coverage before final outcome validation.
- All-excluded outcomes skip persistence and publication. Before publication,
  ordinary errors may finish the run as failed; ownership/store errors propagate.
- The coordinator marks publication as started immediately before the atomic
  store call. Publication and subsequent context-cleanup errors propagate for
  reconciliation rather than overwriting an uncertain or successful outcome.
- There is no new deployment unit, transport, queue, persistence format, or change
  to the recovery and publication boundaries in ADR-0030, ADR-0052 and ADR-0064.
