# Tasks

- [x] Deliver portable candidate identity generation and pinned guest installation.
- [x] Deliver explicit API configuration and checked-in entry point.
- [x] Use dedicated Colima launch and actual Docker socket group discovery.
- [x] Document complete guided setup, configuration, review, run and recovery.
- [x] Verify controlled behavior, links, static checks and package build; record limits.

Verification: 1,429 controlled/unit/architecture/SQL compatibility tests passed;
one Linux O_PATH test skipped on macOS. After the final review-helper regression,
all 32 focused setup tests passed. Ruff lint/format, mypy (148 source files),
package build, guide shell syntax/local links, containment gate names and native/
Colima Make dry runs passed. Fresh VM provisioning, native parser/Docker runtime
acceptance, AWS and browser checks were not executed for this change. The guide
requires actual-host checks and preserves deferred capacity evidence.

User correction: require the existing Apple Silicon macOS/Colima environment.
Alternative guide routes and the native launcher option have been removed.

- [x] Expose guided Make stages for dependencies, runtime installation, candidate,
  actual-host validation, reports, named review, configuration and forwarding.
- [x] Enforce Apple Silicon/macOS and dedicated Colima transport; retain failure
  stops, committed source export, private settings and separate startup/review.
- [x] Verify orchestration with controlled tests and Make dry runs; shorten guide.
