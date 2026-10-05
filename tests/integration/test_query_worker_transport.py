"""Controlled subprocess behavior; this is not Docker isolation evidence."""

import hashlib
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq

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
    values = [
        date(2026, 9, 1),
        Decimal("100"),
        Decimal("10"),
        Decimal("10"),
        Decimal("10"),
        "1",
        "10",
        "10.00",
        "10.00",
    ]
    fields = []
    arrays = []
    for column, value in zip(dataset.columns, values, strict=True):
        if column.value_type.kind == "decimal":
            dtype = pa.decimal128(column.value_type.precision, column.value_type.scale)
        elif column.value_type.kind == "date":
            dtype = pa.date32()
        else:
            dtype = pa.string()
        fields.append(pa.field(column.name, dtype, nullable=False))
        arrays.append(pa.array([value], type=dtype))
    original = tmp_path / "fixture.parquet"
    pq.write_table(pa.Table.from_arrays(arrays, schema=pa.schema(fields)), original)
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
