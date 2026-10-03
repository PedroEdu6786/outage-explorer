import hashlib
import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from outage_explorer.application.errors import VerificationError
from outage_explorer.bootstrap import build_national_verifier
from outage_explorer.entrypoints.cli.command import run
from outage_explorer.infrastructure.verification_report import LocalReportWriter

BASELINE = Path(__file__).resolve().parents[2] / "data/verification/national-2026-09"


@pytest.fixture
def bundle(tmp_path):
    destination = tmp_path / "evidence"
    shutil.copytree(BASELINE, destination)
    return destination


def read(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def rehash(bundle, name):
    manifest = read(bundle / "manifest.json")
    manifest["artifacts"][name] = hashlib.sha256(
        (bundle / name).read_bytes()
    ).hexdigest()
    write_json(bundle / "manifest.json", manifest)


def synthetic(bundle, rows):
    snapshot = read(bundle / "national.json")
    snapshot["response"]["data"] = rows
    snapshot["response"]["total"] = str(len(rows))
    write_json(bundle / "national.json", snapshot)
    manifest = read(bundle / "manifest.json")
    manifest.update(evidence_kind="synthetic", bundle_id="synthetic-policy-cases")
    write_json(bundle / "manifest.json", manifest)
    rehash(bundle, "national.json")


def verify(bundle):
    return build_national_verifier().verify(str(bundle / "manifest.json"))


def scaled_integer(value):
    """Independent base-ten oracle; no production parser or Fraction division."""
    whole, _, decimal = value.partition(".")
    return int(whole + decimal), 10 ** len(decimal)


def assert_arithmetic(result, source):
    outage, outage_scale = scaled_integer(source["outage"])
    capacity, capacity_scale = scaled_integer(source["capacity"])
    share = result.fraction
    assert (
        share.numerator * capacity * outage_scale
        == share.denominator * outage * capacity_scale
    )
    percent = result.percentage
    assert (
        percent.numerator * capacity * outage_scale
        == percent.denominator * outage * capacity_scale * 100
    )


def test_real_baseline_provenance_coverage_and_independent_arithmetic():
    report = verify(BASELINE)
    snapshot = read(BASELINE / "national.json")
    assert (
        hashlib.sha256((BASELINE / "national.json").read_bytes()).hexdigest()
        == "b140ed2d61813f500089704506a52518914cc3bce7c1859f90ab04c50ad54e9c"
    )
    assert dict(report.counts) == {
        "received": 30,
        "selected": 30,
        "excluded": 0,
        "duplicate": 0,
        "superseded": 0,
    }
    assert [day.period for day in report.coverage] == [
        f"2026-09-{day:02}" for day in range(1, 31)
    ]
    for day in report.coverage:
        result = day.result
        source = snapshot["response"]["data"][result.source_position]
        assert dict(result.observation.original) == source
        assert_arithmetic(result, source)
    with pytest.raises(AssertionError):
        assert_arithmetic(
            replace(report.coverage[0].result, fraction=Fraction(1)),
            snapshot["response"]["data"][0],
        )
    assert len({day.result.observation.capacity for day in report.coverage}) == 1


def test_retained_records_are_immutable_and_evidence_bytes_unchanged(bundle):
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    report = verify(bundle)
    with pytest.raises(TypeError):
        report.evidence.records[0].value["capacity"] = "0"
    assert before == {p.name: p.read_bytes() for p in bundle.iterdir()}


def test_mixed_rows_account_for_exclusions_duplicates_conflicts_and_gaps(
    bundle, tmp_path
):
    first = read(bundle / "national.json")["response"]["data"][0]
    rows = [
        first,
        {**first, "outage": "0", "percentOutage": "99"},
        {**first, "outage": "0", "percentOutage": "99"},
        {**first, "capacity": "0", "extra": "bad"},
        {**first, "period": "2026-09-02", "outage": "bad"},
        {**first, "period": "bad-date"},
    ]
    synthetic(bundle, rows)
    report = verify(bundle)
    assert dict(report.counts) == {
        "received": 6,
        "selected": 1,
        "excluded": 3,
        "duplicate": 1,
        "superseded": 1,
    }
    assert sum(dict(report.reason_counts).values()) == 4
    assert [item.status for item in report.ledger] == [
        "superseded",
        "duplicate",
        "selected",
        "excluded",
        "excluded",
        "excluded",
    ]
    assert report.coverage[0].result.source_position == 2
    assert report.coverage[0].result.calculated_display == "0.00"
    assert report.coverage[0].result.reported_display == "99.00"
    assert report.coverage[0].excluded_positions == (3,)
    assert report.coverage[1].result is None
    assert report.coverage[1].excluded_positions == (4,)
    assert report.coverage[2].result is None
    assert report.coverage[2].excluded_positions == ()
    locations = LocalReportWriter().write(report, str(tmp_path / "report"))
    document = read(Path(locations.json))
    rendered = Path(locations.markdown).read_text()
    assert document["coverage"][0]["result"]["reported_values"] == rows[2]
    assert document["coverage"][1]["result"] is None
    assert len(document["source_records"]) == len(rows)
    for forbidden in (
        "mismatch",
        "discrepancy",
        "warning",
        "alert",
        "tolerance",
        "agreement",
    ):
        assert forbidden not in rendered.lower()
        assert forbidden not in json.dumps(document).lower()
    assert "unavailable" in rendered
    assert "nonpositive_capacity" in rendered
    assert "invalid_number" in rendered


@pytest.mark.parametrize("empty", [True, False])
def test_no_usable_rows_leave_all_dates_unavailable(bundle, empty):
    synthetic(bundle, [] if empty else [{"period": "2026-09-01"}])
    report = verify(bundle)
    assert len(report.coverage) == 30
    assert all(day.result is None for day in report.coverage)
    assert dict(report.counts)["selected"] == 0


def test_incorrect_calculation_fails_without_comparing_reported_percentage(monkeypatch):
    from outage_explorer.application.services import evidence

    actual = evidence.calculate
    monkeypatch.setattr(
        evidence,
        "calculate",
        lambda observation, position: replace(
            actual(observation, position), fraction=Fraction(1)
        ),
    )
    with pytest.raises(VerificationError, match="Calculation invariant"):
        verify(BASELINE)


@pytest.mark.parametrize(
    "name",
    ["national.json", "metadata.json", "profile.json", "capacity-semantics.json"],
)
def test_corrupt_or_missing_evidence_fails(bundle, name):
    (bundle / name).write_text("{}")
    with pytest.raises(VerificationError, match="checksum"):
        verify(bundle)
    (bundle / name).unlink()
    with pytest.raises(VerificationError, match="Cannot read"):
        verify(bundle)


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"response": {}}',
        '{"response": {"data": {}, "frequency": "daily", "dateFormat": "YYYY-MM-DD"}}',
        '{"a":1,"a":2}',
        '{"value":NaN}',
    ],
)
def test_malformed_evidence_is_not_a_row_exclusion(bundle, payload):
    (bundle / "national.json").write_text(payload)
    rehash(bundle, "national.json")
    with pytest.raises(VerificationError):
        verify(bundle)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", 2),
        ("bundle_version", True),
        ("report_version", None),
        ("start", "2025-09-01"),
        ("end", "2026-10-01"),
        ("snapshot", "missing.json"),
        ("parameters", None),
        ("evidence_kind", "unknown"),
    ],
)
def test_invalid_manifest_fails_explicitly(bundle, field, value):
    manifest = read(bundle / "manifest.json")
    manifest[field] = value
    write_json(bundle / "manifest.json", manifest)
    with pytest.raises(VerificationError):
        verify(bundle)


