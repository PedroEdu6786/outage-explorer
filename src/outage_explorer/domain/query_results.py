"""Fixed result lifetime, page boundaries and accepted whole-result limits."""

from dataclasses import dataclass
from datetime import datetime

from outage_explorer.domain.access import AnalyticalGrain

MAX_ROWS = 1000
MAX_BYTES = 1_048_576
# Fixed, unrenewed lifetime shared by preview sequences and retained SQL results
# (ADR-0059; previously 900 seconds under ADR-0015/0020).
LIFETIME_SECONDS = 60


def validate_page(page: int, size: int | None = None) -> None:
    if type(page) is not int or page < 1:
        raise ValueError("Positive page required")
    if size is not None and (type(size) is not int or not 1 <= size <= 500):
        raise ValueError("Page size must be between one and 500")


@dataclass(frozen=True)
class ResultIdentity:
    id: str
    owner: str
    grains: frozenset[AnalyticalGrain]
    generation_id: str | None
    page_size: int
    completed_at: datetime
    expires_at: datetime
    retained_row_count: int
    truncation_reason: str | None

    @property
    def total_pages(self) -> int:
        return max(1, (self.retained_row_count + self.page_size - 1) // self.page_size)

    def position(self, page: int) -> tuple[int, int]:
        validate_page(page)
        if page > self.total_pages:
            raise ValueError("Page outside retained range")
        start = (page - 1) * self.page_size
        return start, min(start + self.page_size, self.retained_row_count)
