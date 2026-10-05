# Connector AWS setup

Status: **S3 development setup verified; Cognito setup and RDS connection
completed per user confirmation on October 3, 2026**.
Earlier AWS observations below used the `outage-explorer` profile. The user's
later confirmation supersedes the earlier RDS/Cognito deferral and empty regional
inventory; no new agent-run RDS/Cognito check is claimed.

Development runs locally with the configured resources. EC2 replaces ECS as the
deployment target under [ADR-0038](../../adr/0038-ec2-deployment-local-development.md).
No EC2 instance is required for local development, and deployment choices do not
block local connector implementation or testing. Application integration and
runtime acceptance remain separate from resource setup completion.

## Confirmed target

| Setting | Value |
| --- | --- |
| Account | `[REDACTED AWS account]` |
| Local AWS profile | `outage-explorer` |
| Verified IAM principal | `[REDACTED IAM principal]` |
| Region | `us-east-1` |
| S3 bucket | `arkham-outage-explorer` |
| S3 prefix | `data/` — user confirmed, no leading slash |
| Cognito pool/app client | Setup completed per user; identifiers remain in local configuration |
| RDS connection | Completed per user; connection settings and secrets remain local |

The nonsecret S3 target values are in `.env.example` and the local ignored `.env`.
Use the current local Cognito configuration; do not reconstruct the previously
removed pool identifier from historical context.
Default connector CLI runs and explicit Phase 5 persist/recover operations now
consume these S3 settings (ADR-0042); `--local-only` opts out of AWS.
its configured-bucket checks remain separate from historical setup probes.
`AWS_PROFILE` is for local development; deployed application/refresh processes should receive their
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
It does not prove the future deployed role's permissions, production adapter
verification, multipart behavior, or publication/recovery correctness. Versioning
alone does not prevent overwrites; the adapter must use conditional creation and
verify same-key retries. No bucket policy enforces that requirement currently.
Retain the accepted published-data retention behavior: do not introduce expiration
or authoritative-object cleanup as part of connector implementation.

See [AWS conditional-write behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

## Historical RDS/Cognito discovery limitations

These earlier denials are retained as evidence, not current setup blockers.
The user subsequently completed setup; policy attachment is not a prerequisite
for local implementation. Revisit discovery access only if a specific task needs it.

The current principal received `AccessDenied` for:

- `cognito-idp:DescribeUserPool` and `cognito-idp:ListUserPoolClients` on the
  supplied pool. Its existence/configuration and intended app client are unverified.
- `rds:DescribeDBEngineVersions` and `rds:DescribeOrderableDBInstanceOptions`.

An account administrator can attach
[`infra/aws/setup-discovery-policy.json`](../../../infra/aws/setup-discovery-policy.json)
as an inline policy named `OutageExplorerSetupDiscovery` to `[REDACTED IAM user]`:
IAM → Users → [REDACTED IAM user] → Add permissions → Create inline policy → JSON.
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

## Historical RDS preparation proposal

The following inventory and sizing proposal predate the user's completed RDS
connection. They do not describe the current resource or request a second database.

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

1. Continue from the implemented fixture-tested EIA source adapter to durable
   refresh and S3 integration using the confirmed target. The S3 adapter still
   has controlled bounded upload/readback, integrity and failure/retry tests;
   configured-bucket verification remains separately authorized.
2. Implement and test application adapters against the configured services,
   including verified TLS, database role separation, token/session mapping and
   application-owned permissions. Setup completion does not prove these behaviors.
3. Continue local development without EC2. Plan deployed connectivity, supervision,
   IAM access and resource bounds separately when preparing EC2 deployment.
4. Rehearse cloud adapters, durable publication, authorization and replacement
   recovery before marking phase 6 acceptance. EC2/sandbox/resource-budget
   decisions remain separate; this setup does not close them.

## Phase 5 follow-up: configured-bucket connector checks

These are **not executed Phase 5 evidence**. Phase 6 requires separate explicit
authorization for configured-bucket reads/writes and live EIA retrieval. This
page describes checks against an existing configured target; it provisions
nothing and selects no deployment, lifecycle, versioning or retention policy.

Configure `OUTAGE_S3_BUCKET`, `OUTAGE_S3_PREFIX` (nonempty relative prefix ending
in `/`) and `AWS_REGION`. Local `AWS_PROFILE` selects the credential provider;
otherwise the SDK resolves credentials, including workload roles. Supply
credentials outside the repository. `.env.example` is a template and is not
automatically loaded. No caller endpoint/URL or CLI credential flag is accepted.
The provider needs `s3:PutObject` and `s3:GetObject` for the configured prefix,
plus any encryption permissions required by the existing bucket configuration.
No bucket-list, delete, provisioning or retention permissions are required by
the adapter. Role connectivity and bucket encryption policy remain to verify.

After authorization, use a bounded **verified** local candidate and its exact
manifest reference. Record effective artifact/model limits, SDK versions,
configured bucket/prefix, date, credential-provider kind (no credential values),
object count/bytes, returned receipts and sanitized failure outcomes.

1. Persist the complete graph with the README command. Confirm every physical
   key lies under the configured prefix and all dependency verification finishes
   before the final manifest is written. Record full fresh readback/replay success.
2. Repeat persistence with the same reference; confirm identical bytes are
   verified, without replacing objects. For precondition/conflict fault checks,
   use isolated authorized test objects and controlled competing writes. Do not
   mutate or delete authoritative artifacts to simulate corruption.
3. Use a new empty local staging path, unset `EIA_API_KEY` and forbid EIA egress.
   Recover by the saved exact reference with the same target configuration.
   Compare manifests, per-grain exact values/origins/quality and source replay.
4. Repeat recovery in another empty path after application/local staging
   replacement. Test missing/corrupt/partial graph failures through controlled
   SDK tests, or separately authorized isolated test fixtures; never delete
   published snapshots or pinned findings inputs. Record limitations and failures.

These checks establish configured-target storage behavior only. Initial live
loading still uses April 2–October 1, 2026 inclusive and requires verified usable
output in all three grains, measured resource budgets and contract applicability.
Backend activation, PostgreSQL outcomes/uncertain commit reconciliation,
authorization, reader pinning, runtime supervision and deployed EC2 role access
remain separate work. No connector receipt says that data was published.

## Phase 6 configured-bucket evidence — October 4, 2026

User-authorized bounded contributor checks against the existing bucket/prefix
passed conditional persistence, full readback/replay and EIA-disabled empty-staging
reconstruction in sequential and three-worker modes. Exact references, graph
sizes, durations and distinctions between new uploads and identical retries are
in [recovery verification](recovery-verification.md) and
[resource evidence](resource-evidence.md). Clients used the existing local credential
provider; no credentials are recorded. No bucket configuration, role, publication
reference or retained object was modified/deleted. Deployed-role permissions,
EC2 runtime and durable backend outcomes remain unverified.

October4 final initial gate: GET-only exact-reference CLI recovery with3 S3 workers
against the existing configured bucket/profile passed for
`f74027258fdbf78ba040128b4761166c15249177365df4eba7db1bd5f5232cd0:563052`:
2054objects/63,420,955bytes with full source-disabled semantic replay. No PUT,
object deletion or infrastructure change was performed for this closure.
See [recovery evidence](recovery-verification.md) and
[tracked measurement](evidence/2026-10-04/initial-interval-recovery.json).
