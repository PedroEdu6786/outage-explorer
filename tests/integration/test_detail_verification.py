import hashlib
import json
import shutil
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

from outage_explorer.application.errors import VerificationError
from outage_explorer.bootstrap import (
    build_facility_verifier,
    build_generator_verifier,
    build_national_verifier,
)
from outage_explorer.entrypoints.cli.command import run
from outage_explorer.infrastructure.verification_report import (
    LocalReportWriter,
    report_document,
)

from .test_national_verification import assert_arithmetic, read, rehash, write_json

ROOT = Path(__file__).resolve().parents[2]
BUILDERS = {"facility": build_facility_verifier, "generator": build_generator_verifier}
EXPECTED = {
    "facility": (
        1650,
        55,
        "a0bae3e25ff11c0ed4e7721ecb0c79b4f4c798f95aa1e4111460157eec5376e9",
    ),
    "generator": (
        2850,
        95,
        "9f58a9cb19f19a585181f14c6d570d73b8de25310eefbfbdf041b1affeb23d93",
    ),
}


@pytest.fixture(params=["facility", "generator"])
def grain(request):
    return request.param


@pytest.fixture
def bundle(grain, tmp_path):
    target = tmp_path / "evidence"
    shutil.copytree(ROOT / f"data/verification/{grain}-2026-09", target)
    return target


def verify(grain, bundle):
    return BUILDERS[grain]().verify(str(bundle / "manifest.json"))


def synthetic(grain, bundle, rows):
    snapshot = read(bundle / f"{grain}.json")
    snapshot["response"].update(data=rows, total=str(len(rows)))
    write_json(bundle / f"{grain}.json", snapshot)
    manifest = read(bundle / "manifest.json")
    manifest.update(
        evidence_kind="synthetic", bundle_id=f"synthetic-{grain}-policy-cases"
    )
    write_json(bundle / "manifest.json", manifest)
    rehash(bundle, f"{grain}.json")


def test_real_detail_baseline_arithmetic_identity_and_coverage(grain, bundle):
    expected_rows, entities, digest = EXPECTED[grain]
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    report = verify(grain, bundle)
    snapshot = read(bundle / f"{grain}.json")
    assert hashlib.sha256((bundle / f"{grain}.json").read_bytes()).hexdigest() == digest
    assert dict(report.counts) == {
        "received": expected_rows,
        "selected": expected_rows,
        "excluded": 0,
        "duplicate": 0,
        "superseded": 0,
    }
    assert len(report.coverage) == expected_rows
    assert Counter(c.period for c in report.coverage) == {
        f"2026-09-{d:02d}": entities for d in range(1, 31)
    }
    assert len({(c.period, c.identity) for c in report.coverage}) == expected_rows
    assert all(c.result is not None for c in report.coverage)
    capacities = {}
    for entry in report.coverage:
        result = entry.result
        source = snapshot["response"]["data"][result.source_position]
        assert dict(result.observation.original) == source
        assert entry.identity == (
            (source["facility"], source["generator"])
            if grain == "generator"
            else (source["facility"],)
        )
        assert_arithmetic(result, source)
        capacities.setdefault(entry.identity, set()).add(source["capacity"])
    assert all(len(values) == 1 for values in capacities.values())
    with pytest.raises(TypeError):
        report.evidence.records[0].value["facility"] = "changed"
    assert before == {p.name: p.read_bytes() for p in bundle.iterdir()}
    accounting = report_document(report)["source_accounting"]
    assert accounting == {
        "reported_total": "2850",
        "received_rows": expected_rows,
        "reported_total_matches_received": grain == "generator",
        "observed_entities": entities,
        "unavailable_entity_dates": 0,
        "roster_known": True,
        "upstream_completeness": "unverified",
    }


def test_detail_contract_is_supported_by_recorded_metadata_and_all_fields(
    grain, bundle
):
    metadata = read(bundle / "metadata.json")["response"]
    profile = read(bundle / "profile.json")["routes"][grain]
    rows = read(bundle / f"{grain}.json")["response"]["data"]
    facets = [f["id"] for f in metadata["facets"]]
    assert facets == (
        ["facility", "generator"] if grain == "generator" else ["facility"]
    )
    assert metadata["defaultFrequency"] == "daily"
    assert metadata["defaultDateFormat"] == "YYYY-MM-DD"
    assert metadata["data"] == {
        "capacity": {"units": "megawatts"},
        "outage": {"units": "megawatts"},
        "percentOutage": {"units": "percent"},
    }
    assert len(profile["fields"]) == (10 if grain == "generator" else 9)
    for row in rows:
        assert set(row) == set(profile["fields"])
        assert all(isinstance(value, str) and value.strip() for value in row.values())
    keys = [tuple(row[f] for f in ("period", *facets)) for row in rows]
    assert len(keys) == len(set(keys))


def test_rendered_detail_report_keeps_selected_identifiers_names_and_both_percentages(
    grain, bundle, tmp_path
):
    first = read(bundle / f"{grain}.json")["response"]["data"][0]
    changed = {
        **first,
        "capacity": "100",
        "outage": "0",
        "percentOutage": "99",
        "facilityName": "Plant | <name>\nnext",
    }
    synthetic(
        grain,
        bundle,
        [first, changed, {**changed, "period": "2026-09-02", "capacity": "0"}],
    )
    report = verify(grain, bundle)
    locations = LocalReportWriter().write(report, str(tmp_path / "report"))
    document = read(Path(locations.json))
    rendered = Path(locations.markdown).read_text()
    first_result = document["coverage"][0]
    assert first_result["identity"]["facility"] == first["facility"]
    assert first_result["result"]["source_position"] == 1
    assert first_result["result"]["reported_values"] == changed
    assert first_result["result"]["calculated_percentage_display"] == "0.00"
    assert first_result["result"]["reported_percentage_display"] == "99.00"
    assert document["coverage"][1]["result"] is None
    assert document["coverage"][1]["excluded_positions"] == [2]
    assert "Plant &#124; &lt;name&gt; next" in rendered
    assert "nonpositive_capacity" in rendered
    assert "unavailable" in rendered
    for forbidden in ("discrepancy", "tolerance", "agreement"):
        assert forbidden not in rendered.lower()
        assert forbidden not in json.dumps(document).lower()


