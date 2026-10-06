# Parser readiness review packet

Status: numeric containment caps accepted by the user on October 6, 2026;
full report/configuration readiness review pending; no activation authorization.

The [candidate configuration](../../../infrastructure/analytical-worker/sql-inspection.candidate.json)
contains explicit Linux paths/hashes and bounds, with `evidence: null`.
[Native evidence](evidence/2026-10-06-linux-sql-parser-owner-loss.json) records
18 passing resource/lifecycle/owner-loss checks and matching code/executables.
[Controlled evidence](evidence/2026-10-06-parser-controlled-review.json) records
102 passing parser/configuration checks, including malformed/missing/mismatched
reviews and unsafe ownership. Current parser source hashes still match the
18-check native owner-loss record. This is a review packet, not an approved runtime record.

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
The [path/cap record](evidence/2026-10-06-parser-candidate-path-check.json) records
that narrower result and the user's numeric-cap acceptance.

Matching review digests, ready for the user's substantive review:

- Controlled: `31d4637a5ee8d2d1fe4e6173af903ea3d94b85ecd79561ec38c7d50b1a6c4e36`.
- Native owner loss: `af23d5a9009fcf1a40e858aeaf75edd0edf0beef746313386f5c6560bc8ebcda`.
- Path/cap follow-up: `21041e66d7b371b2300f4cd9ce8b789491acfd947f051bd14bee1ff740524de9`.

Recommendation: approve the matching parser configuration/reports for initial
acceptance on this recorded Linux host, retaining full analytical readiness and
activation as separate gates. Candidate `evidence` remains null until that
explicit report/profile review is accepted.

Before SQL activation: review reports and settings; validate the proposed private
ownership root on the actual serving host; create a matching review record from
actual approved report digests; pass the separate `--inspection-config` together
with a fully reviewed analytical runtime config. Both gates must pass before
startup, and endpoint enablement still needs separate direction. Mac hosts do
not support this native Linux launcher.

Representative preview and local resource observations now pass; see the
[analytical record](evidence/2026-10-06-preview-sql-local-resource-observations.json).
It contains 27 previews, six SQL executions, three result-page reads and memory
observations for all 33 containers: 301 samples, zero failed samples and one
explicit read crossing confirmed removal. Historical failed reports remain intact.
This is sampled evidence, not complete high-water or reviewed budgets.

Other readiness remains open: spill/high-water, S3 cold-cache/transfer/storage,
independently authorized API/refresh
overlap, live Cognito login and pooled IAM signing, original T1.7/T1.C and
T4.3/T4.C. No overlap workload, refresh/publication, deployment, cloud namespace,
credential transfer or API startup was created for these checks.
