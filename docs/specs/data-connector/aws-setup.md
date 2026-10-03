# Connector AWS setup

Status: **S3 development setup verified; RDS and Cognito deferred by user**.
Observed October 3, 2026 through the AWS MCP using `outage-explorer`.
These are development/demo resources, confirmed by the user. Revalidate this
inventory before provisioning; observations do not establish runtime acceptance.
The user selected “Continue with S3 and defer RDS/Cognito”; the discovery-policy
attachment and database provisioning below are future work, not current blockers
for the S3 setup or fixture-based connector implementation.

## Confirmed target

| Setting | Value |
| --- | --- |
| Account | `596447731027` |
| Local AWS profile | `outage-explorer` |
| Verified IAM principal | `arn:aws:iam::596447731027:user/pedroeducruz` |
| Region | `us-east-1` |
| S3 bucket | `arkham-outage-explorer` |
| S3 prefix | `data/` — user confirmed, no leading slash |
| Cognito pool | Not configured; previous identifier removed at user request |
| Cognito app client | Not yet identified |
| RDS endpoint/database credentials | Not yet provisioned |

The nonsecret S3 target values are in `.env.example` and the local ignored `.env`.
The Cognito pool setting is blank; its earlier value was removed from project
files, saved memories and accessible local logs at the user's request.
The connector adapters do not yet consume these settings. `AWS_PROFILE` is for
local development; deployed application/refresh processes should receive their
own role, while analytical workers receive no cloud/database credentials.
The existing `EIA_API_KEY` entry was preserved without displaying or validating
its value. No EIA retrieval or dataset publication was performed here.

## S3 evidence

- `GetBucketLocation`: default region (`us-east-1`).
- `GetPublicAccessBlock`: all four public-access protections enabled.
- `GetBucketEncryption`: default `AES256` (SSE-S3).
- `GetBucketVersioning`: enabled.
- `GetBucketLifecycleConfiguration`: `NoSuchLifecycleConfiguration`.
- `GetBucketPolicy`: `NoSuchBucketPolicy`.
- Root object listing succeeded and returned no objects/prefixes before the probe.
- A unique synthetic object under `data/_setup-checks/` was created using
  `PutObject` with `IfNoneMatch="*"`; `HeadObject` and an authenticated presigned
  download succeeded. A second conditional creation of that key returned
  `PreconditionFailed`, as expected. The exact temporary object version was
  subsequently deleted; no test dataset or active-generation pointer was created.
- A second probe uploaded a real 987-byte synthetic Parquet file through a
  presigned conditional PUT, downloaded it, and compared exact bytes, SHA-256,
  Parquet schema and values. All comparisons passed. SHA-256:
  `48d31e3a84a6fb462136c206cecec97faa5f2783dd06f2cb14daa75ab9f8a912`.
  `HeadObject` confirmed 987 bytes and `AES256` encryption. Deleted the exact
  object version after verification; a version listing confirmed no remaining
  versions or delete markers under the synthetic probe prefix.

This proves the tested principal can perform these operations on the probe.
It does not prove the future task role's permissions, production adapter
verification, multipart behavior, or publication/recovery correctness. Versioning
alone does not prevent overwrites; the adapter must use conditional creation and
verify same-key retries. No bucket policy enforces that requirement currently.
Retain the accepted published-data retention behavior: do not introduce expiration
or authoritative-object cleanup as part of connector implementation.

See [AWS conditional-write behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

## Deferred RDS/Cognito permission prerequisite

The current principal received `AccessDenied` for:

- `cognito-idp:DescribeUserPool` and `cognito-idp:ListUserPoolClients` on the
  supplied pool. Its existence/configuration and intended app client are unverified.
- `rds:DescribeDBEngineVersions` and `rds:DescribeOrderableDBInstanceOptions`.

An account administrator can attach
[`infra/aws/setup-discovery-policy.json`](../../../infra/aws/setup-discovery-policy.json)
as an inline policy named `OutageExplorerSetupDiscovery` to `pedroeducruz`:
IAM → Users → pedroeducruz → Add permissions → Create inline policy → JSON.
It now grants only RDS engine/instance-option discovery in `us-east-1`.
The pool-specific Cognito statement was removed with the identifier. A fresh
pool configuration and scoped discovery permission would be needed if that work
is resumed; do not reconstruct the removed value from historical context.
It grants no resource creation, user administration, or IAM mutation.

Own IAM user/policy inspection was also denied. No policy-completeness or
least-privilege claim is made about the existing principal. The new JSON policy
has been parsed locally; it has not been attached or validated by IAM.
AWS denial of discovery does not prove creation is denied: creation permissions
have not been tested. Do not switch to an unrelated AWS profile to bypass this.

## RDS preparation and remaining choices

`DescribeDBInstances`, `DescribeDBClusters`, and `DescribeDBSubnetGroups` returned
empty lists in `us-east-1`. This is a regional observation, not an account-wide
inventory. ADR-0032 still requires private RDS PostgreSQL with verified TLS.

The discovered default VPC is `vpc-00c1ecd5410a16bc9` (`172.31.0.0/16`). Its six
default subnets use the main route table's Internet Gateway route and enable
public-IP assignment. Only the default security group was returned. Do not use
its broad self-access rule as the application's database access boundary.
SSM managed-host discovery and VPN discovery were denied, so an existing private
access path has not been established.

For this development/demo environment, the proposed starting point is a private
Single-AZ RDS PostgreSQL `db.t4g.micro`, encrypted 20-GiB general-purpose storage,
an RDS-managed master secret, and a separate limited application database role.
This is a proposal, not a provisioned or benchmarked configuration. Before
creation, verify supported engine/storage options, choose dedicated database
subnets/security groups, and establish laptop access through an existing private
connection or an SSM-managed tunnel host. A tunnel host requires its own role,
networking and costs. Never expose PostgreSQL publicly to solve laptop access.

AWS Price List API returned USD 0.016/hour for Single-AZ PostgreSQL
`db.t4g.micro` in N. Virginia on this date: USD 11.68 for 730 running hours,
**instance compute only**. Storage, secrets, backup overages, burst CPU, access
host/network costs, requests, taxes and credits are excluded. A complete estimate
and the exact available engine version remain pending discovery access.

## Next verification

1. Continue phase 3 fixture-based retrieval and S3 adapter implementation using
   the confirmed target. The S3 setup is available; the adapter still needs its
   bounded upload/readback, integrity and failure/retry tests.
2. When RDS/Cognito work resumes, attach the discovery policy and repeat the
   denied reads. Return only
   nonsecret app-client settings; `DescribeUserPoolClient` can contain a secret.
3. Finalize and provision the development RDS connection path and resource
   configuration; verify actual TLS/database connectivity and role separation.
   Cloud provisioning does not block real local PostgreSQL adapter tests.
4. Rehearse cloud adapters, durable publication, authorization and replacement
   recovery before marking phase 6 acceptance. ECS/sandbox/resource-budget
   decisions remain separate; this setup does not close them.