def test_outside_interval_is_a_bundle_error(bundle):
    row = read(bundle / "national.json")["response"]["data"][0]
    synthetic(bundle, [{**row, "period": "2026-10-01"}])
    with pytest.raises(VerificationError, match="outside"):
        verify(bundle)


def test_cli_failure_does_not_report_success(bundle, tmp_path, capsys):
    (bundle / "national.json").write_text("corrupt")
    output = tmp_path / "output"
    assert (
        run(
            build_national_verifier(),
            [
                "--evidence-bundle",
                str(bundle / "manifest.json"),
                "--output-directory",
                str(output),
            ],
        )
        == 1
    )
    capture = capsys.readouterr()
    assert "Verification failed" in capture.err
    assert capture.out == ""
    assert not output.exists()


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_report_cannot_overwrite_source_via_alias(bundle, tmp_path, alias):
    report = verify(bundle)
    output = tmp_path / "output"
    output.mkdir()
    target = output / "report.json"
    source = bundle / "national.json"
    before = source.read_bytes()
    if alias == "symlink":
        target.symlink_to(source)
    else:
        target.hardlink_to(source)
    with pytest.raises(VerificationError, match="overwrite"):
        LocalReportWriter().write(report, str(output))
    assert source.read_bytes() == before


def test_report_write_error_fails(tmp_path):
    destination = tmp_path / "not-a-directory"
    destination.write_text("existing file")
    with pytest.raises(VerificationError, match="Cannot write"):
        LocalReportWriter().write(verify(BASELINE), str(destination))


