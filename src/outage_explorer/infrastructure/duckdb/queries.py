"""Bounded result production inside the reviewed worker boundary only."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import duckdb
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.execution import ExecutionBounds, QueryRead
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.domain.datasets import Column
from outage_explorer.infrastructure.query_results.duckdb_types import (
    EngineType,
    value_type,
)
from outage_explorer.infrastructure.query_results.encoding import (
    EncodingBounds,
    EncodingLimit,
    UnsupportedValue,
    retain_result,
)


def execute_query(
    request: QueryRead, bounds: ExecutionBounds, encoding: EncodingBounds
) -> QueryOutput:
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
        for dataset, files in request.relations:
            if not files:
                raise DataUnavailableError("Approved query inputs unavailable")
            for file in files:
                path = Path(file.path)
                if (
                    path.is_symlink()
                    or path.stat().st_size != file.byte_count
                    or hashlib.sha256(path.read_bytes()).hexdigest() != file.sha256
                    or pq.read_schema(path).names
                    != [column.name for column in dataset.columns]
                ):
                    raise DataUnavailableError("Approved query file integrity mismatch")
            connection.from_parquet([file.path for file in files]).create(dataset.id)
        connection.execute("SET enable_external_access = false")
        result = connection.execute(request.sql)
        columns = tuple(
            Column(item[0], value_type(cast(EngineType, item[1])), nullable=None)
            for item in result.description
        )

        def rows() -> Iterator[tuple[object, ...]]:
            while True:
                row = result.fetchone()
                if row is None:
                    return
                yield row

        output = retain_result(columns, rows(), encoding)
        if len(output.document) > bounds.output_bytes:
            raise AnalyticalResourceError("Worker output budget exhausted")
        return QueryOutput(
            output.document, output.retained_row_count, output.truncation_reason
        )
    except (EncodingLimit, UnsupportedValue) as exc:
        raise AnalyticalResourceError(
            "Unsupported or oversized query representation"
        ) from exc
    finally:
        connection.close()
