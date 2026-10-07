# Tests and quality checks

[Back to README](../../README.md)


The full backend checks need disposable PostgreSQL and Chromium. From the
backend checkout, with Docker running:

```sh
make setup
make test-postgres
# Continue after this reports that PostgreSQL is accepting connections:
docker exec outage-explorer-test-postgres pg_isready -U outage_test -d postgres
export OUTAGE_TEST_POSTGRES_DSN='host=127.0.0.1 port=55439 dbname=postgres user=outage_test password=controlled-test-only sslmode=disable'
make test-browser-setup
make check
make test-postgres-stop
```

`make check` runs dependency checks, Ruff lint/format, strict mypy, pytest and
package builds. `make test` runs the test suite alone. Required tests use
controlled providers and a disposable database; live-provider tests are excluded.
CI configures Python 3.12/3.14, PostgreSQL and Chromium.

In the web checkout:

```sh
npm run typecheck
npm run lint
npm test
npm run build
```

Its README documents additional boundary and browser checks.

