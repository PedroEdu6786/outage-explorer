"""Offline evidence replay, mismatch visibility and integrity rejection."""

import hashlib
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path("docs/challenge/evidence/facility_row_count.py")
EXTENSIONS = Path("docs/challenge/evidence/reconciliation_extensions.py")


@pytest.fixture
def evidence(tmp_path):
    # Copy only the fixed, versioned inputs; no local investigation directory.
    for grain in ("national", "facility", "generator"):
        relative = Path("data/verification") / f"{grain}-2026-09"
        shutil.copytree(ROOT / relative, tmp_path / relative)
    destination = tmp_path / SCRIPT
    destination.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / SCRIPT, destination)
    probes = Path("docs/challenge/evidence/facility-row-count/live-probes.json")
    (tmp_path / probes).parent.mkdir()
    shutil.copyfile(ROOT / probes, tmp_path / probes)
    return tmp_path


def replay(root, *arguments, script=SCRIPT):
    # stdlib only (-S), from an unrelated cwd. Disable network explicitly.
    wrapper = (
        "import runpy, socket, sys; from pathlib import Path; "
        "socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')); "
        "sys.argv = sys.argv[1:]; sys.path.insert(0, str(Path(sys.argv[0]).parent)); "
        "runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    return subprocess.run(
        [sys.executable, "-S", "-c", wrapper, str(root / script), *arguments],
        cwd=root.parent,
        env={},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("arguments", "report"),
    [
        (("--reconciliation-only",), "reconciliation.json"),
        ((), "facility-row-count.json"),
    ],
)
def test_offline_replay_matches_saved_report_without_local_downloads(
    evidence, arguments, report
):
    result = replay(evidence, *arguments)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (ROOT / "docs/challenge/evidence" / report).read_text()


def test_reconciliation_does_not_require_separate_probe_evidence(evidence):
    (evidence / "docs/challenge/evidence/facility-row-count/live-probes.json").unlink()
    result = replay(evidence, "--reconciliation-only")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["daily_reconciliation"]) == 30
    assert report["generator_groups"] == 1650


@pytest.mark.parametrize("kind", ["snapshot", "probes"])
def test_corrupt_evidence_fails_without_a_report(evidence, kind):
    relative = (
        "data/verification/national-2026-09/national.json"
        if kind == "snapshot"
        else "docs/challenge/evidence/facility-row-count/live-probes.json"
    )
    with (evidence / relative).open("ab") as stream:
        stream.write(b" ")
    result = replay(evidence)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "hash differs" in result.stderr


@pytest.mark.parametrize("change", ["value_gap", "duplicate", "missing_parent"])
def test_changed_inputs_report_real_gaps_or_reject_duplicate_keys(evidence, change):
    # Synthetic mutations prove the analysis does not assume zero gaps.
    folder = evidence / "data/verification/facility-2026-09"
    manifest = json.loads((folder / "manifest.json").read_text())
    snapshot = folder / manifest["snapshot"]
    document = json.loads(snapshot.read_text())
    rows = document["response"]["data"]
    row = next(r for r in rows if (r["period"], r["facility"]) == ("2026-09-01", "46"))
    if change == "value_gap":
        row["outage"] = str(Decimal(row["outage"]) + Decimal("1.25"))
    elif change == "duplicate":
        rows.append(dict(row))
    else:
        rows.remove(row)
    snapshot.write_text(json.dumps(document))
    manifest["artifacts"][snapshot.name] = hashlib.sha256(
        snapshot.read_bytes()
    ).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest))

    if change == "duplicate":
        result = replay(evidence, "--reconciliation-only")
        assert result.returncode != 0
        assert "Duplicate facility keys" in result.stderr
        assert result.stdout == ""
        return

    result = replay(evidence, "--reconciliation-only")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    if change == "missing_parent":
        assert report["missing_parent_keys"] == [["2026-09-01", "46"]]
        assert report["generator_rows_without_parent"] == 3
        assert report["browns_ferry_example"]["facility"] is None
        assert report["counts"]["facility"]["missing_days_within_observed_roster"] == 1
        return

    assert report["generator_to_facility_differences"] == [
        {
            "key": ["2026-09-01", "46"],
            "field": "outage",
            "facility": "750.418",
            "generator_sum": "749.168",
            "gap": "-1.250",
        }
    ]
    day = report["daily_reconciliation"][0]
    assert Decimal(day["gaps_from_national"]["facility"]["outage"]) == Decimal("1.25")
    assert Decimal(day["gaps_from_national"]["generator"]["outage"]) == 0


@pytest.fixture
def extended_evidence(evidence):
    folder = Path("docs/challenge/evidence")
    for name in (EXTENSIONS.name, "historical_omissions.py"):
        shutil.copyfile(ROOT / folder / name, evidence / folder / name)
    shutil.copytree(
        ROOT / folder / "historical-omissions",
        evidence / folder / "historical-omissions",
    )
    return evidence


