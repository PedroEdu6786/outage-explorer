"""Shared controlled source fixtures for the three-resource candidate suites.

Graph candidate assertions were superseded by test_resource_candidates.py.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from outage_explorer.application.ports.artifacts import ArtifactBounds
from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.domain.refresh import Interval, Origin, RefreshBounds

GRAINS = ("national", "facility", "generator")
WINDOW = Interval(date(2026, 9, 1), date(2026, 9, 3))
BOUNDS = RefreshBounds(1000, 1000, 1000, 15, 1000, 100, 100, 100000, 366, 100000)
ARTIFACT_BOUNDS = ArtifactBounds(100, 100, 2**20, 2**22, 2**29, 10000, 2**18, 20)
ROOT = Path(__file__).resolve().parents[2]


def raw(grain, **changes):
    value = {
        "period": "2026-09-02",
        "capacity": "100",
        "outage": "1.235",
        "percentOutage": "9.875",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
    }
    if grain != "national":
        value.update(facility="0046", facilityName="Example")
    if grain == "generator":
        value["generator"] = "01"
    return {**value, **changes}


def pages(grain, rows, run, interval=WINDOW, page_size=2, total=None):
    position = 0
    for index, offset in enumerate(range(0, len(rows) + page_size, page_size)):
        values = tuple(rows[offset : offset + page_size])
        origin = Origin(
            grain,
            run,
            f"{run}-{grain}",
            f"request-{run}-{grain}-{index}",
            f"page-{run}-{grain}-{index}",
            datetime(2026, 10, 2, tzinfo=UTC),
            index,
            0,
            position,
            "contract-v1",
            "transform-v1",
            f"evidence-{run}-{grain}-{index}",
        )
        yield SanitizedPage(
            origin,
            interval,
            position,
            page_size,
            1,
            total or str(len(rows)),
            grain,
            {"frequency": "daily"},
            {"fixture": True},
            "2.1.14",
            values,
        )
        position += len(values)
        if not values:
            break
