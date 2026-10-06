"""Bounded result production inside the reviewed worker boundary only."""

from collections.abc import Iterator
from typing import cast

from outage_explorer.application.errors import AnalyticalResourceError
from outage_explorer.application.ports.execution import ExecutionBounds, QueryRead
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.domain.datasets import Column
from outage_explorer.infrastructure.duckdb.views import open_restricted
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
    connection = open_restricted(
        bounds, [(dataset.id, dataset, files) for dataset, files in request.relations]
    )
    try:
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