def test_extended_replay_covers_history_metrics_identity_and_daily_changes(
    extended_evidence,
):
    result = replay(extended_evidence, script=EXTENSIONS)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert (
        result.stdout
        == (ROOT / "docs/challenge/evidence/reconciliation-extensions.json").read_text()
    )
    history = report["historical_coverage_checks"]
    assert history["total_reconciled_days"] == 152
    assert history["total_facility_day_groups"] == 9532
    assert report["combined_sample_coverage"]["sampled_dates"] == 182
    assert report["combined_sample_coverage"]["facility_day_groups"] == 11182
    sensitivity = history["denominator_sensitivity_example"]
    assert Decimal(sensitivity["capacity_difference_mw"]) == -967
    assert Decimal(sensitivity["difference_percentage_points"]).quantize(
        Decimal("0.000001")
    ) == Decimal("0.139092")
    assert (
        sum(row["missing_dates_with_nrc_full_power"] for row in history["samples"])
        == 43
    )
    first = report["daily_metric_and_identity_checks"][0]
    assert first["generator_observation_categories"] == {
        "zero": 84,
        "partial": 10,
        "full": 1,
    }
    assert first["generator_id_occurrences"]["1"] == 47
    assert Decimal(first["national_capacity_offline_percent"]).quantize(
        Decimal("0.0001")
    ) == Decimal("2.7804")
    assert Decimal(
        first["grain_metrics"]["facility"]["unweighted_mean_percent"]
    ).quantize(Decimal("0.0001")) == Decimal("3.2921")
    transitions = report["daily_change_attribution"]
    assert len(transitions) == 29
    for row in transitions:
        assert Decimal(row["matched_units_minus_national_delta_mw"]) == 0
        assert Decimal(row["facility_minus_national_delta_mw"]) == 0
        assert Decimal(row["generator_minus_national_delta_mw"]) == 0
        assert row["added_observation_keys"] == row["removed_observation_keys"] == []
        assert all(
            Decimal(facility["gap_mw"]) == 0
            for facility in row["facility_change_attribution"]
        )
    example = next(row for row in transitions if row["after"] == "2026-09-14")
    assert Decimal(example["matched_unit_increases_mw"]) == Decimal("860.516")
    assert Decimal(example["matched_unit_decreases_mw"]) == Decimal("-1817.071")
    assert Decimal(example["national_delta_outage_mw"]) == Decimal("-956.555")


def rewrite_snapshot(root, grain, mutate):
    folder = root / "data/verification" / f"{grain}-2026-09"
    manifest = json.loads((folder / "manifest.json").read_text())
    snapshot = folder / manifest["snapshot"]
    document = json.loads(snapshot.read_text())
    mutate(document["response"]["data"])
    snapshot.write_text(json.dumps(document))
    manifest["artifacts"][snapshot.name] = hashlib.sha256(
        snapshot.read_bytes()
    ).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest))


def test_offsetting_entity_errors_are_visible_despite_matching_national_sums(
    extended_evidence,
):
    def mutate(rows):
        candidates = [
            r for r in rows if r["period"] == "2026-09-01" and Decimal(r["outage"]) > 2
        ]
        for row, delta in zip(
            candidates[:2], (Decimal("1.25"), Decimal("-1.25")), strict=True
        ):
            row["outage"] = str(Decimal(row["outage"]) + delta)

    rewrite_snapshot(extended_evidence, "facility", mutate)
    result = replay(extended_evidence, script=EXTENSIONS)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["facility_gap_diagnostics"]["outage"] == {
        "mismatched_facility_day_groups": 2,
        "signed_gap_sum_mw": "0.000",
        "absolute_gap_sum_mw": "2.500",
    }
    first = report["daily_metric_and_identity_checks"][0]
    assert (
        Decimal(
            first["grain_metrics"]["facility"][
                "weighted_minus_national_percentage_points"
            ]
        )
        == 0
    )


def test_temporal_attribution_reports_missing_observation_instead_of_a_zero(
    extended_evidence,
):
    def mutate(rows):
        row = next(
            r
            for r in rows
            if (r["period"], r["facility"], r["generator"])
            == ("2026-09-14", "6110", "1")
        )
        rows.remove(row)

    rewrite_snapshot(extended_evidence, "generator", mutate)
    result = replay(extended_evidence, script=EXTENSIONS)
    assert result.returncode == 0, result.stderr
    transitions = json.loads(result.stdout)["daily_change_attribution"]
    disappearance = next(row for row in transitions if row["after"] == "2026-09-14")
    reappearance = next(row for row in transitions if row["before"] == "2026-09-14")
    assert disappearance["removed_observation_keys"] == [["6110", "1"]]
    assert reappearance["added_observation_keys"] == [["6110", "1"]]
    assert Decimal(disappearance["matched_units_minus_national_delta_mw"]) != 0


def test_extended_replay_rejects_corrupt_historical_archive(extended_evidence):
    with (
        extended_evidence
        / "docs/challenge/evidence/historical-omissions/sources.json.gz"
    ).open("ab") as stream:
        stream.write(b"corrupt")
    result = replay(extended_evidence, script=EXTENSIONS)
    assert result.returncode != 0
    assert result.stdout == ""
