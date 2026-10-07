.DEFAULT_GOAL := help

PYTHON ?= python3
HOST ?= 127.0.0.1
PORT ?= 8000
VENV_PYTHON := .venv/bin/python

START ?=
END ?=
CONFIG ?=
LOCAL_ONLY ?= 0
FETCH_WORKERS ?=
S3_WORKERS ?=
REVIEWER ?=
OPERATION ?=
RESOURCES ?=
PRIOR ?=
# With a config file, preserve its staging value unless explicitly overridden.
STAGING ?= $(if $(strip $(CONFIG)),,data/connector-local)
shell_quote = '$(subst ','"'"',$(1))'

.PHONY: help setup run run-analytical stop-analytical run-worker health connector connector-help test check check-env check-test-env test-postgres test-postgres-stop test-browser-setup

help:
	@printf '%s\n' \
	  'make local-help   Show the guided Colima setup commands' \
	  'make setup   Install the pinned dependencies in .venv' \
	  'make run     Start macOS Flask health/docs scaffold (preview/SQL unavailable)' \
	  'make run-analytical   Serve the configured Colima API with AWS credential renewal' \
	  'make stop-analytical  Stop the configured Colima API' \
	  'make run-worker   Run the independent refresh worker using .env' \
	  'make health  Call GET /health on the running API' \
	  'make connector START=YYYY-MM-DD END=YYYY-MM-DD   Build and verify a candidate in S3' \
	  'make connector CONFIG=path.json   Run with optional JSON configuration' \
	  'Connector overrides: STAGING=path PRIOR=path/to/report.json FETCH_WORKERS=3 S3_WORKERS=3' \
	  'make connector OPERATION=persist RESOURCES=path/to/report.json STAGING=path S3_WORKERS=3' \
	  'make connector LOCAL_ONLY=1 START=YYYY-MM-DD END=YYYY-MM-DD   Local only' \
	  'make connector-help   Show connector CLI options without running it' \
	  'make test    Run all tests' \
	  'make test-postgres   Start disposable Docker PostgreSQL on port 55439' \
	  'make test-browser-setup   Install controlled Chromium acceptance browser' \
	  'make check   Run lint, format, type, test, and build checks' \
	  'Overrides: make run PORT=8080; make setup PYTHON=python3.14'

# Manual local setup, always using the dedicated Colima outage-runtime guest.
LOCAL_STEPS := dependencies runtime candidate validate reports configure forward
.PHONY: local-help local-review $(addprefix local-,$(LOCAL_STEPS))
local-help:
	@printf '%s\n' \
	  '1. make local-dependencies       Install macOS tools (Homebrew required)' \
	  '2. make setup                    Install host Python dependencies' \
	  '3. make local-runtime            Create fresh Colima VM, install source/build image' \
	  '4. make local-candidate          Capture this host/image/parser identity' \
	  '5. make local-validate           Run actual-guest containment checks' \
	  '6. make local-reports            Inspect the check reports' \
	  '7. make local-review REVIEWER="Your name"  Explicitly accept local containment' \
	  '8. make local-configure          Install reviewed API settings from .env' \
	  '9. make run-analytical           Start API (separate terminal)' \
	  '10. make local-forward           Forward API port (separate terminal)' \
	  'Then npm run dev in the sibling web checkout; see docs/development/fresh-machine.md.' \
	  'Runtime is fresh-install only. Configure AWS login and .env before configuration.' \
	  'Command details: docs/development/local-commands.md'

$(addprefix local-,$(LOCAL_STEPS)):
	$(PYTHON) scripts/local_machine.py $(patsubst local-%,%,$@)

local-configure: check-env

local-review:
	$(PYTHON) scripts/local_machine.py review --reviewer $(call shell_quote,$(REVIEWER))


$(VENV_PYTHON):
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ required. Try: make setup PYTHON=python3.14")'
	$(PYTHON) -m venv .venv

