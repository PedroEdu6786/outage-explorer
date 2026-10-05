# User-access verification

Date: **2026-10-05**. Phase 5 controlled verification and live readiness are
separate gates. **T5.14 and T5.C remain incomplete** until the required real
managed-login and browser evidence passes. The user selected completing
controlled tests while leaving real validation pending during this run.

## Read-only live readiness

Actual command: `.venv/bin/python /private/tmp/outage-phase5-readonly.py`.
This temporary operator probe loaded the existing local `.env` and process
environment without printing values, called AWS STS `GetCallerIdentity`, Cognito
`DescribeUserPool`, `DescribeUserPoolClient`, and `AdminGetUser`, and connected
directly with Psycopg using a freshly signed IAM token. It read tables within
`SET TRANSACTION READ ONLY`, with a five-second statement timeout and explicit
rollback. No migration, seed, grant, cloud provisioning or password change ran.
The temporary script is local operator evidence, not a shipped repository command;
use the [setup runbook](setup.md) for repeatable configuration and setup commands.

The sandbox attempt failed with `EndpointConnectionError`/`OperationalError`;
the approved network-enabled rerun completed. Final probe timestamp:
**2026-10-05T07:22:26.882175+00:00**.

| Read | Actual result |
| --- | --- |
| Retained AWS profile | `outage-explorer` resolves to **root**. The profile was preserved; no identity replacement ran. |
| PostgreSQL connection | Server 17.9, database `outage-explorer-db`, runtime role `outage_app`, fresh IAM token, `verify-full` TLS and encrypted connection. This direct connection is not evidence of deployed application pooling. |
| Access schema | Runtime-visible `roles`, `users`, `application_sessions`, and `login_attempts` are present. |
| Trusted seeds | Three users and `admin`, `analyst`, `viewer` roles; exactly one user per role. The complete stored issuer/subject/email/role set equals all three trusted manifest records from `/private/tmp/outage-user-access-seed.json`. No email or subject values were emitted. |
| Essential local user fields | `id`, `identity_issuer`, `identity_subject`, `email`, `role_code`; no credential field. |
| Cognito pool/client | Email login enabled, self-registration disabled, managed domain configured, authorization-code flow enabled, confidential client secret present, one registered callback, configured scopes `email`, `openid`, `phone`. Secret content was never emitted or copied into runtime settings. |
| Cognito personas | All three enabled; trusted subject and email match the manifest. All three remain **`FORCE_CHANGE_PASSWORD`**. |

The existing `.env` retains obsolete `PGUSER=master` and
`PGDATABASE=outage_explorer`; a first probe using those values failed with
`OperationalError`. The successful probe explicitly selected the documented
application database and runtime role above. These local settings were not edited.
An attempted migration-revision read as `outage_app` returned
`InsufficientPrivilege`; it was removed from the runtime-only probe. No privileges
were broadened, and migration revision is not newly revalidated by these reads.

## Controlled implementation evidence

Implementation and controlled verification ran on local **Python 3.14.6**, with
Psycopg pool 3.3.3, Playwright 1.63.0 and Chromium revision 1243. The existing
disposable PostgreSQL 18.6 instance under `/private/tmp/outage-access-pg/data`
listens on **5432**; the historical 55439 target failed with connection refusal.
The test DSN explicitly selected loopback, `postgres`, local user `PECRUZ` and
`sslmode=disable`. Only randomly named disposable test databases were created,
migrated/seeded and dropped; no RDS writes ran. Local TCP/browser process tests
needed approved execution outside sandbox network restrictions.

Actual commands/results:

- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: passed, 277 files already formatted.
- `.venv/bin/mypy`: passed, 91 source files.
- `.venv/bin/python -m pip check`: passed, no broken requirements.
- `.venv/bin/python -m build --no-isolation`: built
  `outage_explorer-0.1.0.tar.gz` and `outage_explorer-0.1.0-py3-none-any.whl`.
