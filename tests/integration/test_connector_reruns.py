"""Pinned immutable reruns and failures preserve earlier readable candidates."""

from unittest.mock import patch

import pytest

from outage_explorer.application.ports.source import ROUTES
from outage_explorer.bootstrap import execute_connector
from outage_explorer.infrastructure.connector_report import LocalConnectorReports
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_cli import (
    SECRET,
    Wire,
    config_file,
    environment,
    execute,
    inputs,
    models,
    reopen,
    row,
)


def run_at(root, rows, start, end, prior=None):
    wire = Wire(rows)
    result = execute_connector(
        inputs(root, prior, start, end), environment=environment(), transport=wire
    )
    assert wire.closed
    return result


def test_rerun_retains_original_invalid_absent_outside_and_excluded_route(tmp_path):
    original = {
        grain: [row(grain, period=f"2026-09-0{day}") for day in (1, 2, 3)]
        for grain in ROUTES
    }
    original["facility"].insert(2, row("facility", period="2026-09-02", facility="002"))
    initial = run_at(tmp_path, original, "2026-09-01", "2026-09-03")
    reference = initial.report.manifest
    assert reference is not None
    store, prior = reopen(tmp_path, reference)
    old = {
        grain: {item.key: item for item in models(store, prior, grain)}
        for grain in ROUTES
    }
    incoming = {
        "national": [
            row("national", period="2026-09-02", capacity="bad"),
            row("national", period="2026-09-03", outage="2"),
        ],
        "facility": [
            row("facility", period="2026-09-02", capacity="bad"),
            row("facility", period="2026-09-02", facility="003", capacity="bad"),
        ],
        "generator": [row("generator", period="2026-09-03", outage="2")],
    }
    changed = run_at(tmp_path, incoming, "2026-09-02", "2026-09-03", reference)
    assert changed.report.outcome == "candidate_verified"
    store, candidate = reopen(tmp_path, changed.report.manifest)
    for grain in ROUTES:
        current = models(store, candidate, grain)
        assert len(current) == len(old[grain])
        for item in current:
            if grain != "facility" and item.observation.day.day == 3:
                assert (
                    item.observation.outage == 2
                    and item.origin.run_id == changed.report.run_id
                )
            else:
                assert item == old[grain][item.key]
    summaries = {summary.grain: summary for summary in candidate.summaries}
    assert (
        summaries["national"].retained_invalid,
        summaries["national"].retained_absent,
        summaries["national"].carried_outside_interval,
    ) == (1, 0, 1)
    assert (
        summaries["facility"].retained_invalid,
        summaries["facility"].retained_absent,
        summaries["facility"].carried_outside_interval,
    ) == (1, 2, 1)
    assert (
        summaries["generator"].retained_invalid,
        summaries["generator"].retained_absent,
        summaries["generator"].carried_outside_interval,
    ) == (0, 1, 1)
    for summary in summaries.values():
        assert (
            summary.candidate_count
            == summary.quality.selected
            + summary.retained_invalid
            + summary.retained_absent
            + summary.carried_outside_interval
        )
    repeated = run_at(
        tmp_path, incoming, "2026-09-02", "2026-09-03", changed.report.manifest
    )
    store, repeated_candidate = reopen(tmp_path, repeated.report.manifest)
    for grain in ROUTES:
        values = models(store, repeated_candidate, grain)
        assert len(values) == len({item.key for item in values}) == len(old[grain])
    assert reopen(tmp_path, reference)[1] == prior
    assert len(list((tmp_path / "runs").glob("*/report.json"))) == 3


def test_all_excluded_preserves_prior_and_reports_reasons(tmp_path):
    initial, _ = execute(tmp_path)
    reference = initial.report.manifest
    _, prior = reopen(tmp_path, reference)
    rows = {grain: [row(grain, capacity="bad", outage="bad")] for grain in ROUTES}
    result, _ = execute(tmp_path, rows, prior=reference)
    assert (
        result.report.outcome == "retained_all_excluded" and not result.report.published
    )
    _, candidate = reopen(tmp_path, result.report.manifest)
    assert candidate.modeled == prior.modeled
    for summary in candidate.summaries:
        assert summary.retained_invalid == 1 and summary.quality.excluded == 1
        assert sum(count for _, count in summary.quality.reason_counts) == 2
    # Retained outcomes are reports, not eligible new bases. Keep the last candidate.
    invalid, wire = execute(tmp_path, prior=result.report.manifest)
    assert invalid.report.error == "prior_integrity" and not wire.calls
    assert reopen(tmp_path, reference)[1] == prior


@pytest.mark.parametrize("grain", list(ROUTES))
@pytest.mark.parametrize("unusable", ["empty", "excluded"])
def test_initial_requires_usable_output_for_every_grain(tmp_path, grain, unusable):
    rows = {g: [row(g)] for g in ROUTES}
    rows[grain] = [] if unusable == "empty" else [row(grain, capacity="invalid")]
    result, _ = execute(tmp_path, rows)
    assert result.report.outcome == "failed"
    assert result.report.error == (
        "retrieval" if unusable == "empty" else "unusable_input"
    )
    assert result.report.manifest is None and not result.report.published


