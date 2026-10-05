"""Real Parquet and concurrent controlled transport: deterministic route ordering."""

import shutil
import threading
from dataclasses import asdict

import pytest

from outage_explorer.application.ports.source import ROUTES
from tests.integration.test_connector_cli import (
    Wire,
    config_file,
    configuration,
    environment,
    execute,
    execute_connector,
    inputs,
    models,
    reopen,
    row,
)


class OverlappingWire(Wire):
    def __init__(self, rows, *, fault=None):
        self.barrier = threading.Barrier(3, timeout=5)
        self.generator_done = threading.Event()
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.fault = fault
        self.seen = set()
        self.end_order = []
        super().__init__(rows)

    def handle(self, request):
        grain = next(g for g, route in ROUTES.items() if route in request.url.path)
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            first = grain not in self.seen
            self.seen.add(grain)
        try:
            if first:
                self.barrier.wait()
            if grain == "national" and first:
                if self.fault == "interrupt":
                    raise KeyboardInterrupt
                if self.fault == "failure":
                    from outage_explorer.application.ports.source import SourceError

                    raise SourceError("Controlled route failure")
                assert self.generator_done.wait(5)
            result = super().handle(request)
            if (
                request.url.path.endswith("/data/")
                and not result.json()["response"]["data"]
            ):
                self.end_order.append(grain)
                if grain == "generator":
                    self.generator_done.set()
            return result
        finally:
            with self.lock:
                self.active -= 1


def parallel(root, rows, *, prior=None, fault=None, source=None):
    config = configuration()
    config["workers"] = {"endpoint_workers": 3}
    if source:
        config["source"].update(source)
    wire = OverlappingWire(rows, fault=fault)
    result = execute_connector(
        inputs(root, prior, config_path=config_file(root, config)),
        environment=environment(),
        transport=wire,
    )
    assert wire.closed and wire.active == 0
    assert not any(t.name.startswith("connector_") for t in threading.enumerate())
    return result, wire


def comparable(value):
    record = asdict(value)
    # Execution identifiers may change; recorded order/policy/value must not.
    for key in (
        "run_id",
        "retrieval_id",
        "request_id",
        "page_id",
        "raw_object",
        "raw_row",
        "retrieved_at",
        "evidence_id",
    ):
        record["origin"].pop(key, None)
    return record


@pytest.mark.parametrize("retention", ["invalid", "absent"])
def test_endpoint_overlap_reverse_completion_cross_page_conflicts_and_prior(
    tmp_path, retention
):
    first_root, second_root = tmp_path / "sequential", tmp_path / "parallel"
    prior_result, _ = execute(
        first_root,
        {g: [row(g), row(g, period="2026-09-02")] for g in ROUTES},
        config=configuration(),
    )
    prior = prior_result.report.manifest
    shutil.copytree(first_root, second_root)
    rows = {
        grain: [
            row(grain, outage="2"),
            row(grain, outage="1"),
            row(grain, outage="2"),
            row(grain, period="2026-09-02", outage="invalid"),
        ]
        for grain in ROUTES
    }
    if retention == "absent":
        rows = {g: values[:-1] for g, values in rows.items()}
    prior_store, prior_candidate = reopen(first_root, prior)
    sequential, _ = execute(first_root, rows, prior=prior, config=configuration())
    concurrent, wire = parallel(second_root, rows, prior=prior)
    assert (
        concurrent.report.outcome == sequential.report.outcome == "candidate_verified"
    )
    assert wire.peak == 3 and wire.end_order[-1] == "national"
    assert concurrent.report.sources == sequential.report.sources
    assert concurrent.report.models == sequential.report.models
    a_store, a = reopen(first_root, sequential.report.manifest)
    b_store, b = reopen(second_root, concurrent.report.manifest)
    for grain in ROUTES:
        assert [comparable(v) for v in models(a_store, a, grain)] == [
            comparable(v) for v in models(b_store, b, grain)
        ]
    for grain in ROUTES:
        preserved = models(prior_store, prior_candidate, grain)[1]
        assert models(a_store, a, grain)[1] == models(b_store, b, grain)[1] == preserved
    offsets = {grain: [] for grain in ROUTES}
    for call in wire.calls:
        if call.url.path.endswith("/data/"):
            grain = next(g for g, route in ROUTES.items() if route in call.url.path)
            offsets[grain].append(int(call.url.params["offset"]))
    expected = [0, 2, 4] if retention == "invalid" else [0, 2, 3]
    assert all(values == expected for values in offsets.values())


@pytest.mark.parametrize(
    "fault,code", [("failure", "retrieval"), ("interrupt", "interrupted")]
)
def test_failed_or_interrupted_route_joins_workers_and_never_confirms_success(
    tmp_path, fault, code
):
    result, wire = parallel(
        tmp_path / "local", {g: [row(g)] for g in ROUTES}, fault=fault
    )
    assert result.report.error == code
    assert result.report.outcome == "failed" and result.report.manifest is None
    assert wire.peak == 3
    assert not list((tmp_path / "local" / "objects").glob(".staging-*"))


def test_source_requests_are_shared_not_multiplied_by_endpoint_workers(tmp_path):
    # A barrier needs all three metadata requests; the fourth admission exhausts
    # a shared limit rather than granting four attempts to every endpoint.
    result, wire = parallel(
        tmp_path / "local", {g: [row(g)] for g in ROUTES}, source={"requests": 3}
    )
    assert result.report.error == "resource" and result.report.manifest is None
    assert len(wire.calls) <= 3


def test_pipeline_deadline_is_checked_during_modeling_before_late_success(tmp_path):
    from unittest.mock import patch

    from outage_explorer.infrastructure.parquet.candidates import (
        ParquetCandidateBuilder,
    )

    original = ParquetCandidateBuilder.build
    clock = [0.0]

    def expire_then_build(self, *args):
        clock[0] = 1000.0
        return original(self, *args)

    with (
        patch(
            "outage_explorer.infrastructure.connector_workers.time.monotonic",
            side_effect=lambda: clock[0],
        ),
        patch.object(ParquetCandidateBuilder, "build", expire_then_build),
    ):
        result, wire = execute(tmp_path / "expired", config=configuration())
    assert wire.closed
    assert result.report.error == "resource" and result.report.manifest is None
    assert result.report.stage == "modeling"
