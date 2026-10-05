"""Restricted worker engine. Call only inside the reviewed isolated boundary."""

import hashlib
from datetime import date
from pathlib import Path
from typing import cast

import duckdb
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.execution import (
    ExecutionBounds,
    PreviewRead,
    PreviewRows,
)


def execute_preview(request: PreviewRead, bounds: ExecutionBounds) -> PreviewRows:
    """OS file/network/process isolation is owned by the reviewed launcher."""
    columns = request.dataset.columns
    names = [col.name for col in columns]
    identities = [name for name in ("facility", "generator") if name in names]
    if not request.files or not 1 <= request.size <= 500:
        raise DataUnavailableError("Invalid approved preview inputs")
    for file in request.files:
        path = Path(file.path)
        if (
            path.is_symlink()
            or path.stat().st_size != file.byte_count
            or hashlib.sha256(path.read_bytes()).hexdigest() != file.sha256
            or pq.read_schema(path).names != names
        ):
            raise DataUnavailableError("Approved preview file integrity mismatch")
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
        connection.from_parquet([file.path for file in request.files]).create(
            "approved"
        )
        connection.execute("SET enable_external_access = false")
        predicates: list[str] = []
        values: list[object] = []
        for value, operator in ((request.start, ">="), (request.end, "<=")):
            if value is not None:
                predicates.append(f"period {operator} ?")
                values.append(value)
        if request.after is not None:
            if len(request.after) != 1 + len(identities):
                raise AnalyticalResourceError("Invalid preview key")
            day = date.fromisoformat(request.after[0])
            if identities:
                lhs = ",".join(f'encode("{name}")' for name in identities)
                rhs = ",".join("encode(?)" for _ in identities)
                predicates.append(f"(period < ? OR (period = ? AND ({lhs}) > ({rhs})))")
                values.extend([day, day, *request.after[1:]])
            else:
                predicates.append("period < ?")
                values.append(day)
        projection = ",".join(f'"{name}"' for name in names)
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        order = "period DESC" + "".join(f',encode("{name}") ASC' for name in identities)
        output = connection.execute(
            f"SELECT {projection} FROM approved{where} ORDER BY {order} LIMIT ?",
            [*values, request.size + 1],
        ).fetchall()
        rows = tuple(tuple(row) for row in output[: request.size])
        keys = tuple(
            (
                cast(date, row[0]).isoformat(),
                *(cast(str, row[names.index(name)]) for name in identities),
            )
            for row in rows
        )
        return PreviewRows(rows, keys, len(output) > request.size)
    finally:
        connection.close()
