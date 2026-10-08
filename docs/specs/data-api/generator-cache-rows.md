# Generator preview row-cap correction

Date: 2026-10-08. Source fix verified; local runtime candidate awaits review and
activation. No running API/package/profile or publication was changed.

The running API repeatedly returned HTTP 422 for generator previews. Read-only
publication metadata showed 32,395 generator rows (18,203,015 bytes), versus
18,755 facility rows and 341 national rows. Bootstrap passed a hard-coded 30,000
row ceiling to `VerifiedResourceCache`. The cache rejects the complete resource
descriptor before downloading or executing a preview, regardless of page size,
date selection or facility filter. The public error maps this preparation failure
to `query_resource_limit`, obscuring which limit failed.

Bootstrap now takes `cache_rows` from `RuntimeProfile`. It remains a finite,
positive integer, defaults to the existing 30,000 ceiling and participates in the
profile digest. The [candidate](generator-cache-rows.candidate.json) explicitly
sets 100,000 rows, matching the connector's default modeled-output row allowance.
This does not guarantee admission of every 100,000-row resource: file/byte,
preparation, memory and all other independent bounds still apply. The page size,
10-second execution cap, 128 MiB engine memory, 512 MiB container memory, exact
file verification and single execution slot are unchanged.

Adding the field changes the canonical profile identity even when omitted in an
old JSON file. Existing review digests must not be copied to the new profile.
The candidate retains `evidence: null`; it cannot start until reviewed.

## Verification

- Regression reproduces rejection of a synthetic 32,395-row unified generator
  resource under the old cap, then verifies first and continuation pages under
  the proposed cap without duplicate/skipped IDs. Resources above the configured
  ceiling are still refused before a source read.
- Production composition tests verify both rejection and admission using the
  configured ceiling. Profile tests reject malformed limits and stale evidence.
- Focused cache, preview, runtime composition/configuration and architecture
  suites: **260 passed, 31 skipped**. The skipped cases require configured
  disposable PostgreSQL; they are not new live authorization evidence.
- Repository Ruff lint/format passed; strict mypy passed for 149 source files;
  wheel build and `git diff --check` passed.
- A separate read-only diagnostic, running as the API's Linux UID, prepared the
  exact current published generator object with `cache_rows=100000` using the
  existing cache/S3 adapters and the same 30-second bound. First attempt reached
  the bound at **30.005 seconds**. An instrumented retry passed: download
  **17.906 seconds**, verification **0.470 seconds**, total **18.413 seconds**.
  Both outcomes matter: the row-cap fix removes the deterministic rejection;
  variable cold-download time can still exhaust the existing deadline. Earlier
  diagnostic-runner attempts failed before data preparation because of working
  directory/stdin multiprocessing setup; they do not measure product performance.
- No new isolated worker execution or authenticated HTTP preview was performed.
  Existing immutable protocol-v2 worker image is unchanged. Prior native worker
  evidence remains historical; this is not a new full capacity acceptance.

## Reviewable artifacts and activation

- Candidate profile identity:
  `0eca402e19a9c878e42c80dcc6a431c3b194180761cff5527f647acae00a73a6`.
- Existing worker image:
  `sha256:a29b0629d4d6e4b16f4c6c0c3943e717d71b9e127ecfaa38f6f1f5602f4419d9`.
- Prepared wheel:
  `/private/tmp/outage-generator-cap-candidate/outage_explorer-0.1.0-py3-none-any.whl`.
  SHA-256: `c2fda7fc561fed2a7b5389ac2b2844bac18b47b39c7843bf14f4fada3edaba6a`.

[ADR-0055](../../adr/0055-scoped-local-analytical-readiness.md) requires user
review of actual reports and changed containment limits. Approval would accept
this explicit 100,000-row local candidate and its stated evidence limits, then
permit installing the prepared backend wheel and reviewed profile and restarting
the local API. Back up the installed package and profile first; restore both on
startup failure. The worker image needs no code change. Keep refresh idle and
publication history intact. The runtime uses its installed guest package, so
restarting it alone does not install this source fix.