def test_facility_total_difference_is_visible_without_inventing_rows(
    bundle, grain, tmp_path
):
    locations = LocalReportWriter().write(verify(grain, bundle), str(tmp_path / "out"))
    rendered = Path(locations.markdown).read_text()
    if grain == "facility":
        assert "Reported response total: 2850; received rows: 1650" in rendered
        assert "pagination/completeness semantics remain unresolved" in rendered
    else:
        assert "Reported response total: 2850; received rows: 2850" in rendered
    assert "upstream completeness is unverified" in rendered


@pytest.mark.parametrize("empty", [True, False])
def test_empty_or_unidentifiable_roster_is_explicit_in_report(
    grain, bundle, empty, tmp_path
):
    synthetic(grain, bundle, [] if empty else [{"period": "2026-09-01"}])
    report = verify(grain, bundle)
    doc = report_document(report)
    assert len(doc["coverage"]) == 30
    assert doc["source_accounting"]["roster_known"] is False
    assert all(c["identity"] is None and c["result"] is None for c in doc["coverage"])
    locations = LocalReportWriter().write(report, str(tmp_path / "out"))
    assert "No identifiable entity roster" in Path(locations.markdown).read_text()


def test_wrong_dataset_fails_before_rows_are_interpreted(grain, bundle):
    other = build_generator_verifier if grain == "facility" else build_facility_verifier
    for builder in (other, build_national_verifier):
        with pytest.raises(VerificationError, match="dataset"):
            builder().verify(str(bundle / "manifest.json"))


@pytest.mark.parametrize(
    "artifact", ["snapshot", "metadata.json", "profile.json", "capacity-semantics.json"]
)
def test_detail_integrity_errors_fail(grain, bundle, artifact):
    name = f"{grain}.json" if artifact == "snapshot" else artifact
    (bundle / name).write_text("{}")
    with pytest.raises(VerificationError, match="checksum"):
        verify(grain, bundle)
    (bundle / name).unlink()
    with pytest.raises(VerificationError, match="Cannot read"):
        verify(grain, bundle)


@pytest.mark.parametrize("total", [None, 2850, "NaN", "-1", "2.0", "٢٨٥٠"])
def test_invalid_total_is_bundle_error(grain, bundle, total):
    snapshot = read(bundle / f"{grain}.json")
    snapshot["response"]["total"] = total
    write_json(bundle / f"{grain}.json", snapshot)
    rehash(bundle, f"{grain}.json")
    with pytest.raises(VerificationError, match="total"):
        verify(grain, bundle)


def test_outside_period_fails_even_if_measurements_invalid(grain, bundle):
    synthetic(grain, bundle, [{"period": "2026-10-01"}])
    with pytest.raises(VerificationError, match="outside"):
        verify(grain, bundle)


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_detail_report_cannot_overwrite_evidence(grain, bundle, tmp_path, alias):
    report = verify(grain, bundle)
    output = tmp_path / "out"
    output.mkdir()
    source = bundle / f"{grain}.json"
    before = source.read_bytes()
    target = output / "report.json"
    if alias == "symlink":
        target.symlink_to(source)
    else:
        target.hardlink_to(source)
    with pytest.raises(VerificationError, match="overwrite"):
        LocalReportWriter().write(report, str(output))
    assert source.read_bytes() == before


def test_detail_cli_reports_error_without_success(grain, bundle, tmp_path, capsys):
    (bundle / f"{grain}.json").write_text("bad")
    assert (
        run(
            BUILDERS[grain](),
            [
                "--evidence-bundle",
                str(bundle / "manifest.json"),
                "--output-directory",
                str(tmp_path / "out"),
            ],
        )
        == 1
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert "Verification failed" in output.err


def test_detail_cli_is_offline_deterministic_across_clocks_and_locations(
    grain, bundle, tmp_path
):
    script = textwrap.dedent("""
        import datetime
        import importlib
        import sys
        from unittest.mock import patch

        class ClockDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(int(sys.argv[1]), 1, 1)

        def forbid_network(event, args):
            if event.startswith('socket.'):
                raise AssertionError('Network during offline verification')

        sys.addaudithook(forbid_network)
        with patch('datetime.date', ClockDate):
            main = importlib.import_module('outage_explorer.entrypoints.cli.' + sys.argv[2] + '_startup').main
            sys.argv = ['verify-detail-data', '--evidence-bundle', sys.argv[3], '--output-directory', sys.argv[4]]
            raise SystemExit(main())
    """)
    outputs = []
    for year in (2026, 2035):
        evidence = tmp_path / f"copy-{year}"
        shutil.copytree(bundle, evidence)
        destination = tmp_path / f"out-{year}"
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(year),
                grain,
                str(evidence / "manifest.json"),
                str(destination),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(
            tuple(
                (destination / f"report.{extension}").read_bytes()
                for extension in ("json", "md")
            )
        )
    assert outputs[0] == outputs[1]