- `git diff --check`: passed.
- Phase-specific PostgreSQL/HTTP/provider/IAM/settings/startup/schema/helper and
  browser suite: **159 passed**, no skips, before the extra physical-reconnect,
  SDK and negative-import cases were added.
- Final command (2026-10-05, complete by 07:37:44 UTC):

  ```sh
  PLAYWRIGHT_BROWSERS_PATH=/private/tmp/outage-web-playwright \
  OUTAGE_TEST_POSTGRES_DSN='host=127.0.0.1 port=5432 dbname=postgres user=PECRUZ sslmode=disable' \
  .venv/bin/python -m pytest -m 'not live_provider' -q --tb=short
  ```

  **1381 passed, 17 subtests passed, zero skips**, in 83.40 seconds. This includes
  the architecture negative fixtures, all PostgreSQL/HTTP/provider/IAM tests and
  actual persistent Chromium browser acceptance, plus concurrent repository work.

The first full suite found one overly strict new reconnect assertion: pool
replacement and waiting-request growth can legitimately create two physical
connections. The test was corrected to assert fresh signing for every recorded
physical attempt, rather than assuming exactly one replacement. Its fixed
application expiry and single provider-exchange checks already passed. The final
suite includes this correction. Required database/browser setup now fails clearly
rather than silently skipping; CI provisions PostgreSQL 18 and Chromium on Python
3.12/3.14 without cloud credentials. No remote CI run or local Python 3.12 run is
claimed; that interpreter is unavailable locally.

### Acceptance reconciliation

| Criterion | Controlled/read-only evidence | Required live portion |
| --- | --- | --- |
| AC1 | Disposable seeding plus read-only exact three-persona live manifest match | Revalidated seeded state |
| AC2 | Each persona completes verified confidential-provider PKCE callback with PostgreSQL session | Real email login/password completion pending |
| AC3 | PostgreSQL constraints, shared-role tests, live one-persona-per-role reads | Revalidated role bindings |
| AC4 | HTTP session identity/current role for all three personas | Real managed-login session pending |
| AC5 | Unlinked/unknown/unassigned identities deny, no session/protected work | Controlled complete |
| AC6 | Provider admin groups/role claims cannot override current local role | Controlled complete |
| AC7 | Viewer national-only matrix on direct and later-page use-case calls | Downstream feature integration remains separate |
| AC8 | Analyst/Admin all-grain direct/later-page matrix | Downstream feature integration remains separate |
| AC9 | Admin refresh-initiation authorization seam | Actual refresh implementation outside auth scope |
| AC10 | Admin outcome/diagnostic authorization seams | Actual refresh implementation outside auth scope |
| AC11 | Non-Admin/invalid-session refresh denial before protected spy work | Actual refresh integration remains separate |
| AC12 | Typed guards deny early; retained helper identity cannot bypass fresh PostgreSQL role check; direct/later-page spies deny before work | Feature-specific reference/result-owner checks remain downstream |
| AC13 | Default lease exactly establishment plus one hour in PostgreSQL and HTTP | Real managed-login lease pending |
| AC14 | Activity, persistent profile reopening and IAM reconnection after virtual 901 seconds preserve expiry; provider exchange never renews | Real-provider browser activity pending |
| AC15 | Real Chromium persistent profile closes/reopens with unchanged valid sign-in and expiry | Real managed-login profile reopening pending |
| AC16 | Controlled server clock exact expiry denies a still-present browser cookie | Real-provider expired session pending |
| AC17 | Committed logout, old-cookie replay and revoked profile reopening deny | Real-provider logout pending |
| AC18 | Independently signed-in PostgreSQL sessions/browser profiles survive another session's logout | Real-provider independent sessions pending |
| AC19 | Wrong confidential secret, invalid grant/code/token/identity and malformed input return sanitized generic errors without fallback/leaks | Managed-login invalid-email/password presentation pending |
| AC20 | Denial JSON excludes protected data and exception/credential values | Controlled complete |
| AC21 | Essential user-field schema, trusted manifest allowlist, no duplicated credential/token store; live schema read | Read-only schema revalidated |
| AC22 | Auth-only PostgreSQL/provider/HTTP/browser/IAM acceptance requires no connector/S3/analytical data/EC2/UI | Controlled complete |

