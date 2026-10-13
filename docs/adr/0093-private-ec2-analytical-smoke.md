# ADR-0093: Activate scoped analytical endpoints for a private EC2 smoke test

Status: **Accepted by explicit user direction**

Date: 2026-10-13

## Context

ADR-0055 permits a separately reviewed local preview/SQL checkpoint while full
capacity evidence remains open. This deployment uses a new Amazon Linux 2023
`t3.small` host in `us-east-2`, reached only through Session Manager tunnels.
The user selected this account, reusable RDS/Cognito/S3 resources, and private
smoke access, then confirmed Cognito sign-in on the host. The user reviewed the
private EC2 readiness packet and explicitly approved preview/SQL activation
with refresh idle.

The exact host worker image is
`sha256:0872c8a9a032572200b0598f6184f9a88ed80ea12b2bbd5ced833c111d0acea7`.
Runtime and parser profile identities are respectively
`d26c246a4f2a827356356da7e5f1fb36b796335cd25b61c01d22d54bc540e91b`
and `137c7017e33e25d9674f51aa8a4a9b1d61595dae76f519e69b4a5acbd6313912`.
Native Docker isolation had 19 passing checks, parser integration had 18,
and the analytical-only SQL/all-grain preview workload passed with 33 of 33
containers sampled. The published base and current generation resource files
passed exact descriptor, checksum, row-count and schema verification. The
matching isolation manifest and workload report SHA-256 values are
`8339eab34057669c88d90dcea9cd5eb3d00b040aff75cb1a0c9ccdacc06126c1`
and `f3bb5884124315009be583f0e90ea5549469af78b5566de9e47e39aad7f0fd7a`.

## Decision

- Add a distinct `private-ec2-smoke` analytical evidence scope. It requires
  reviewed profile/report identities and the explicit single-process loopback
  startup path, just like `local-preview-sql`. Generic runtime readiness rejects
  this scope. The API and web listeners remain on `127.0.0.1`; the EC2 security
  group has no inbound rules.
- Enable preview and SQL on this exact host/profile with the reviewed parser
  profile. Keep the independent refresh worker idle. Preserve application
  authorization, bounded subprocess SQL inspection, Docker isolation, S3 input
  integrity, confirmed termination and restart/rollback behavior.
- Retain the initial limits: 512 MiB container memory, 128 MiB engine memory,
  16 MiB temporary bytes and 10-second execution. These are containment limits,
  not measured production capacity.
- Record user review on October 13, 2026 in the host's evidence files. Preserve
  the individual native reports and analytical workload report on the host.
  Earlier failed measurement attempts remain visible.

## Open evidence

The workload's highest **sampled** container memory was 142,422,016 bytes and
lowest sampled host available memory was 1,032,417,280 bytes. Sampling does not
establish high-water peaks. Full high-water/spill and product S3 cold-cache
performance, simultaneous refresh/API capacity, Admin/session lifecycle
acceptance, and public ingress/TLS remain open. This ADR does not accept
production sizing or authorize a refresh, publication, or public endpoint.
