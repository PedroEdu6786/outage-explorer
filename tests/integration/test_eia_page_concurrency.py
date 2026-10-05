"""Parallel requests within one route, canonical replay and audited lookahead."""

import json
import threading
from dataclasses import replace

import httpx
import pytest

from outage_explorer.application.dto import ConnectorArtifactInput
from outage_explorer.application.ports.artifacts import ArtifactError
from outage_explorer.application.ports.source import ROUTES
from outage_explorer.bootstrap import execute_connector, execute_connector_artifacts
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.evidence import verify_evidence
from tests.integration.test_connector_artifacts import ENV
from tests.integration.test_connector_cli import (
    MODEL,
    Wire,
    config_file,
    configuration,
    environment,
    execute,
    inputs,
    models,
    reopen,
    row,
)
from tests.integration.test_connector_concurrency import comparable
from tests.integration.test_s3_artifacts import ControlledS3


class PageWire(Wire):
    def __init__(self, rows, *, short=False, fault=None):
        self.barrier = threading.Barrier(3, timeout=5)
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.completed = []
        self.short, self.fault = short, fault
        self.first = set()
        super().__init__(rows, totals={"facility": "99999"})

    def handle(self, request):
        if not request.url.path.endswith("/data/"):
            return super().handle(request)
        grain = next(g for g, route in ROUTES.items() if route in request.url.path)
        offset = int(request.url.params["offset"])
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            first = (grain, offset) not in self.first
            self.first.add((grain, offset))
        try:
            if grain == "national" and offset in (0, 2, 4) and first:
                self.barrier.wait()
                if offset == 0:
                    assert self.release.wait(5)
                if offset == 4:
                    self.release.set()
            if grain == "national" and offset == 4 and self.fault:
                if self.fault == "interrupt":
                    raise KeyboardInterrupt
                return httpx.Response(
                    400, json={"error": "synthetic-only-connector-secret"}
                )
            response = super().handle(request)
            if self.short and offset == 0:
                content = response.json()
                content["response"]["data"] = content["response"]["data"][:1]
                response = httpx.Response(200, json=content)
            with self.lock:
                self.completed.append((grain, offset))
            return response
        finally:
            with self.lock:
                self.active -= 1


def run_parallel(root, rows, **options):
    source = options.pop("source", {})
    wire = PageWire(rows, **options)
    config = configuration()
    config["source"].update(source)
    config["workers"] = {"page_workers": 3}
    result = execute_connector(
        inputs(root, config_path=config_file(root, config)),
        environment=environment(),
        transport=wire,
    )
    assert wire.closed and wire.active == 0
    assert not any(t.name.startswith("connector_") for t in threading.enumerate())
    return result, wire


def test_same_route_overlap_reverse_completion_conflicts_and_transport_graph_recovery(
    tmp_path,
):
    rows = {g: [row(g, outage=v) for v in ["1", "2", "1", "3", "2"]] for g in ROUTES}
    sequential, _ = execute(
        tmp_path / "seq", rows, totals={"facility": "99999"}, config=configuration()
    )
    parallel, wire = run_parallel(tmp_path / "parallel", rows)
    assert parallel.report.outcome == "candidate_verified"
    assert wire.peak == 3
    assert wire.completed.index(("national", 4)) < wire.completed.index(("national", 0))
    a_store, a = reopen(tmp_path / "seq", sequential.report.manifest)
    b_store, b = reopen(tmp_path / "parallel", parallel.report.manifest)
    assert parallel.report.sources == sequential.report.sources
    assert parallel.report.models == sequential.report.models
    for grain in ROUTES:
        assert [comparable(v) for v in models(a_store, a, grain)] == [
            comparable(v) for v in models(b_store, b, grain)
        ]
    assert all(bundle.transport for bundle in b.evidence)
    graph = LocalConnectorEvidence(b_store).graph(parallel.report.manifest, MODEL)
    assert all(ref in graph for bundle in b.evidence for ref in bundle.transport)
    client = ControlledS3()
    cfg = config_file(tmp_path / "transfer", {"workers": {"s3_workers": 1}})
    for operation, root in [
        ("persist", tmp_path / "parallel"),
        ("recover", tmp_path / "restored"),
    ]:
        receipt = execute_connector_artifacts(
            ConnectorArtifactInput(
                operation,
                str(root),
                f"{parallel.report.manifest.key}:{parallel.report.manifest.byte_count}",
                cfg,
                3,
            ),
            environment=ENV,
            client=client,
        )
        assert receipt.objects == len(graph)
    _, restored = reopen(tmp_path / "restored", parallel.report.manifest)
    assert restored == b
    assert all(body.closed for body in client.closed_bodies)


def test_short_page_repairs_offset_and_audits_unused_successes_and_terminal(tmp_path):
    rows = {g: [row(g, outage=v) for v in ["1", "2", "1", "3", "2"]] for g in ROUTES}
    result, wire = run_parallel(tmp_path / "short", rows, short=True)
    assert result.report.outcome == "candidate_verified"
    store, candidate = reopen(tmp_path / "short", result.report.manifest)
    for bundle in candidate.evidence:
        pages = [record for ref in bundle.pages for record in store.records(ref)]
        assert [p["offset"] for p in pages] == [0, 1, 3, 5]
        assert sum(p["returned_count"] for p in pages) == 5
        assert pages[-1]["returned_count"] == 0
        audits = [json.loads(b"".join(store.read(ref))) for ref in bundle.transport]
        assert any(
            not item["used"] and item["envelope"]["response"]["data"] for item in audits
        )
        assert sum(len(item["envelope"]["response"]["data"]) for item in audits) > 5
        assert (
            len(
                [
                    item
                    for item in audits
                    if item["used"] and not item["envelope"]["response"]["data"]
                ]
            )
            == 1
        )
        assert bundle.transport


