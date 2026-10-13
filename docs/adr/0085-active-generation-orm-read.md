# ADR-0085: Read the active generation through its repository

Status: Accepted by user direction

Date: 2026-10-12

## Context

`PostgresqlResourcePublicationStore.active_generation` opened a psycopg
connection and delegated a raw join to the generation repository. The existing
ORM records already map the active pointer and published descriptors.

## Decision

`PostgresqlPublishedGenerationRepository.active_generation` uses `@with_session`
and a SQLAlchemy join from the active pointer to the published generation. It
returns a domain `ResourcePublishedGeneration` before the session closes, or
`None` when no matching active generation exists. Descriptor validation keeps
the existing fail-closed behavior. The publication store delegates directly.

This read owns its own transaction; admission's base check and publication's
atomic write retain their existing transaction boundaries.

## Consequences

The active-generation query now follows the same repository convention as the
other migrated reads. No schema or publication-pointer change is required.
