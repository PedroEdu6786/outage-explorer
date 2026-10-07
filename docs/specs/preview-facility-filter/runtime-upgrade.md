# Local protocol-v2 upgrade candidate

Date: 2026-10-07. **Prepared; user review and activation pending.**

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
