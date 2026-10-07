"""Replay national seasonality and event windows without network or app imports."""

import calendar
import gzip
import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent / "seasonal-outages"
EVENTS = {
    "2011_tornado_outbreak": ("2011-04-27", "2011-04-28"),
    "2012_hurricane_sandy": ("2012-10-29", "2012-10-30"),
    "2018_hurricane_florence": ("2018-09-13", "2018-09-17"),
    "2024_hurricane_helene": ("2024-09-26", "2024-09-28"),
}


def gw(value):
    return str((value / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def replay():
    archive = (EVIDENCE / "sources.json.gz").read_bytes()
    manifest = json.loads((EVIDENCE / "manifest.json").read_text())
    if hashlib.sha256(archive).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Archive checksum mismatch")
    sources = json.loads(gzip.decompress(archive))
    if set(sources) != set(manifest["sources"]):
        raise ValueError("Source inventory mismatch")
    rows = {}
    for name, expected in manifest["sources"].items():
        raw = sources[name].encode()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
        document = json.loads(raw)
        if document["http_status"] != 200:
            raise ValueError("Unsuccessful recorded source response")
        for row in document["response"]["data"]:
            day = row["period"]
            date.fromisoformat(day)
            if day in rows:
                raise ValueError(f"Duplicate date: {day}")
            capacity, outage = Decimal(row["capacity"]), Decimal(row["outage"])
            if not capacity.is_finite() or not outage.is_finite():
                raise ValueError(f"Nonfinite observation: {day}")
            if capacity <= 0 or not 0 <= outage <= capacity:
                raise ValueError(f"Observation outside checked bounds: {day}")
            if any(
                row[field] != "megawatts"
                for field in ("capacity-units", "outage-units")
            ):
                raise ValueError(f"Unexpected MW units: {day}")
            rows[day] = row
    start, end = date(2007, 1, 1), date(2025, 12, 31)
    expected_days = {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }
    selected = {
        day: row
        for day, row in rows.items()
        if start.isoformat() <= day <= end.isoformat()
    }
    if set(selected) != expected_days:
        raise ValueError("Missing dates in full-year analysis interval")
    monthly = []
    for month in range(1, 13):
        sample = [row for day, row in selected.items() if int(day[5:7]) == month]
        monthly.append(
            {
                "month": calendar.month_abbr[month],
                "observations": len(sample),
                "mean_outage_gw": gw(
                    sum(Decimal(row["outage"]) for row in sample) / len(sample)
                ),
            }
        )
    peaks = []
    for year in range(2007, 2026):
        sample = [
            row for day, row in sorted(selected.items()) if day.startswith(str(year))
        ]
        peak = max(sample, key=lambda row: Decimal(row["outage"]))
        peaks.append({"period": peak["period"], "outage_mw": peak["outage"]})
    events = {}
    for name, days in EVENTS.items():
        events[name] = {
            "observations": [rows[day] for day in days],
            "national_change_mw": str(
                Decimal(rows[days[1]]["outage"]) - Decimal(rows[days[0]]["outage"])
            ),
            "interpretation": "National change; not an estimate of capacity lost because of this event",
        }
    return {
        "scope": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "observations": len(selected),
        },
        "monthly": monthly,
        "annual_peaks": peaks,
        "event_windows": events,
        "limitations": [
            "Saved national observations; not the current published generation or an independent physical measurement.",
            "Daily status includes partial reductions; not full-day averages, lost MWh or household blackouts.",
            "Temporal association does not attribute the entire national change to an event.",
            "No facility/generator reconciliation or quantitative cause decomposition is performed.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(replay(), indent=2))
