.DEFAULT_GOAL := help

PYTHON ?= python3
HOST ?= 127.0.0.1
PORT ?= 8000
VENV_PYTHON := .venv/bin/python

.PHONY: help setup run health test check check-env

help:
	@printf '%s\n' \
	  'make setup   Install the pinned dependencies in .venv' \
	  'make run     Start the local API at http://127.0.0.1:8000' \
	  'make health  Call GET /health on the running API' \
	  'make test    Run all tests' \
	  'make check   Run lint, format, type, test, and build checks' \
	  'Overrides: make run PORT=8080; make setup PYTHON=python3.14'

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
	$(VENV_PYTHON) -m flask --app outage_explorer.entrypoints.http.startup:create_app run --host $(HOST) --port $(PORT)

health:
	curl --fail --silent --show-error --include http://$(HOST):$(PORT)/health

test: check-env
	$(VENV_PYTHON) -m pytest

check: check-env
	$(VENV_PYTHON) -m pip check
	$(VENV_PYTHON) -m ruff check .
	$(VENV_PYTHON) -m ruff format --check .
	$(VENV_PYTHON) -m mypy
	$(VENV_PYTHON) -m pytest
	$(VENV_PYTHON) -m build --no-isolation
