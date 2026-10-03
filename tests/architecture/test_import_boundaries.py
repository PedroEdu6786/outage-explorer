from pathlib import Path

import pytest

from .import_rules import CLI_STARTUP_SOURCE, CLI_WRAPPERS, STARTUP_SOURCE, violations


def source_tree(tmp_path, files):
    root = tmp_path / "outage_explorer"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def test_application_obeys_import_boundaries():
    root = Path(__file__).resolve().parents[2] / "src" / "outage_explorer"
    assert list(root.rglob("*.py")), "The architecture check must inspect real source"
    assert violations(root) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "domain/policy.py",
            "from outage_explorer.application.dto import HealthStatus",
        ),
        ("domain/policy.py", "from ..application.dto import HealthStatus"),
        ("domain/policy.py", "from flask import request"),
        ("domain/policy.py", "import pathlib"),
        ("domain/policy.py", "reader = open"),
        ("application/services/bad.py", "import outage_explorer.infrastructure.clock"),
        ("application/services/bad.py", "from ...infrastructure import clock"),
        ("application/services/bad.py", "from outage_explorer import settings"),
        ("application/services/bad.py", "from flask import current_app"),
        ("application/services/bad.py", "import sqlite3"),
        ("application/services/bad.py", "import psycopg"),
        ("application/services/bad.py", "import boto3"),
        ("application/services/bad.py", "from outage_explorer import helper"),
        ("application/services/bad.py", "from ..dto import *"),
        ("application/services/bad.py", "import importlib as loader"),
        ("application/services/bad.py", "load = __import__"),
        ("infrastructure/bad.py", "from ..application.services import health"),
        ("infrastructure/bad.py", "from ..entrypoints.http.app import create_app"),
        (
            "entrypoints/http/routes/bad.py",
            "from ....infrastructure.clock import SystemClock",
        ),
        ("entrypoints/http/routes/bad.py", "from ....domain import policy"),
        ("entrypoints/http/routes/bad.py", "from ....bootstrap import build_http_app"),
        ("entrypoints/http/routes/bad.py", "from ..startup import create_app"),
        ("entrypoints/http/routes/bad.py", "import duckdb"),
        ("entrypoints/http/app.py", "from ...bootstrap import build_http_app"),
        ("__init__.py", "from .infrastructure.clock import SystemClock"),
        ("application/dto.py", "from ...outside import helper"),
    ],
)
def test_rejects_forbidden_dependencies(tmp_path, path, source):
    assert violations(source_tree(tmp_path, {path: source}))


def test_rejects_forbidden_re_export(tmp_path):
    root = source_tree(
        tmp_path,
        {
            "application/services/example.py": "from ..ports import SystemClock",
            "application/ports/__init__.py": "from ...infrastructure.clock import SystemClock",
        },
    )
    errors = violations(root)
    assert any(
        "application.ports -> outage_explorer.infrastructure.clock" in error
        for error in errors
    )


def test_allows_matrix_and_dedicated_startup(tmp_path):
    root = source_tree(
        tmp_path,
        {
            "domain/policy.py": "from decimal import Decimal",
            "application/services/example.py": "from ...domain import policy\nfrom ..ports import clock",
            "infrastructure/clock.py": "from ..application.ports.clock import Clock",
            "entrypoints/http/routes/health.py": "from ....application.services import example",
            "bootstrap.py": "from .infrastructure.clock import SystemClock",
            "entrypoints/http/startup.py": STARTUP_SOURCE,
        },
    )
    assert violations(root) == []


def test_startup_exception_cannot_add_handlers_or_import_time_work(tmp_path):
    root = source_tree(
        tmp_path,
        {
            "entrypoints/http/startup.py": STARTUP_SOURCE
            + "\napp = build_http_app()\n",
        },
    )
    assert any("startup may only forward" in error for error in violations(root))


def test_detects_cycles_even_within_a_layer(tmp_path):
    root = source_tree(
        tmp_path,
        {
            "application/first.py": "from . import second",
            "application/second.py": "from . import first",
        },
    )
    assert any("Import cycle" in error for error in violations(root))


def test_allows_only_dedicated_cli_composition(tmp_path):
    root = source_tree(tmp_path, {"entrypoints/cli/startup.py": CLI_STARTUP_SOURCE})
    assert violations(root) == []


@pytest.mark.parametrize(
    "addition",
    [
        "\nservice = build_national_verifier()\n",
        "\ndef handler():\n    return build_national_verifier()\n",
        "\nimport pathlib\n",
    ],
)
def test_cli_wrapper_cannot_add_import_time_work_or_handlers(tmp_path, addition):
    root = source_tree(
        tmp_path, {"entrypoints/cli/startup.py": CLI_STARTUP_SOURCE + addition}
    )
    assert any("startup may only compose" in error for error in violations(root))


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "entrypoints/cli/command.py",
            "from ...bootstrap import build_national_verifier",
        ),
        ("entrypoints/cli/command.py", "from .startup import main"),
        ("entrypoints/http/routes/bad.py", "from ...cli.startup import main"),
        (
            "entrypoints/cli/command.py",
            "from ...infrastructure.recorded_evidence import LocalRecordedEvidence",
        ),
        ("entrypoints/cli/command.py", "from ...domain.national import calculate"),
        ("application/services/bad.py", "import argparse"),
        ("domain/bad.py", "import sys"),
    ],
)
def test_cli_exception_does_not_weaken_other_boundaries(tmp_path, path, source):
    assert violations(source_tree(tmp_path, {path: source}))


@pytest.mark.parametrize("wrapper", list(CLI_WRAPPERS)[1:])
@pytest.mark.parametrize(
    "addition",
    [
        "",
        "\nservice = None\n",
        "\ndef handler():\n    return None\n",
        "\nimport pathlib\n",
    ],
)
def test_detail_startup_exception_is_exact(tmp_path, wrapper, addition):
    _, expected = CLI_WRAPPERS[wrapper]
    path = wrapper.removeprefix("outage_explorer.").replace(".", "/") + ".py"
    errors = violations(source_tree(tmp_path, {path: expected + addition}))
    assert bool(errors) == bool(addition)


@pytest.mark.parametrize("grain", ["facility", "generator"])
@pytest.mark.parametrize(
    "source",
    [
        "entrypoints/cli/command.py",
        "entrypoints/http/routes/bad.py",
        "application/services/bad.py",
    ],
)
def test_detail_startup_cannot_be_imported_as_service_locator(tmp_path, grain, source):
    code = f"from outage_explorer.entrypoints.cli.{grain}_startup import main"
    assert violations(source_tree(tmp_path, {source: code}))


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_command_cannot_use_detail_bootstrap_directly(tmp_path, grain):
    code = f"from outage_explorer.bootstrap import build_{grain}_verifier"
    assert violations(source_tree(tmp_path, {"entrypoints/cli/command.py": code}))
