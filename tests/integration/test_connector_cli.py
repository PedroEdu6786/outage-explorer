"""CLI through controlled HTTP and real Parquet; no live services or credentials."""

import json
import logging
from dataclasses import asdict
from datetime import date
from fractions import Fraction
from unittest.mock import patch

import httpx
import pytest

from outage_explorer.application.dto import ConnectorInput
from outage_explorer.application.ports.artifacts import ArtifactBounds
from outage_explorer.application.ports.source import ROUTES, SourceBounds
from outage_explorer.bootstrap import execute_connector
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.entrypoints.cli.connector import run
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.resource_metadata import read_candidate

SECRET = "synthetic-only-connector-secret"
SOURCE = SourceBounds(
    30,
    2,
    10000,
    100,
    200,
    1,
    4000,
    100000,
    1000000,
    5000000,
    20,
    20000,
    20000,
    60,
    3,
    1,
)
ARTIFACT = ArtifactBounds(100, 100, 1000000, 2000000, 100000000, 10000, 100000, 25)
MODEL = RefreshBounds(10000, 10000, 10000, 30, 10000, 100, 100, 100000, 30, 100000)


def environment():
    return {"EIA_API_KEY": SECRET}


def configuration(source=SOURCE, artifact=ARTIFACT, model=MODEL, report_bytes=1000000):
    return {
        "source": asdict(source),
        "artifact": asdict(artifact),
        "model": asdict(model),
        "report_bytes": report_bytes,
    }


def config_file(root, config):
    path = root.parent / f"{root.name}-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return str(path)


def row(grain, **changes):
    value = {
        "period": "2026-09-01",
        "capacity": "+3.0000e0",
        "outage": "1",
        "percentOutage": "33.333333333333",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
    }
    if grain != "national":
        value.update(facility="001", facilityName="Exact name ")
    if grain == "generator":
        value["generator"] = "01"
    return value | changes


def inputs(root, prior=None, start="2026-09-01", end="2026-09-02", config_path=None):
    return ConnectorInput(
        start,
        end,
        str(root),
        None if prior is None else report_path(root, prior),
        config_path,
    )