setup: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt
	$(VENV_PYTHON) -m pip install --no-deps --no-build-isolation -e .
	$(VENV_PYTHON) -m pip check

check-env:
	@test -x .venv/bin/flask || { printf '%s\n' 'Run make setup first.'; exit 1; }

run: check-env
	@printf '%s\n' 'This Flask startup has no preview/SQL execution resources. For the configured local runtime, use make run-analytical.'
	$(VENV_PYTHON) -m flask --app outage_explorer.entrypoints.http.startup:create_app run --host $(HOST) --port $(PORT)

# Uses the explicitly provisioned/reviewed local service. Never falls back to Flask.
run-analytical: check-env
	$(VENV_PYTHON) scripts/local_analytical.py

# Independent refresh process; it only claims runs an Admin has admitted.
run-worker: check-env
	$(VENV_PYTHON) scripts/run_worker.py

stop-analytical:
	colima ssh --profile outage-runtime -- sudo systemctl stop outage-api-local

health:
	curl --fail --silent --show-error --include http://$(HOST):$(PORT)/health

connector: check-env
	$(VENV_PYTHON) -m outage_explorer.entrypoints.cli.connector_startup \
	  $(if $(CONFIG),--config $(call shell_quote,$(CONFIG))) \
	  $(if $(START),--start $(call shell_quote,$(START))) \
	  $(if $(END),--end $(call shell_quote,$(END))) \
	  $(if $(STAGING),--staging $(call shell_quote,$(STAGING))) \
	  $(if $(PRIOR),--prior $(call shell_quote,$(PRIOR))) \
	  $(if $(FETCH_WORKERS),--fetch-workers $(call shell_quote,$(FETCH_WORKERS))) \
	  $(if $(S3_WORKERS),--s3-workers $(call shell_quote,$(S3_WORKERS))) \
	  $(if $(OPERATION),--operation $(call shell_quote,$(OPERATION))) \
	  $(if $(RESOURCES),--resources $(call shell_quote,$(RESOURCES))) \
	  $(if $(filter 1,$(LOCAL_ONLY)),--local-only)

connector-help: check-env
	$(VENV_PYTHON) -m outage_explorer.entrypoints.cli.connector_startup --help

test-postgres:
	docker run --rm --detach --name outage-explorer-test-postgres -e POSTGRES_USER=outage_test -e POSTGRES_PASSWORD=controlled-test-only -e POSTGRES_DB=postgres -p 127.0.0.1:55439:5432 postgres:18
	@printf '%s\n' "export OUTAGE_TEST_POSTGRES_DSN='host=127.0.0.1 port=55439 dbname=postgres user=outage_test password=controlled-test-only sslmode=disable'"
	@printf '%s\n' 'Wait for docker exec outage-explorer-test-postgres pg_isready -U outage_test -d postgres to pass.'

test-postgres-stop:
	docker stop outage-explorer-test-postgres

test-browser-setup: check-env
	$(VENV_PYTHON) -m playwright install chromium

check-test-env: check-env
	@$(VENV_PYTHON) -c 'import os,sys; sys.exit(0 if os.environ.get("OUTAGE_TEST_POSTGRES_DSN") else "Required tests need OUTAGE_TEST_POSTGRES_DSN for disposable loopback PostgreSQL; see make test-postgres.")'
	@$(VENV_PYTHON) -c 'from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); installed=Path(p.chromium.executable_path).is_file(); p.stop(); assert installed, "Required browser missing; run make test-browser-setup."'

test: check-test-env
	$(VENV_PYTHON) -m pytest -m 'not live_provider'

check: check-test-env
	$(VENV_PYTHON) -m pip check
	$(VENV_PYTHON) -m ruff check .
	$(VENV_PYTHON) -m ruff format --check .
	$(VENV_PYTHON) -m mypy
	$(VENV_PYTHON) -m pytest -m 'not live_provider'
	$(VENV_PYTHON) -m build --no-isolation
