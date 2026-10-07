"""Controlled subprocess behavior; this is not Docker isolation evidence."""

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal

from outage_explorer.domain.datasets import PUBLIC_DATASETS


def test_worker_query_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "outage_explorer.entrypoints.query_worker_startup"],
        input=json.dumps(
            {
                "version": 1,
                "operation": "query",
                "sql": "SELECT 42 AS answer",
                "relations": [],
            }
        ),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["result"]["columns"][0]["name"] == "answer"
    assert response["result"]["rows"] == [["42"]]


def test_worker_subprocess_fails_safely_without_credentials():
    result = subprocess.run(
        [sys.executable, "-m", "outage_explorer.entrypoints.query_worker_startup"],
        input='{"version":1,"operation":"query","sql":"SELECT * FROM read_csv(\'/secret\')","relations":[]}',
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "unsupported_sql"
    assert "/secret" not in result.stdout


def test_worker_preview_subprocess_checks_real_parquet(tmp_path):
    dataset = PUBLIC_DATASETS[0]
    values = [date(2026, 9, 1), Decimal("100")]
    from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
    from tests.integration.test_connector_parquet import ARTIFACT_BOUNDS, GRAINS
    from tests.integration.test_connector_parquet import raw as source_row
    from tests.integration.test_resource_candidates import build

    store = LocalParquetStore(tmp_path / "source", ARTIFACT_BOUNDS)
    candidate = build(
        store,
        values={
            grain: [
                source_row(
                    grain,
                    period="2026-09-01",
                    capacity="100",
                    outage="10",
                    percentOutage="10",
                )
            ]
            for grain in GRAINS
        },
    )
    original = tmp_path / "fixture.parquet"
    original.write_bytes(b"".join(store.read(candidate.resources[0].object)))
    raw = original.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    original.rename(tmp_path / (digest + ".parquet"))
    payload = {
        "version": 1,
        "operation": "preview",
        "dataset": "national",
        "files": [{"sha256": digest, "byte_count": len(raw), "rows": 1}],
        "start_date": None,
        "end_date": None,
        "after": None,
        "page_size": 100,
    }
    program = """
import sys
from pathlib import Path
from outage_explorer.bootstrap import build_query_worker
from outage_explorer.entrypoints.query_worker import run
raise SystemExit(run(build_query_worker(inputs_root=Path(sys.argv[1])), sys.stdin.buffer, sys.stdout.buffer))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)["result"]
    assert response["rows"][0][0] == "2026-09-01"
    assert Decimal(response["rows"][0][1]) == Decimal("100")
    assert response["keys"] == [["2026-09-01"]]
    assert response["has_more"] is False
    from outage_explorer.application.ports.analytical_inputs import ApprovedFile
    from outage_explorer.application.ports.execution import PreviewRead
    from outage_explorer.infrastructure.worker_runtime.configuration import (
        RuntimeProfile,
    )
    from outage_explorer.infrastructure.worker_runtime.decoding import WorkerTransport

    transport = WorkerTransport(
        RuntimeProfile(
            image_id="sha256:" + "a" * 64,
            daemon_endpoint="unix:///var/run/docker.sock",
            platform="controlled-subprocess",
            daemon_version="not-run",
            filesystem_identity="synthetic",
        )
    )
    decoded = transport.decode(
        result.stdout.encode(),
        request=PreviewRead(
            dataset,
            (ApprovedFile(str(tmp_path / (digest + ".parquet")), digest, len(raw), 1),),
            None,
            None,
            None,
            100,
        ),
        exit_code=result.returncode,
    )
    assert decoded.rows[0][0] == values[0]
    assert decoded.rows[0][1] == values[1]
    assert type(decoded.rows[0][0]) is date
    assert type(decoded.rows[0][1]) is Decimal
    payload["files"][0]["sha256"] = "b" * 64
    rejected = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert rejected.returncode == 1
    assert "fixture.parquet" not in rejected.stdout
    assert "error" in json.loads(rejected.stdout)


def test_real_engine_response_passes_strict_parent_decoder():
    from outage_explorer.application.ports.execution import QueryRead
    from outage_explorer.infrastructure.worker_runtime.configuration import (
        RuntimeProfile,
    )
    from outage_explorer.infrastructure.worker_runtime.decoding import WorkerTransport

    transport = WorkerTransport(
        RuntimeProfile(
            image_id="sha256:" + "a" * 64,
            daemon_endpoint="unix:///var/run/docker.sock",
            platform="controlled-subprocess",
            daemon_version="not-run",
            filesystem_identity="synthetic",
        )
    )
    request = QueryRead(
        "SELECT DATE '2026-09-01' AS same, CAST(10.123456789012 AS DECIMAL(38,12)) AS same, [1,2] AS nested",
        (),
    )
    result = subprocess.run(
        [sys.executable, "-m", "outage_explorer.entrypoints.query_worker_startup"],
        input=transport.request(request),
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = transport.decode(
        result.stdout, request=request, exit_code=result.returncode
    )
    document = json.loads(output.document)
    assert document["rows"] == [["2026-09-01", "10.123456789012", ["1", "2"]]]
    assert document["columns"][0]["name"] == document["columns"][1]["name"] == "same"
    from outage_explorer.infrastructure.query_results.encoding import canonical_json

    assert output.document == canonical_json(json.loads(result.stdout)["result"])


def test_worker_preview_subprocess_projects_public_columns_of_resource_files(tmp_path):
    from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
    from tests.integration.test_connector_parquet import ARTIFACT_BOUNDS
    from tests.integration.test_resource_candidates import build

    store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
    candidate = build(store)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    program = """
import sys
from pathlib import Path
from outage_explorer.bootstrap import build_query_worker
from outage_explorer.entrypoints.query_worker import run
raise SystemExit(run(build_query_worker(inputs_root=Path(sys.argv[1])), sys.stdin.buffer, sys.stdout.buffer))
"""
    for dataset in PUBLIC_DATASETS:
        ref = next(r for r in candidate.resources if r.grain == dataset.grain)
        shutil.copyfile(
            store.root / ref.object.key, inputs / (ref.object.sha256 + ".parquet")
        )
        payload = {
            "version": 1,
            "operation": "preview",
            "dataset": dataset.id,
            "files": [
                {
                    "sha256": ref.object.sha256,
                    "byte_count": ref.object.byte_count,
                    "rows": ref.row_count,
                }
            ],
            "start_date": None,
            "end_date": None,
            "after": None,
            "page_size": 100,
        }
        result = subprocess.run(
            [sys.executable, "-c", program, str(inputs)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        response = json.loads(result.stdout)["result"]
        assert len(response["rows"]) == ref.row_count
        assert [c["name"] for c in response["columns"]] == [
            c.name for c in dataset.columns
        ]
        assert "origin" not in result.stdout
