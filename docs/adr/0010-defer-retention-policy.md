# ADR-0010: Defer snapshot retention and recovery policy

Status: **Accepted**

Date: 2026-10-01

## Context and decision

The user explicitly deferred snapshot retention and recovery-policy work.
Do not make retention durations, historical browsing, rollback workflows,
automated generation cleanup or disaster-recovery design a prerequisite
for the current challenge implementation.

## Alternatives and consequences

Designing configurable retention and recovery now adds scope the user does
not need. For now do not implement automatic deletion of published snapshots.
This is a simple scope default, not an indefinite-retention service promise.
The challenge still requires reproducible findings, and existing requirements
still preserve active readers and durable data across container replacement.
Keep findings inputs available; do not build a retention subsystem for this.
Local cache eviction remains in scope under ADR-0008 and is separate from
deletion of authoritative S3 data. No backup schedule or recovery SLA is selected.
