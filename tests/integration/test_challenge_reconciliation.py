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


def replay(root, *arguments):
    # stdlib only (-S), from an unrelated cwd. Disable network explicitly.
    wrapper = (
        "import runpy, socket, sys; "
        "socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')); "
        "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    return subprocess.run(
        [sys.executable, "-S", "-c", wrapper, str(root / SCRIPT), *arguments],
        cwd=root.parent,
        env={},
        capture_output=True,
        text=True,
        timeout=10,
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
