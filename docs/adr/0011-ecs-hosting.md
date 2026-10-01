# ADR-0011: Host the backend on Amazon ECS

Status: **Accepted service; launch and storage pattern proposed**

Date: 2026-10-01

## Context and decision

The user selected ECS and requested an established deployment pattern suited
to the existing single-backend, SQLite, S3 and local Parquet cache design.
ECS is now the compute orchestration service. No resources are provisioned.

## Proposed implementation and alternatives

Recommend ECS on EC2 with a separately managed EBS data volume mounted into
the backend for SQLite. Keep that volume independent of task replacement,
with explicit single-owner placement and mount checks. Disposable cache and
query scratch have separate budgets. Prevent overlapping backend owners
during deployment; an interruption is acceptable only once documented.
Reattachment on host replacement still needs a concrete procedure.

Fargate remains an alternative, but its ephemeral task storage does not meet
durable SQLite requirements. ECS service-managed EBS task volumes are also
ephemeral; they are not the proposed host-managed EBS volume. A shared EFS
mount is not a transparent substitute for SQLite WAL's local-host requirement.
Changing the database solely to fit another deployment pattern is not selected.

The launch type, volume lifecycle and query sandbox implementation remain
proposals pending the query-runtime discussion and feasibility checks.
Backup/retention policy is deferred under ADR-0010.

## References

- [ECS storage options](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using_data_volumes.html)
- [ECS host bind mounts](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/bind-mounts.html)
- [EBS preservation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/preserving-volumes-on-termination.html)
- [SQLite WAL](https://www.sqlite.org/wal.html)