def test_report_outputs_must_not_alias_each_other(tmp_path):
    (tmp_path / "report.md").symlink_to(tmp_path / "report.json")
    with pytest.raises(VerificationError, match="distinct"):
        LocalReportWriter().write(verify(BASELINE), str(tmp_path))


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"data": {}},
        {"data": [], "frequency": "monthly", "dateFormat": "YYYY-MM-DD"},
        {"data": [], "frequency": "daily", "dateFormat": "YYYYMMDD"},
    ],
)
def test_invalid_response_envelope_fails_before_row_processing(bundle, response):
    snapshot = read(bundle / "national.json")
    snapshot["response"] = response
    write_json(bundle / "national.json", snapshot)
    rehash(bundle, "national.json")
    with pytest.raises(VerificationError):
        verify(bundle)


def test_bundle_cannot_escape_to_an_external_artifact(bundle, tmp_path):
    external = tmp_path / "external.json"
    external.write_text("{}")
    manifest = read(bundle / "manifest.json")
    manifest["artifacts"]["../external.json"] = hashlib.sha256(
        external.read_bytes()
    ).hexdigest()
    write_json(bundle / "manifest.json", manifest)
    with pytest.raises(VerificationError, match="inside"):
        verify(bundle)


def test_mislabeled_request_interval_fails(bundle):
    manifest = read(bundle / "manifest.json")
    manifest["parameters"]["start"] = "2025-09-01"
    write_json(bundle / "manifest.json", manifest)
    with pytest.raises(VerificationError, match="request"):
        verify(bundle)


def test_source_provenance_must_match_manifest(bundle):
    snapshot = read(bundle / "national.json")
    snapshot["retrieved_at_utc"] = "2030-01-01T00:00:00Z"
    write_json(bundle / "national.json", snapshot)
    rehash(bundle, "national.json")
    with pytest.raises(VerificationError, match="provenance"):
        verify(bundle)


def test_recorded_metadata_and_profile_support_contract():
    metadata = read(BASELINE / "metadata.json")["response"]
    profile = read(BASELINE / "profile.json")["routes"]["us"]
    assert metadata["facets"] == []
    assert metadata["defaultFrequency"] == "daily"
    assert metadata["defaultDateFormat"] == "YYYY-MM-DD"
    assert metadata["data"] == {
        "capacity": {"units": "megawatts"},
        "outage": {"units": "megawatts"},
        "percentOutage": {"units": "percent"},
    }
    assert len(profile["fields"]) == 7
    assert all(
        field["json_types"] == ["str"] and field["null_or_missing"] == 0
        for field in profile["fields"].values()
    )
    assert profile["rows"] == 30


def test_offline_cli_replay_is_identical_under_changed_clocks(bundle, tmp_path):
    script = textwrap.dedent("""
        import datetime
        import sys
        from unittest.mock import patch

        class ClockDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(int(sys.argv[1]), 1, 1)

        def forbid_network(event, args):
            if event.startswith("socket."):
                raise AssertionError("Network access during offline verification")

        sys.addaudithook(forbid_network)
        with patch("datetime.date", ClockDate):
            from outage_explorer.entrypoints.cli.startup import main
            sys.argv = ["verify-national-data", "--evidence-bundle", sys.argv[2], "--output-directory", sys.argv[3]]
            raise SystemExit(main())
    """)
    outputs = []
    for year in (2026, 2035):
        destination = tmp_path / str(year)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(year),
                str(bundle / "manifest.json"),
                str(destination),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(
            (
                (destination / "report.json").read_bytes(),
                (destination / "report.md").read_bytes(),
            )
        )
    assert outputs[0] == outputs[1]
    rendered = outputs[0][1].decode()
    for text in (
        "full outages",
        "partial output reductions",
        "capacity changes",
        "vintage",
        "reactor shutdown proportion",
        "full-day averages",
        "outage duration",
        "lost energy",
        "outage causes",
        "physical operation",
        "2026-09-01",
        "2026-09-30",
    ):
        assert text in rendered
