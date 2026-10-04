# ADR-0038: Deploy on EC2; keep development local

Status: **Accepted by user direction**

Date: 2026-10-03

Supersedes the ECS hosting selection in [ADR-0011](0011-ecs-hosting.md).
Preserves PostgreSQL on RDS under [ADR-0032](0032-postgresql-on-rds.md).

## Context

The user selected a move from ECS to EC2 and explicitly clarified that an EC2
instance is not required for local development and must not block it. The user
also confirmed completion of Cognito setup and the RDS connection. These are
user-reported setup results, not new agent-run integration checks.

## Decision

Use Amazon EC2 as the deployment target for the single active backend replica.
Run development locally, using configured RDS, Cognito and S3 resources as needed.
EC2 provisioning and deployment design are separate from local implementation
and testing; neither is a prerequisite for continuing connector development.

Keep the layered Flask monolith, application-owned permissions in PostgreSQL,
durable Parquet in S3, and bounded local analytical cache. Do not restore SQLite
or its former durable host-volume proposal. Query-ID metadata remains ephemeral.

## Consequences and open implementation choices

- Instance sizing, OS, packaging, process supervision, ingress/TLS, deployed
  connectivity, IAM access and rollout/recovery procedures remain deployment work.
  This decision selects neither containers nor a particular service manager.
- Refresh remains outside request/import/app-factory lifecycles. One backend
  replica does not settle the WSGI process count or refresh ownership mechanism.
- User SQL still requires the isolated execution boundary, authorized inputs,
  resource limits, and no operational database or cloud credential access.
  EC2 selection alone does not demonstrate isolation; host-provided credential
  access must also be excluded from analytical workers.
- Local development and integration tests use PostgreSQL; unit tests may use
  fakes. Cloud setup completion does not implement the application's adapters,
  token/session mapping, permissions, migrations or publication transactions.
- Production runtime evidence remains required before enabling affected paths,
  but missing EC2 infrastructure must not block independent local development.

## Alternatives and verification

ECS was the previous hosting choice; the user explicitly replaces it with EC2.
Requiring a development EC2 instance conflicts with the user's local workflow.
No cost or performance advantage is asserted without measurement.

This change records direction and synchronizes documentation. It does not
provision resources, deploy the application, or independently verify the reported
RDS/Cognito setup. Historical ADRs retain their original content for traceability.
