"""Assemble bounded cursor pages from an endpoint's already bounded read.

The endpoint owns filtering, ordering, authorization and snapshot lifetime.
This component knows only rows, their continuation keys, and response metadata.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from outage_explorer.application.errors import AnalyticalResourceError


@dataclass(frozen=True)
class CursorPage[Row, Key]:
    rows: tuple[Row, ...]
    keys: tuple[Key, ...]
    has_more: bool
    size: int
    after: Key | None
    cursor: Callable[[Key | None], str]
    metadata: Mapping[str, object]


class CursorPaginator:
    def __init__(
        self, measure_bytes: Callable[[object], int], *, response_bytes: int
    ) -> None:
        if type(response_bytes) is not int or response_bytes <= 0:
            raise ValueError("Positive response byte bound required")
        self._measure_bytes = measure_bytes
        self._response_bytes = response_bytes

    def paginate[Row, Key](self, page: CursorPage[Row, Key]) -> dict[str, object]:
        if len(page.rows) != len(page.keys):
            raise AnalyticalResourceError("Each row must have a continuation key")
        if len(page.rows) > page.size:
            raise AnalyticalResourceError("Read exceeds page size")
        if page.has_more and not page.rows:
            raise AnalyticalResourceError("Continuation requires a row to advance")

        current_cursor = page.cursor(page.after)
        minimum_rows = 1 if page.rows else 0
        for count in range(len(page.rows), minimum_rows - 1, -1):
            has_more = page.has_more or count < len(page.rows)
            next_cursor = page.cursor(page.keys[count - 1]) if has_more else None
            response: dict[str, object] = {
                **page.metadata,
                "rows": list(page.rows[:count]),
                "page_size": page.size,
                "page_cursor": current_cursor,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
            if self._measure_bytes(response) <= self._response_bytes:
                return response
        raise AnalyticalResourceError("Row or envelope exceeds response byte bound")
