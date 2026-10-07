"""Restricted DuckDB connections whose datasets are views over exact staged files.

No base table is created: each dataset is a view over ``read_parquet`` on the
approved files, so reads scan them directly. A unified resource file keeps private
provenance columns; the view projects exactly the dataset's public columns, so no
private physical column is nameable. After setup the engine may read only those
exact paths, external access is off and its configuration is locked.
Container mounts remain the primary isolation boundary.
"""

import hashlib
from collections.abc import Sequence
from pathlib import Path

import duckdb
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.errors import DataUnavailableError
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.execution import ExecutionBounds
from outage_explorer.domain.datasets import Dataset
from outage_explorer.infrastructure.parquet.schemas import schema_for


def verify_approved_file(file: ApprovedFile, dataset: Dataset) -> None:
    path = Path(file.path)
    if (
        path.is_symlink()
        or path.stat().st_size != file.byte_count
        or hashlib.sha256(path.read_bytes()).hexdigest() != file.sha256
    ):
        raise DataUnavailableError("Approved input file integrity mismatch")
    if not pq.read_schema(path).equals(
        schema_for("resource", dataset.grain), check_metadata=True
    ):
        raise DataUnavailableError("Approved input file integrity mismatch")


def _literal(path: str) -> str:
    if "\x00" in path:
        raise DataUnavailableError("Invalid approved input path")
    return "'" + path.replace("'", "''") + "'"


def open_restricted(
    bounds: ExecutionBounds,
    relations: Sequence[tuple[str, Dataset, Sequence[ApprovedFile]]],
) -> duckdb.DuckDBPyConnection:
    paths: list[str] = []
    for _, dataset, approved in relations:
        if not approved:
            raise DataUnavailableError("Approved inputs unavailable")
        for file in approved:
            verify_approved_file(file, dataset)
            paths.append(file.path)
    connection = duckdb.connect(
        config={
            "allow_unsigned_extensions": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "threads": "1",
            "memory_limit": f"{bounds.memory_bytes}B",
            "max_temp_directory_size": f"{bounds.temporary_bytes}B",
        }
    )
    try:
        connection.execute(
            "SET allowed_paths = [" + ",".join(_literal(p) for p in paths) + "]"
        )
        for name, dataset, approved in relations:
            connection.read_parquet([file.path for file in approved]).project(
                ", ".join(f'"{column.name}"' for column in dataset.columns)
            ).create_view(name)
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
    except BaseException:
        connection.close()
        raise
    return connection
