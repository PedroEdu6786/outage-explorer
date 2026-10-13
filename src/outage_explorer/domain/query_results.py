"""Fixed result lifetime, page boundaries and accepted whole-result limits."""

from dataclasses import dataclass
from datetime import datetime

from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.pagination import numbered_total_pages, numbered_window

MAX_ROWS = 1000
MAX_BYTES = 1_048_576
# Fixed, unrenewed lifetime shared by preview sequences and retained SQL results
# (ADR-0059; previously 900 seconds under ADR-0015/0020).
LIFETIME_SECONDS = 60


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
        return numbered_total_pages(self.page_size, self.retained_row_count)

    def position(self, page: int) -> tuple[int, int]:
        return numbered_window(page, self.page_size, self.retained_row_count)