The IAM adapter tests also exercise bounded failed/blocked lookup, controlled SDK
signing inputs, fresh tokens and retry/concurrent physical creation, unchanged
shared DSN, no signing on existing checkout, generic pool logs and fork denial.
Fresh-interpreter import/factory/help tests reject network, credentials, processes,
connections and threads before explicit runtime work. Negative architecture
fixtures cover IAM infrastructure and Flask/helper leakage without widening the
existing startup exception. Controlled setup uses the shared IAM configuration
without Cognito and signs separately for explicit migration, seed and cleanup.

## Initial live acceptance blockers (before subsequent configuration)

At the initial controlled checkpoint, runtime authentication was not configured in the available local `.env`/process
environment: auth opt-in, exact public callback/backend/UI origins and allowed
return paths, runtime provider domain/scopes and securely supplied client secret
are missing. Pool/client identifiers and existing cloud configuration do not
substitute for exporting these application settings. Persona password access and
first-login completion are also unavailable; the read-only account statuses prove
that required password changes remain outstanding.

The following checks **had not run at that checkpoint**:

- Real managed email login for Viewer, Analyst and Admin, including required
  first-login password changes and generic invalid-credential messaging.
- Real provider callback and application identity/session responses with the
  configured runtime origins, client secret and cookie transport.
- Real application logout, old-cookie replay denial, exact expiry, persistent
  browser reopening with unchanged expiry, and independent concurrent sessions.

These omissions keep AC2 and provider-side AC19, the live portions of
AC4/AC13–AC18, T5.14, T5.C and overall phase completion pending. Controlled
browser/provider tests cannot close these live gates. Existing account and schema
reads establish readiness inputs only, not successful authentication.

Catalog/preview/SQL/result/refresh endpoint implementation, actual SQL-reference
extraction and result ownership remain downstream feature responsibilities.
Auth seam checks do not assert authorization of absent product operations.
EC2 provisioning, deployment, connector completion and analytical data are not
prerequisites for the independent user-access test harness.

## Subsequent local authentication and web integration — 2026-10-05

The user subsequently confirmed: **auth module fully completed and integrated
in the web client**. Record this as user acceptance of the integrated behavior;
no additional automated or comprehensive live test run is implied.

- Local ignored configuration was populated with explicit IAM database settings,
  existing confidential-client settings, localhost callback and frontend origin.
  No secret or actual persona identifier is included in this evidence.
- Read-only Cognito checks verified that the localhost callback is registered
  and selected as default, all three personas are enabled and `CONFIRMED`, and
  the configured issuer/domain/client secret/scopes match provider metadata.
- IAM signing, read-only PostgreSQL access, required runtime table privileges
  and application-pool checks passed. Login admission returned `302` to Cognito.
- The user supplied a successful real Viewer session response with role and
  fixed expiry. Personal identifiers and CSRF values are deliberately omitted.
- The user reported logout `204`, followed by `401 unauthenticated` with the
  prior session. An initial Origin/CSRF rejection was corrected before success.
- The user confirmed login and frontend redirection work as expected, registered
  the frontend sign-out URL in Cognito, and later confirmed the complete auth
  integration. Cognito browser logout was handed off to the web client; its
  exact implementation and provider-cookie clearing were not independently
  rerun in this backend session.

The earlier missing configuration, initial-password and untested Viewer
login/logout statements are historical and are superseded by these observations.
No separate detailed results for real Admin/Analyst login, managed-login invalid
credentials, fixed expiry/reopening and independent live sessions were supplied.
Keep T5.14/T5.C open for that evidence; they do not identify additional auth
implementation required by the user's integrated-module confirmation.
