# Local protocol-v2 upgrade candidate

Date: 2026-10-07. **Activated locally after explicit user review.**

The candidate preparation below records the pre-activation state. See the
activation record at the end for the current state.

The running local API uses the installed package inside the Colima
`outage-runtime` guest, not this checkout. Its catalog lacks facility and its
worker protocol is 1. Restarting `make run-analytical` reloads that installed
copy; it does not export source, install a package or rebuild the worker image.
The public running OpenAPI also lacks the facility preview parameter.

Prepared from backend source revision `ff53787`:

- New backend wheel and immutable Linux worker image
  `sha256:a29b0629d4d6e4b16f4c6c0c3943e717d71b9e127ecfaa38f6f1f5602f4419d9`.
- Separate candidate profile, identity
  `fba95355d4f9c459767347db638248bd4f4e5b168163a23dfd207b68b823e58d`.
- Current bounded worker/response/profile checks: **143 passed** in the guest.
- Actual Docker isolation, termination, ownership and quota checks: **19 passed**;
  one representative-measurement case deselected.
- Six real Docker filtered-preview cases: both detail grains with leading-zero,
  quoted and unmatched IDs, inclusive dates and ordered continuation.

The first native run passed 18 cases and failed one because its synthetic fixture
still used the obsolete public-only Parquet layout. The corrected fixture builds
the accepted unified resource, including private provenance; the rerun passed all
19. This fixture correction changes tests only, not the image's product source.
Both attempts' individual reports are preserved in the
[candidate evidence](evidence/2026-10-07-runtime-v2-candidate.json), SHA-256
`eec75f33dd81129405388a3febd49289ce40dcb9c63a9a02b8959f8d76931e4e`.

The existing API was stopped only for synthetic native checks and restored to
its previous package/image afterward. The previous installed package, active
runtime configuration and image remain available for rollback. No Cognito, RDS,
S3, browser, refresh or publication probes ran. Representative high-water/spill,
S3 performance, API/refresh overlap and production acceptance remain open. The
candidate bundle records synthetic functional/resource observations, not new
representative performance measurements.

[ADR-0055](../../adr/0055-scoped-local-analytical-readiness.md) requires:
“User review must accept actual matching reports and initial containment limits”.
The candidate remains unreviewed; no approval metadata or runtime gate was
bypassed. Activation requires that review, then installation of the matching
wheel/profile and an API restart. An activation script has been prepared with
package/config rollback if the public local contract check fails; it has not run.

## Activation record

The user explicitly approved: “Approve and activate locally”. The reviewed
matching wheel, immutable image and profile above are now active. Acceptance
remains `local-preview-sql`; broader runtime and production gaps remain open.

The first activation attempt failed startup and automatically restored the
previous package and runtime configuration. Diagnosis found a second stale-code
source: `/run/outage-api/environment.json` set `PYTHONPATH` to
`/opt/outage-runtime-validation/src`, overriding the installed wheel. Removing
that override allowed the matching installed package to load. The original
environment, package, runtime configuration and image remain available for
rollback in the guest candidate directory; private environment contents are
not included in this report.

After the successful retry, an actual loopback HTTP request to the running API's
OpenAPI contract returned preview parameters `start_date`, `end_date`, and
`facility`. Guest import verification resolved the catalog to the installed
`site-packages` module, confirmed facility support in that module, and reported
worker protocol 2. The exact active profile/image identities match the reviewed
candidate. No authenticated catalog or live analytical data request was made.

No data refresh, publication change, browser check, or external-service probe
was performed. Reload the web application to retrieve updated catalog metadata;
refreshing dataset data is unnecessary for this code/configuration update.
