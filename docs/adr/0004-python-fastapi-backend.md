# ADR-0004: Use Python and FastAPI for the backend

Status: **Accepted**

Date: 2026-10-01

## Context and decision

The user accepted the proposed Python/FastAPI backend stack. Use Python for
the connector and backend and FastAPI for the HTTP API. This fits the planned
Python data-processing and DuckDB integration within one backend service.

## Alternatives and consequences

The earlier plan left language/framework selection open. The user selected
the existing proposal; no additional framework comparison is required.
Dependency versions and supporting libraries such as HTTPX, PyArrow and
SQLGlot still need implementation-level selection and compatibility checks.
This acceptance does not select a SQL isolation runtime or loading strategy.

- [Backend plan](../specs/outage-explorer-backend/plan.md)
