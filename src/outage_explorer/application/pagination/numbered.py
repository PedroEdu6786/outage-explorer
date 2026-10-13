"""Assemble numbered responses from an already retained, addressable result."""

from outage_explorer.application.dto import NumberedPage
from outage_explorer.domain.pagination import (
    numbered_total_pages,
    numbered_window,
    validate_numbered_page,
)


class NumberedPaginator:
    @staticmethod
    def validate(number: int, size: int | None = None) -> None:
        validate_numbered_page(number, size)

    @staticmethod
    def window(number: int, size: int, total_rows: int) -> tuple[int, int]:
        return numbered_window(number, size, total_rows)

    @staticmethod
    def paginate[Row](page: NumberedPage[Row]) -> dict[str, object]:
        numbered_window(page.number, page.size, page.total_rows)
        total_pages = numbered_total_pages(page.size, page.total_rows)
        return {
            **page.metadata,
            "rows": list(page.rows),
            "page": page.number,
            "page_size": page.size,
            "total_pages": total_pages,
            "has_more": page.number < total_pages,
        }