@pytest.mark.parametrize(
    "fault,code", [("failure", "retrieval"), ("interrupt", "interrupted")]
)
def test_admitted_failed_lookahead_even_after_short_page_never_confirms_success(
    tmp_path, fault, code
):
    rows = {g: [row(g)] for g in ROUTES}
    result, wire = run_parallel(tmp_path / "failure", rows, fault=fault)
    assert result.report.outcome == "failed" and result.report.manifest is None
    assert result.report.error == code
    assert not list((tmp_path / "failure").rglob(".staging-*"))


def test_supplemental_corruption_and_missing_dependency_fail_replay(tmp_path):
    result, _ = run_parallel(tmp_path / "audit", {g: [row(g)] for g in ROUTES})
    store, candidate = reopen(tmp_path / "audit", result.report.manifest)
    bundle = candidate.evidence[0]
    with pytest.raises(ArtifactError):
        verify_evidence(store, replace(bundle, transport=bundle.transport[:-1]))
    path = store.root / bundle.transport[-1].key
    path.write_bytes(b"corrupt audit")
    with pytest.raises(ArtifactError):
        LocalConnectorEvidence(store).reopen(result.report.manifest, MODEL)


def test_short_page_unused_rows_are_charged_to_shared_fetch_budget(tmp_path):
    rows = {g: [row(g, outage=v) for v in ["1", "2", "1", "3", "2"]] for g in ROUTES}
    result, _ = run_parallel(tmp_path / "bounds", rows, short=True, source={"rows": 5})
    assert result.report.outcome == "failed" and result.report.error == "resource"
    assert result.report.manifest is None


def test_rehashed_supplemental_value_cannot_replace_canonical_raw_evidence(tmp_path):
    from dataclasses import asdict

    result, _ = run_parallel(tmp_path / "forged", {g: [row(g)] for g in ROUTES})
    store, candidate = reopen(tmp_path / "forged", result.report.manifest)
    bundle = candidate.evidence[0]
    original = bundle.transport[0]
    value = json.loads(b"".join(store.read(original)))
    value["envelope"]["response"]["data"][0]["outage"] = "3"
    forged = store.put_immutable((json.dumps(value).encode(),))
    first_page = bundle.pages[0]
    record = next(store.records(first_page))
    metadata = json.loads(record["metadata_json"])
    metadata["transport_refs"][0] = asdict(forged)
    record["metadata_json"] = json.dumps(metadata)
    rewritten = store.write("pages", bundle.grain, None, [record])
    changed = replace(
        bundle,
        pages=(*rewritten, *bundle.pages[1:]),
        transport=(forged, *bundle.transport[1:]),
    )
    with pytest.raises(
        ArtifactError, match="Supplemental canonical raw value mismatch"
    ):
        verify_evidence(store, changed)


def test_parallel_pages_preserve_invalid_and_absent_prior_origins(tmp_path):
    import shutil

    roots = [tmp_path / "seq-retained", tmp_path / "parallel-retained"]
    prior_rows = {g: [row(g), row(g, period="2026-09-02")] for g in ROUTES}
    initial, _ = execute(roots[0], prior_rows, config=configuration())
    prior = initial.report.manifest
    shutil.copytree(roots[0], roots[1])
    incoming = {
        g: [row(g, outage="2"), row(g, outage="1"), row(g, outage="3")] for g in ROUTES
    }
    incoming["national"].append(row("national", period="2026-09-02", outage="invalid"))
    sequential, _ = execute(roots[0], incoming, prior=prior, config=configuration())
    wire = PageWire(incoming)
    cfg = configuration()
    cfg["workers"] = {"page_workers": 3}
    parallel = execute_connector(
        inputs(roots[1], prior, config_path=config_file(roots[1], cfg)),
        environment=environment(),
        transport=wire,
    )
    assert parallel.report.outcome == sequential.report.outcome == "candidate_verified"
    a_store, a = reopen(roots[0], sequential.report.manifest)
    b_store, b = reopen(roots[1], parallel.report.manifest)
    prior_store, original = reopen(roots[0], prior)
    for grain in ROUTES:
        assert (
            models(a_store, a, grain)[1]
            == models(b_store, b, grain)[1]
            == models(prior_store, original, grain)[1]
        )
    assert wire.closed and not any(
        t.name.startswith("connector_") for t in threading.enumerate()
    )


def test_nested_endpoint_page_failure_joins_every_worker(tmp_path):
    wire = Wire({g: [row(g)] for g in ROUTES}, failure=("national", 4))
    config = configuration()
    config["workers"] = {"endpoint_workers": 3, "page_workers": 3}
    result = execute_connector(
        inputs(
            tmp_path / "nested", config_path=config_file(tmp_path / "nested", config)
        ),
        environment=environment(),
        transport=wire,
    )
    assert result.report.outcome == "failed" and result.report.manifest is None
    assert wire.closed and not any(
        t.name.startswith("connector_") for t in threading.enumerate()
    )


def test_parallel_supplemental_and_canonical_artifacts_never_store_credentials(
    tmp_path,
):
    from tests.integration.test_connector_cli import SECRET

    rows = {g: [row(g), row(g, period="2026-09-02", outage=SECRET)] for g in ROUTES}
    result, _ = run_parallel(tmp_path / "secret", rows)
    assert result.report.outcome == "candidate_verified"
    assert all(
        SECRET.encode() not in path.read_bytes()
        for path in (tmp_path / "secret" / "objects").iterdir()
    )