class Wire(httpx.MockTransport):
    def __init__(self, rows=None, *, totals=None, failure=None):
        self.rows = {grain: [row(grain)] for grain in ROUTES} if rows is None else rows
        self.totals, self.failure = totals or {}, failure
        self.calls, self.closed = [], False
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        assert not self.closed
        grain = next(
            grain for grain, route in ROUTES.items() if route in request.url.path
        )
        if request.url.path.endswith("/data/"):
            offset = int(request.url.params["offset"])
            if self.failure == (grain, offset):
                return httpx.Response(400, json={"error": SECRET})
            if callable(self.failure):
                self.failure(grain, offset)
            length = int(request.url.params["length"])
            return httpx.Response(
                200,
                json={
                    "apiVersion": "2.1.14",
                    "request": {"api_key": SECRET},
                    "response": {
                        "frequency": "daily",
                        "total": self.totals.get(grain, str(len(self.rows[grain]))),
                        "data": self.rows[grain][offset : offset + length],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "apiVersion": "2.1.14",
                "request": {
                    "command": f"/v2/nuclear-outages/{ROUTES[grain]}/",
                    "params": [],
                },
                "response": {
                    "id": ROUTES[grain],
                    "frequency": [{"id": "daily"}],
                    "data": {
                        key: {"units": unit}
                        for key, unit in (
                            ("capacity", "megawatts"),
                            ("outage", "megawatts"),
                            ("percentOutage", "percent"),
                        )
                    },
                },
            },
        )

    def close(self):
        self.closed = True
        super().close()


def execute(root, rows=None, *, prior=None, config=None, **wire_options):
    wire = Wire(rows, **wire_options)
    result = execute_connector(
        inputs(
            root,
            prior,
            config_path=None if config is None else config_file(root, config),
        ),
        environment=environment(),
        transport=wire,
    )
    assert wire.closed
    return result, wire


def report_path(root, candidate):
    if isinstance(candidate, (str, type(root))):
        return str(candidate)
    return str(
        next(
            path
            for path in (root / "runs").glob("*/report.json")
            if json.loads(path.read_text())["generation_id"] == candidate.generation_id
        )
    )


def reopen(root, reference):
    store = LocalParquetStore(root / "objects", ARTIFACT)
    candidate = read_candidate(reference) if isinstance(reference, str) else reference
    with patch(
        "outage_explorer.infrastructure.eia.source.EiaSource.__init__",
        side_effect=AssertionError("Reopen accessed EIA"),
    ):
        LocalConnectorEvidence(store).verify_candidate(candidate, MODEL)
    return store, candidate


def models(store, candidate, grain):
    return [
        modeled_from_record(value, grain)
        for ref in candidate.resources
        if ref.grain == grain
        for value in store.records(ref)
    ]


def test_cli_multipage_preserves_exact_values_and_quality(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    rows = {}
    for grain in ROUTES:
        rows[grain] = [
            row(grain),
            row(grain, outage="2"),
            row(grain),
            row(grain, capacity="bad"),
            row(grain, period="2026-09-02", outage="0"),
        ]
    wire = Wire(rows, totals={"facility": "2850"})
    outcomes = []

    def invoke(parameters):
        result = execute_connector(
            parameters, environment=environment(), transport=wire
        )
        outcomes.append(result)
        return result

    assert (
        run(
            invoke,
            [
                "--local-only",
                "--config",
                config_file(tmp_path, {"source": {"page_rows": 2}}),
                "--start",
                "2026-09-01",
                "--end",
                "2026-09-02",
                "--staging",
                str(tmp_path),
            ],
        )
        == 0
    )
    result = outcomes[0]
    assert result.report.outcome == "candidate_verified"
    assert result.report_written and wire.closed
    assert not result.report.published
    # Reopening has no source factory or HTTP dependency.
    store, candidate = reopen(tmp_path, result.report.candidate)
    for grain in ROUTES:
        modeled = models(store, candidate, grain)
        assert modeled[0].result.percentage == Fraction(100, 3)
        assert modeled[1].result.percentage == 0
        assert modeled[0].origin.source_position == 2
        assert modeled[0].origin.page_index == 1
        assert modeled[0].origin.run_id == result.report.run_id
        assert dict(modeled[0].observation.original)["capacity"] == "+3.0000e0"
    for quality in candidate.summaries:
        q = quality.quality
        assert (q.received, q.selected, q.excluded, q.duplicate, q.superseded) == (
            5,
            2,
            1,
            1,
            1,
        )
    report_path = tmp_path / "runs" / result.report.run_id / "report.json"
    report = json.loads(report_path.read_text())
    facility = next(item for item in report["sources"] if item["grain"] == "facility")
    assert facility["advertised_totals"] == ["2850"] * 4
    assert facility["received"] == 5 and facility["count_mismatch"]
    assert facility["upstream_completeness"] == "unverified"
    assert [request.url.path for request in wire.calls] == sorted(
        [request.url.path for request in wire.calls],
        key=lambda path: list(ROUTES.values()).index(
            next(route for route in ROUTES.values() if route in path)
        ),
    )
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
    output = capsys.readouterr()
    assert SECRET not in caplog.text + output.out + output.err
    assert "api_key" not in output.err and "Exact name" not in output.err
    steps = [
        "resource_candidate_started",
        "eia_metadata_verified",
        "eia_page_collected",
        "resource_candidate_complete",
    ]
    assert [output.err.index(step) for step in steps] == sorted(
        output.err.index(step) for step in steps
    )
    assert "route=facility-nuclear-outages" in output.err


@pytest.mark.parametrize("total", ["2850", "2"])
def test_facility_mismatch_nonblocking_but_failed_page_fails(tmp_path, total):
    rows = {grain: [row(grain), row(grain, period="2026-09-02")] for grain in ROUTES}
    result, _ = execute(tmp_path / "good", rows, totals={"facility": total})
    assert result.report.outcome == "candidate_verified"
    failed, _ = execute(
        tmp_path / "bad", rows, totals={"facility": total}, failure=("facility", 2)
    )
    assert failed.report.error == "retrieval"
    assert failed.report.candidate is None


def test_grains_calculate_independently(tmp_path):
    rows = {
        grain: [row(grain, capacity=capacity, outage=outage)]
        for grain, capacity, outage in (
            ("national", "3", "1"),
            ("facility", "100", "50"),
            ("generator", "7", "0"),
        )
    }
    result, _ = execute(tmp_path, rows)
    store, candidate = reopen(tmp_path, result.report.candidate)
    assert [
        models(store, candidate, grain)[0].result.percentage for grain in ROUTES
    ] == [Fraction(100, 3), Fraction(50), Fraction(0)]


def test_cli_candidate_stores_exactly_three_unified_resource_files(tmp_path):
    rows = {
        grain: [row(grain, period="2026-09-01"), row(grain, period="2026-09-02")]
        for grain in ROUTES
    }
    result, _ = execute(tmp_path, rows)
    store, candidate = reopen(tmp_path, result.report.candidate)
    assert [(ref.kind, ref.grain, ref.partition) for ref in candidate.resources] == [
        ("resource", grain, None) for grain in ROUTES
    ]
    assert all(ref.row_count == 2 for ref in candidate.resources)
    assert candidate.schema_version == "1" and candidate.base_generation_id is None
    assert [(item.first_period, item.last_period) for item in candidate.summaries] == [
        (date(2026, 9, 1), date(2026, 9, 2))
    ] * 3
    assert {path.name for path in store.root.iterdir()} == {
        ref.object.key for ref in candidate.resources
    }


def test_cli_failure_and_configuration_exit_codes(tmp_path, capsys):
    wire = Wire(failure=("national", 0))
    assert (
        run(
            lambda params: execute_connector(
                params, environment=environment(), transport=wire
            ),
            [
                "--local-only",
                "--start",
                "2026-09-01",
                "--end",
                "2026-09-02",
                "--staging",
                str(tmp_path),
            ],
        )
        == 1
    )
    assert "retrieval" in capsys.readouterr().out
    assert (
        run(
            lambda params: execute_connector(params, environment={}),
            [
                "--local-only",
                "--start",
                "bad",
                "--end",
                "2026-09-02",
                "--staging",
                str(tmp_path),
            ],
        )
        == 2
    )
    assert "configuration" in capsys.readouterr().out


def test_invalid_config_precedes_storage_or_transport(tmp_path):
    root = tmp_path / "never-created"
    wire = Wire()
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        execute_connector(
            inputs(root),
            environment={},
            transport=wire,
        )
    assert not root.exists() and not wire.calls and wire.closed


def test_recorded_facility_total_discrepancy_is_visible_without_inventing_rows(
    tmp_path,
):
    rows = {grain: [row(grain)] for grain in ROUTES}
    rows["facility"] = [
        row("facility", facility=f"{index:04d}") for index in range(1650)
    ]
    config = {"source": {"page_rows": 1000, "response_bytes": 1000000}}
    result, _ = execute(tmp_path, rows, totals={"facility": "2850"}, config=config)
    assert result.report.outcome == "candidate_verified"
    source = next(item for item in result.report.sources if item.grain == "facility")
    assert source.advertised_totals == ("2850", "2850", "2850")
    assert source.received == 1650 and source.count_mismatch
    assert (
        next(
            item
            for item in result.report.candidate.summaries
            if item.grain == "facility"
        ).candidate_count
        == 1650
    )


def test_help_needs_neither_credentials_nor_executor(capsys):
    def forbidden(_):
        raise AssertionError("help invoked connector")

    with pytest.raises(SystemExit) as error:
        run(forbidden, ["--help"])
    assert error.value.code == 0 and "never publishes" in capsys.readouterr().out


def test_argument_errors_do_not_echo_supplied_secrets(capsys):
    with pytest.raises(SystemExit) as error:
        run(lambda _: pytest.fail("executor called"), ["--api-key", SECRET])
    assert error.value.code == 2
    assert SECRET not in capsys.readouterr().err


@pytest.mark.parametrize("override_flags", [False, True])
def test_cli_file_configuration_and_run_flag_precedence(tmp_path, override_flags):
    root = tmp_path / "staging"
    file_root = tmp_path / "file-staging"
    path = config_file(
        root,
        {
            "start": "2026-09-01",
            "end": "2026-09-01" if override_flags else "2026-09-02",
            "staging": str(file_root if override_flags else root),
            "source": {"page_rows": 1},
        },
    )
    wire = Wire(
        {grain: [row(grain), row(grain, period="2026-09-02")] for grain in ROUTES}
    )
    outcomes = []

    def invoke(parameters):
        result = execute_connector(
            parameters, environment=environment(), transport=wire
        )
        outcomes.append(result)
        return result

    flags = ["--local-only", "--config", path]
    if override_flags:
        flags += ["--end", "2026-09-02", "--staging", str(root)]
    assert run(invoke, flags) == 0
    result = outcomes[0]
    assert result.report.outcome == "candidate_verified" and wire.closed
    assert result.report.interval.end.isoformat() == "2026-09-02"
    assert not file_root.exists()
    requests = [
        request for request in wire.calls if request.url.path.endswith("/data/")
    ]
    assert all(request.url.params["length"] == "1" for request in requests)
    _, candidate = reopen(root, result.report.candidate)
    assert all(quality.quality.received == 2 for quality in candidate.summaries)


@pytest.mark.parametrize(
    "document", [None, '{"api_key":"SECRET"}', '{"source":{"rows":true}}']
)
def test_bad_config_file_exits_two_without_io_or_secret_echo(
    tmp_path, capsys, document
):
    path = tmp_path / f"{SECRET}.json"
    if document is not None:
        path.write_text(document.replace("SECRET", SECRET))
    wire = Wire()
    root = tmp_path / "never-created"
    assert (
        run(
            lambda params: execute_connector(
                params, environment=environment(), transport=wire
            ),
            [
                "--config",
                str(path),
                "--local-only",
                "--start",
                "2026-09-01",
                "--end",
                "2026-09-02",
                "--staging",
                str(root),
            ],
        )
        == 2
    )
    assert wire.closed and not wire.calls and not root.exists()
    output = capsys.readouterr()
    assert "configuration" in output.out and SECRET not in output.out + output.err


def test_help_does_not_open_even_an_explicit_config_file(capsys):
    with patch("pathlib.Path.open", side_effect=AssertionError("config file read")):
        with pytest.raises(SystemExit) as error:
            run(execute_connector, ["--config", "missing.json", "--help"])
    assert error.value.code == 0 and "--config" in capsys.readouterr().out


def test_cli_logging_restores_configuration_after_failure_and_help(capsys):
    logger = logging.getLogger("outage_explorer.connector")
    original = (logger.level, logger.propagate, list(logger.handlers))

    def failed(_):
        raise RuntimeError(SECRET)

    assert (
        run(failed, ["--local-only", "--start", "2026-09-01", "--end", "2026-09-01"])
        == 1
    )
    output = capsys.readouterr()
    assert "connector_failed code=internal" in output.err
    assert SECRET not in output.err + output.out
    assert (logger.level, logger.propagate, list(logger.handlers)) == original
    with pytest.raises(SystemExit):
        run(failed, ["--help"])
    assert capsys.readouterr().err == ""
    assert (logger.level, logger.propagate, list(logger.handlers)) == original


def test_cli_rejects_insufficient_aggregate_worker_memory_before_source(
    tmp_path, capsys
):
    root = tmp_path / "worker-limits"
    path = config_file(root, {"workers": {"endpoint_workers": 3, "memory_bytes": 1}})
    wire = Wire()
    result = run(
        lambda request: execute_connector(
            request, environment=environment(), transport=wire
        ),
        [
            "--local-only",
            "--start",
            "2026-09-01",
            "--end",
            "2026-09-02",
            "--staging",
            str(root),
            "--config",
            path,
        ],
    )
    assert result == 2
    assert wire.closed and not wire.calls and not root.exists()
    assert SECRET not in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--fetch-workers", "--s3-workers"])
@pytest.mark.parametrize("value", ["0", "4", "synthetic-secret"])
def test_cli_worker_arguments_fail_before_executor_without_echo(flag, value, capsys):
    with pytest.raises(SystemExit) as error:
        run(lambda _: pytest.fail("executor invoked"), [flag, value])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.err + captured.out


def test_make_forwards_page_and_s3_overrides_without_json():
    import subprocess

    result = subprocess.run(
        [
            "make",
            "-n",
            "connector",
            "START=2026-04-02",
            "END=2026-10-01",
            "FETCH_WORKERS=3",
            "S3_WORKERS=3",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--fetch-workers '3'" in result.stdout
    assert "--s3-workers '3'" in result.stdout
    assert "--config" not in result.stdout


def test_cli_worker_override_dtos_for_candidate_and_recovery(tmp_path):
    from dataclasses import replace

    from outage_explorer.application.dto import ConnectorArtifactInput
    from outage_explorer.application.ports.connector import DurableResourceReceipt

    seen = []
    result, _ = execute(tmp_path / "candidate-input")

    def candidate(request):
        seen.append(request)
        return result

    assert (
        run(candidate, ["--local-only", "--fetch-workers", "3", "--s3-workers", "2"])
        == 0
    )
    assert seen[0].fetch_workers == 3 and seen[0].s3_workers == 2
    candidate_result = result.report.candidate
    reference = "receipt.json"

    def recover(request):
        seen.append(request)
        return DurableResourceReceipt(
            generation_id=candidate_result.generation_id,
            resources=tuple(
                replace(
                    ref,
                    object=replace(
                        ref.object,
                        key=f"generations/{candidate_result.generation_id}/{name}.parquet",
                    ),
                )
                for ref, name in zip(
                    candidate_result.resources,
                    ("national", "facilities", "generators"),
                    strict=True,
                )
            ),
            interval=candidate_result.interval,
            contract_id=candidate_result.contract_id,
            transformation_id=candidate_result.transformation_id,
            base_generation_id=None,
        )

    assert (
        run(
            candidate,
            [
                "--operation",
                "recover",
                "--resources",
                reference,
                "--s3-workers",
                "3",
            ],
            execute_artifacts=recover,
        )
        == 0
    )
    assert isinstance(seen[1], ConnectorArtifactInput) and seen[1].s3_workers == 3