@pytest.mark.parametrize(
    "fault,code",
    [
        ("page", "retrieval"),
        ("source_budget", "resource"),
        ("artifact_budget", "resource"),
        ("model_budget", "resource"),
        ("representation", "representation"),
        ("interrupted", "interrupted"),
        ("write", "prior_integrity"),
        ("report", "report"),
    ],
)
def test_failures_never_damage_prior_or_report_unconfirmed_success(
    tmp_path, fault, code
):
    initial, _ = execute(tmp_path)
    reference = initial.report.manifest
    store, prior = reopen(tmp_path, reference)
    prior_bytes = {
        path.name: path.read_bytes() for path in (tmp_path / "objects").iterdir()
    }
    rows = {grain: [row(grain, outage="2")] for grain in ROUTES}
    config = {}
    wire = Wire(rows)
    target = None
    if fault == "page":
        wire.failure = ("facility", 0)
    elif fault == "source_budget":
        config = {"source": {"requests": 1}}
    elif fault == "artifact_budget":
        # Prior fits; adding evidence exhausts the write session budget.
        config = {"artifact": {"objects": 1}}
    elif fault == "model_budget":
        config = {"model": {"incoming_rows": 1}}
        wire.rows = {grain: [row(grain), row(grain, outage="2")] for grain in ROUTES}
    elif fault == "representation":
        wire.rows = {
            grain: [row(grain, capacity="1e-30", outage="0")] for grain in ROUTES
        }
    elif fault == "interrupted":

        def interrupt(grain, offset):
            raise KeyboardInterrupt

        wire.failure = interrupt
    elif fault == "write":
        target = patch.object(
            LocalParquetStore, "put_immutable", side_effect=OSError(SECRET)
        )
    elif fault == "report":
        target = patch.object(
            LocalConnectorReports, "finish", side_effect=OSError(SECRET)
        )
    parameters = inputs(tmp_path, reference, config_path=config_file(tmp_path, config))
    if target:
        with target:
            result = execute_connector(
                parameters, environment=environment(), transport=wire
            )
    else:
        result = execute_connector(
            parameters, environment=environment(), transport=wire
        )
    assert result.report.outcome == "failed" and result.report.error == code
    assert (
        result.report.manifest is None and not result.report.published and wire.closed
    )
    assert SECRET not in repr(result)
    assert reopen(tmp_path, reference)[1] == prior
    assert all(
        (tmp_path / "objects" / key).read_bytes() == value
        for key, value in prior_bytes.items()
    )
    if fault == "report":
        assert not result.report_written
        assert not (tmp_path / "runs" / result.report.run_id / "report.json").exists()


def test_corrupt_prior_graph_is_rejected_before_retrieval(tmp_path):
    # Corrupt a disposable copy, keeping the earlier staging directory intact.
    import shutil

    original = tmp_path / "original"
    damaged = tmp_path / "damaged"
    initial, _ = execute(original)
    reference = initial.report.manifest
    _, prior = reopen(original, reference)
    shutil.copytree(original, damaged)
    child = prior.evidence[0].raw[0].object
    (damaged / "objects" / child.key).write_bytes(b"corrupt")
    result, wire = execute(damaged, prior=reference)
    assert result.report.error == "prior_integrity" and not wire.calls
    assert reopen(original, reference)[1] == prior


def test_report_budget_failure_cannot_claim_completion(tmp_path):
    result, _ = execute(tmp_path, config={"report_bytes": 1})
    assert result.report.error == "report" and not result.report_written
    assert not list((tmp_path / "runs").glob("*/report.json"))


def test_interrupted_immutable_link_leaves_prior_readable_and_no_final_success(
    tmp_path,
):
    import os

    initial, _ = execute(tmp_path)
    reference = initial.report.manifest
    _, prior = reopen(tmp_path, reference)
    link = os.link

    def fail_object_link(source, target, **kwargs):
        if target.parent.name == "objects":
            raise OSError(SECRET)
        return link(source, target, **kwargs)

    with patch(
        "outage_explorer.infrastructure.parquet.storage.os.link",
        side_effect=fail_object_link,
    ):
        result, _ = execute(tmp_path, prior=reference)
    assert (
        result.report.error == "prior_integrity" and result.report.outcome == "failed"
    )
    assert result.report_written
    assert not list((tmp_path / "objects").glob(".staging-*"))
    assert reopen(tmp_path, reference)[1] == prior


def test_report_cleanup_failure_does_not_contradict_linked_final_report(tmp_path):
    from pathlib import Path

    initial, _ = execute(tmp_path)
    report = initial.report
    root = tmp_path / "cleanup-check"
    writer = LocalConnectorReports(root, report.run_id, 1000000)
    unlink = Path.unlink

    def fail_report_temp(path, *args, **kwargs):
        if path.name.startswith(".report-"):
            raise OSError("temporary cleanup failed")
        return unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", fail_report_temp):
        writer.finish(report)
    saved = root / "runs" / report.run_id / "report.json"
    assert saved.exists()
    assert '"outcome":"candidate_verified"' in saved.read_text()
