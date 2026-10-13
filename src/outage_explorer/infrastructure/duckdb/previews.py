"""Restricted worker engine. Call only inside the reviewed isolated boundary."""

from datetime import date
from typing import cast

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.execution import (
    ExecutionBounds,
    PreviewRead,
    PreviewRows,
)
from outage_explorer.domain.datasets import (
    PREVIEW_DATE_COLUMN,
)
from outage_explorer.infrastructure.duckdb.views import open_restricted


def _continuation(
    after: tuple[str, ...], identities: tuple[str, ...]
) -> tuple[str, list[object]]:
    if len(after) != 1 + len(identities):
        raise AnalyticalResourceError("Invalid preview key")
    day = date.fromisoformat(after[0])
    if not identities:
        return f"{PREVIEW_DATE_COLUMN} < ?", [day]

    columns = ",".join(f'encode("{name}")' for name in identities)
    values = ",".join("encode(?)" for _ in identities)
    return (
        f"({PREVIEW_DATE_COLUMN} < ? OR "
        f"({PREVIEW_DATE_COLUMN} = ? AND ({columns}) > ({values})))"
    ), [
        day,
        day,
        *after[1:],
    ]


def _preview_query(
    request: PreviewRead,
    names: tuple[str, ...],
    identities: tuple[str, ...],
    exact_filters: tuple[tuple[str, str], ...],
) -> tuple[str, list[object]]:
    predicates: list[str] = []
    parameters: list[object] = []
    if request.start is not None:
        predicates.append(f"{PREVIEW_DATE_COLUMN} >= ?")
        parameters.append(request.start)
    if request.end is not None:
        predicates.append(f"{PREVIEW_DATE_COLUMN} <= ?")
        parameters.append(request.end)
    for column, value in exact_filters:
        predicates.append(f'"{column}" = ?')
        parameters.append(value)
    if request.after is not None:
        predicate, values = _continuation(request.after, identities)
        predicates.append(predicate)
        parameters.extend(values)

    projection = ",".join(f'"{name}"' for name in names)
    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    order = f"{PREVIEW_DATE_COLUMN} DESC" + "".join(
        f',encode("{name}") ASC' for name in identities
    )
    sql = f"SELECT {projection} FROM approved{where} ORDER BY {order} LIMIT ?"
    return sql, [*parameters, request.size + 1]


def _preview_rows(
    output: list[tuple[object, ...]],
    names: tuple[str, ...],
    identities: tuple[str, ...],
    size: int,
) -> PreviewRows:
    rows = tuple(tuple(row) for row in output[:size])
    identity_positions = tuple(names.index(name) for name in identities)
    keys = tuple(
        (
            cast(date, row[0]).isoformat(),
            *(cast(str, row[position]) for position in identity_positions),
        )
        for row in rows
    )
    return PreviewRows(rows, keys, len(output) > size)


def execute_preview(request: PreviewRead, bounds: ExecutionBounds) -> PreviewRows:
    """OS file/network/process isolation is owned by the reviewed launcher."""
    names = tuple(column.name for column in request.dataset.columns)
    identities = request.dataset.preview_identity_columns
    if not request.files or not 1 <= request.size <= 500:
        raise DataUnavailableError("Invalid approved preview inputs")
    connection = open_restricted(bounds, [("approved", request.dataset, request.files)])
    try:
        exact_filters = request.dataset.preview_exact_filters(request.facility)
        sql, parameters = _preview_query(request, names, identities, exact_filters)
        output = connection.execute(sql, parameters).fetchall()
        return _preview_rows(output, names, identities, request.size)
    finally:
        connection.close()
