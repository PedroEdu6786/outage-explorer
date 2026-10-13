# ADR-0082: Publish generations in one repository transaction

Status: Accepted by user direction

Date: 2026-10-12

## Context

After ADR-0081, `_publish` still mixed raw database queries with publication
orchestration. Its descriptor insert, active-pointer switch, successful run
update and slot release must commit together. A lost commit response also needs
fresh, serialized reconciliation before the outcome can be reported.

## Decision

`PostgresqlPublishedGenerationRepository.publish` owns the whole database
operation in one `@with_session` transaction over the bounded pool. It checks
the fenced owner and frozen base, validates any active base through an ORM
mapping, inserts the immutable exact generation descriptors, updates the run
using database time, switches the active pointer and releases the refresh slot.
It returns a plain `RefreshRun` after the writes are flushed.

The publication store validates the generation and bounded quality report,
checks that the generation belongs to the owner run, delegates the transaction,
and retains the existing `AccessStoreError` catch that reconciles uncertain
commits against durable history. Fault-injection checks must exercise the ORM
session boundary as well as the fresh reconciliation checkout.

The existing psycopg base-validation helper remains for admission's current
transaction. Recovery remains on its existing psycopg transaction and is a
separate migration scope. No schema, active-pointer reset, or history rewrite.

## Consequences

Publication uses a mapped `PublishedGenerationRecord` for the write and active
base check. The read mapping is still partial schema metadata and must not
drive migrations. A generation is never activated by a separate decorated call;
uncertain commit outcomes still fail closed or reconcile under the coordination
lock.
