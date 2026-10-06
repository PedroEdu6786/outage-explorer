# Parser readiness review packet

Status: numeric containment caps accepted by the user on October 6, 2026;
full report/configuration readiness review pending; no activation authorization.

The [candidate configuration](../../../infrastructure/analytical-worker/sql-inspection.candidate.json)
contains explicit Linux paths/hashes and bounds, with `evidence: null`.
[Native evidence](evidence/2026-10-06-linux-sql-parser-owner-loss.json) records
18 passing resource/lifecycle/owner-loss checks and matching code/executables.
Controlled checks also reject malformed/missing/mismatched reviews and unsafe
ownership. This file is a review packet, not an approved runtime record.

| Candidate setting | Value | Basis |
| --- | --- | --- |
| Wall-clock | 4 seconds | Explicit native test cap; not measured latency budget |
| CPU | 1 second | Real CPU-exhaustion test passed |
| Address space | 256 MiB | Real memory-exhaustion test passed; not measured peak |
| Termination | 1 second | Confirmed cancellation/process-group cleanup checks |
| Parser SQL / AST / depth | 65,536 bytes / 10,000 nodes / 64 | Existing inspection ceilings preserved |
| stderr / response | 1,024 bytes / fixed 1,024 bytes | Oversized outputs rejected; diagnostics suppressed |
| Admission | 1 slot | Concurrent owner and unresolved child ownership deny reuse |

Recommendation: review these as initial local acceptance caps while preserving
the ten-second analytical execution ceiling. They are candidate containment
settings and should not be described as measured resource budgets. The user accepted the four numeric containment caps for initial local acceptance.
This does not approve full readiness or claim measured production budgets. No
reviewer/date/report approval fields have been invented.

The exact candidate profile (`833fd37713f21542d3ffca7bb0d34d237441c7a145c4b35463deef1cc6649669`)
also passed start, constant-SQL inspection, close and confirmed lease/process
release at its configured ownership root on the Linux validation host. This
does not validate an independently selected serving host.

Before SQL activation: review reports and settings; validate the proposed private
ownership root on the actual serving host; create a matching review record from
actual approved report digests; pass the separate `--inspection-config` together
with a fully reviewed analytical runtime config. Both gates must pass before
startup, and endpoint enablement still needs separate direction. Mac hosts do
not support this native Linux launcher.

Other readiness remains open: sampler errors, representative preview, spill/
high-water, S3 cold-cache/transfer/storage, independently authorized API/refresh
overlap, live Cognito login and pooled IAM signing, original T1.7/T1.C and
T4.3/T4.C. No overlap workload, refresh/publication, deployment, cloud namespace,
credential transfer or API startup was created for these checks.
