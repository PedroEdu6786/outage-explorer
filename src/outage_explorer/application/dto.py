"""Transport-independent application results."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class HealthStatus:
    checked_at: datetime
    status: Literal["ok"] = "ok"
    service: str = "outage-explorer"
