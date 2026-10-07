"""Operator review gates use controlled reports; no daemon or cloud calls."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "review_local_runtime",
    Path(__file__).parents[1] / "scripts/review_local_runtime.py",
)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


@pytest.mark.parametrize(
    "content",
    [
        "<testsuite/>",
        "<testsuite><testcase><failure/></testcase></testsuite>",
        "<testsuite><testcase><error/></testcase></testsuite>",
        '<testsuite><testcase name="required"><skipped/></testcase></testsuite>',
    ],
)
def test_missing_failed_or_skipped_checks_cannot_be_reviewed(tmp_path, content):
    path = tmp_path / "report.xml"
    path.write_text(content)
    with pytest.raises(ValueError):
        review.test_report(path)


def test_cpu_probe_skip_cannot_be_reviewed(tmp_path):
    path = tmp_path / "report.xml"
    path.write_text(
        '<testsuite><testcase name="test_cpu_quota_throttles_busy_children"><skipped/></testcase></testsuite>'
    )
    with pytest.raises(ValueError, match="skipped"):
        review.test_report(path)


def runtime_report(tmp_path, **changes):
    value = {
        "profile_identity": "a" * 64,
        "gates": {
            name: {"status": "passed"}
            for name in review.REQUIRED_GATES | {"identity", "cleanup"}
        },
    }
    value.update(changes)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value))
    return path


def test_required_actual_runtime_reports_are_bound_to_exact_profile(tmp_path):
    path = runtime_report(tmp_path)
    assert review.collect_runtime_reports([path], "a" * 64)[0][
        "sha256"
    ] == review.digest(path)
    with pytest.raises(ValueError, match="mismatch"):
        review.collect_runtime_reports([path], "b" * 64)


@pytest.mark.parametrize("fault", ["failed", "missing", "cleanup", "unrun"])
def test_failed_incomplete_or_unreaped_runtime_report_cannot_be_reviewed(
    tmp_path, fault
):
    path = runtime_report(tmp_path)
    value = json.loads(path.read_text())
    gate = sorted(review.REQUIRED_GATES)[0]
    if fault == "missing":
        del value["gates"][gate]
    elif fault == "cleanup":
        value["gates"]["cleanup"]["status"] = "failed"
    else:
        value["gates"][gate]["status"] = "failed" if fault == "failed" else "not_run"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        review.collect_runtime_reports([path], "a" * 64)


def test_review_refuses_anonymous_or_implicit_approval():
    with pytest.raises(SystemExit) as failure:
        review.main(["--reviewer", "Named operator"])
    assert failure.value.code == 2


def test_review_preserves_existing_record(tmp_path):
    path = tmp_path / "review.json"
    review.write_private(path, {"actual": True})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        review.write_private(path, {"replace": True})
    assert json.loads(path.read_text()) == {"actual": True}


def test_review_records_only_local_scope_and_binds_exact_reports(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tests.test_local_analytical import reviewed_configs

    runtime_path, parser_path = reviewed_configs(tmp_path, reviewed=False)
    runtime_path.rename(tmp_path / "candidate.json")
    parser_path.rename(tmp_path / "parser-candidate.json")
    profile, _ = review.read_runtime_config(tmp_path / "candidate.json")
    for name in ("controlled.xml", "parser.xml", "docker.xml"):
        (tmp_path / name).write_text(
            '<testsuite><testcase name="controlled"/></testsuite>'
        )
    report_root = tmp_path / "owned/validation-reports"
    report_root.mkdir(parents=True)
    path = runtime_report(report_root, profile_identity=profile.identity)
    calls = []

    class ControlledInspector:
        def start(self):
            calls.append("start")

        def inspect(self, sql):
            if sql != "SELECT 1":
                raise review.SqlRejected()
            return SimpleNamespace(reference_free=True)

        def close(self):
            calls.append("close")

    monkeypatch.setattr(review, "ROOT", tmp_path)
    monkeypatch.setattr(review, "SOURCE", tmp_path)
    from outage_explorer.infrastructure.sql_validation.configuration import (
        InspectionProfile,
    )

    monkeypatch.setattr(InspectionProfile, "build", lambda self: ControlledInspector())
    review.review("Controlled test only")
    runtime, evidence = review.read_runtime_config(tmp_path / "runtime-reviewed.json")
    parser, record = review.read_inspection_config(tmp_path / "parser-reviewed.json")
    evidence.require_ready(runtime, started=True, local_acceptance=True)
    record.require_ready(parser)
    assert evidence.acceptance_scope == "local-preview-sql"
    summary = json.loads((tmp_path / "local-scope-review.json").read_text())
    assert summary["containment_reports"][0]["sha256"] == review.digest(path)
    assert summary["refresh"] == "idle"
    assert "deferred" in summary["capacity_measurements"]
    assert calls == ["start", "close"]
