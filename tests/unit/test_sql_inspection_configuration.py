"""Candidate/review separation and inert CLI parser composition."""

import json
from dataclasses import asdict
from datetime import date
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.infrastructure.sql_validation.configuration import (
    InspectionProfile,
    InspectionReview,
    read_inspection_config,
)
from tests.unit.test_subprocess_sql_inspection import bounds


def profile(tmp_path):
    return InspectionProfile(
        bounds(),
        "/trusted/python",
        "/usr/bin/prlimit",
        "/usr/bin/setpriv",
        str(tmp_path / "parser"),
        "a" * 64,
        "b" * 64,
        "c" * 64,
    )


def write(tmp_path, candidate, evidence=None):
    path = tmp_path / "parser.json"
    path.write_text(json.dumps({"profile": asdict(candidate), "evidence": evidence}))
    return path


def test_candidate_roundtrip_and_review_identity(tmp_path):
    candidate = profile(tmp_path)
    assert read_inspection_config(write(tmp_path, candidate)) == (candidate, None)
    record = InspectionReview(
        candidate.identity, "d" * 64, "e" * 64, "controlled reviewer", date(2026, 10, 6)
    )
    raw = asdict(record)
    raw["reviewed_on"] = record.reviewed_on.isoformat()
    assert read_inspection_config(write(tmp_path, candidate, raw)) == (
        candidate,
        record,
    )
    record.require_ready(candidate)
    mismatched = InspectionReview(
        "f" * 64, "d" * 64, "e" * 64, "controlled", date(2026, 10, 6)
    )
    with pytest.raises(RuntimeUnavailableError):
        mismatched.require_ready(candidate)
    adapter = candidate.build()
    assert not (tmp_path / "parser").exists()
    adapter.close()


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"{}",
        b"null",
        b"x" * 65537,
        b'{"profile":{},"profile":{},"evidence":null}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_invalid_configuration_sanitized(tmp_path, raw):
    path = tmp_path / "parser.json"
    path.write_bytes(raw)
    with pytest.raises(
        ValueError, match="^Invalid nonsecret SQL inspection configuration$"
    ):
        read_inspection_config(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("python", None),
        ("python", "/trusted/../secret"),
        ("python_sha256", "private"),
        ("ownership_root", "relative"),
        ("setpriv", True),
        ("bounds", {"memory_bytes": 1}),
    ],
)
def test_invalid_profile_no_supplied_values(tmp_path, field, value):
    raw = asdict(profile(tmp_path))
    raw[field] = value
    path = tmp_path / "parser.json"
    path.write_text(json.dumps({"profile": raw, "evidence": None}))
    with pytest.raises(
        ValueError, match="^Invalid nonsecret SQL inspection configuration$"
    ):
        read_inspection_config(path)


def test_cli_forwards_separate_config_without_starting_api():
    from outage_explorer.entrypoints.http.analytical_command import run

    execute = Mock(return_value=0)
    assert (
        run(execute, ["--config", "runtime.json", "--inspection-config", "parser.json"])
        == 0
    )
    execute.assert_called_once_with("runtime.json", "127.0.0.1", 5000, "parser.json")


def test_unreviewed_parser_config_rejected_before_api_or_runtime(tmp_path, monkeypatch):
    from outage_explorer import bootstrap
    from tests.integration.test_analytical_supervisor import profile as runtime_profile

    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps({"profile": asdict(runtime_profile(tmp_path)), "evidence": None})
    )
    parser = write(tmp_path, profile(tmp_path))
    builder = Mock(side_effect=AssertionError("runtime constructed"))
    monkeypatch.setattr(bootstrap, "build_analytical_resources", builder)
    with pytest.raises(
        RuntimeUnavailableError, match="Reviewed SQL inspection unavailable"
    ):
        bootstrap.execute_analytical_http(str(runtime), "127.0.0.1", 5000, str(parser))
    builder.assert_not_called()
    assert not (tmp_path / "parser").exists()


def test_changed_executable_rejected_before_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "outage_explorer.infrastructure.sql_validation.subprocess_inspection.sys.platform",
        "linux",
    )
    python = tmp_path / "python"
    python.write_bytes(b"changed")
    candidate = InspectionProfile(
        bounds(),
        str(python),
        "/usr/bin/prlimit",
        "/usr/bin/setpriv",
        str(tmp_path / "parser"),
        "a" * 64,
        "b" * 64,
        "c" * 64,
    )
    with pytest.raises(RuntimeUnavailableError, match="executable identity mismatch"):
        candidate.build().start()
    assert not (tmp_path / "parser").exists()
