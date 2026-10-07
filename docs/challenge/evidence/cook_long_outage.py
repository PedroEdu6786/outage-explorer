"""Reproduce the Cook operating outlier from fixed EIA/NRC evidence, offline."""

import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent / "cook-long-outage"
D = Decimal
START, END = date(2008, 1, 1), date(2012, 12, 31)


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def zero_runs(series):
    runs = []
    for unit, observations in sorted(series.items()):
        current = []

        def finish(current=current, unit=unit, observations=observations):
            if not current:
                return
            first, last = current[0], current[-1]
            runs.append(
                {
                    "unit": unit,
                    "first": first.isoformat(),
                    "last": last.isoformat(),
                    "observations": len(current),
                    "complete": (
                        observations.get(first - timedelta(days=1), 0) > 0
                        and observations.get(last + timedelta(days=1), 0) > 0
                    ),
                }
            )

        for day, power in sorted(observations.items()):
            if current and (power != 0 or day != current[-1] + timedelta(days=1)):
                finish()
                current.clear()
            if power == 0:
                current.append(day)
        finish()
    return sorted(runs, key=lambda r: (-r["observations"], r["unit"], r["first"]))


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    packed = (HERE / "sources.json.gz").read_bytes()
    assert hashlib.sha256(packed).hexdigest() == manifest["archive_sha256"]
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        payload = stream.read(30_000_001)
    assert len(payload) <= 30_000_000
    files = json.loads(payload)["files"]
    assert files.keys() == manifest["files"].keys()
    for name, descriptor in manifest["files"].items():
        raw = files[name].encode("utf-8")
        assert len(raw) == descriptor["bytes"]
        assert hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
    source = json.loads(files["eia/manifest.json"])
    assert source["status"] == "retrieved_with_empty_boundaries"
    for name, digest in source["artifacts"].items():
        assert hashlib.sha256(files["eia/" + name].encode()).hexdigest() == digest
    days = [START + timedelta(days=i) for i in range((END - START).days + 1)]
    nrc = defaultdict(dict)
    for year in range(2008, 2013):
        records = csv.DictReader(io.StringIO(files[f"nrc/{year}.txt"]), delimiter="|")
        for record in records:
            day = datetime.strptime(record["ReportDt"].split()[0], "%m/%d/%Y").date()
            unit, power = record["Unit"].strip(), int(record["Power"])
            assert 0 <= power <= 100 and day not in nrc[unit]
            nrc[unit][day] = power
    assert len(nrc) == 104
    assert all(set(observations) == set(days) for observations in nrc.values())
    grains = {}
    for grain, keys in {
        "national": ("period",),
        "facility": ("period", "facility"),
        "generator": ("period", "facility", "generator"),
    }.items():
        rows, offset, previous = {}, 0, None
        for page in source["routes"][grain]["pages"]:
            assert page["offset"] == offset
            doc = json.loads(files["eia/" + page["path"]])
            for row in doc["response"]["data"]:
                key = tuple(row[k] for k in keys)
                order = (key[0], *(int(k) for k in key[1:]))
                assert key not in rows and (previous is None or previous < order)
                previous = order
                c, o, p = (D(row[k]) for k in ("capacity", "outage", "percentOutage"))
                assert all(v.is_finite() for v in (c, o, p))
                assert c > 0 and 0 <= o <= c and 0 <= p <= 100
                assert all(
                    row[f + "-units"] == "megawatts" for f in ("capacity", "outage")
                )
                assert row["percentOutage-units"] == "percent"
                rows[key] = row
            offset += len(doc["response"]["data"])
        assert not doc["response"]["data"]
        assert offset == source["routes"][grain]["received_rows"]
        grains[grain] = rows
    eia_power = defaultdict(dict)
    for day in days:
        period = day.isoformat()
        facility = grains["facility"][period, "6000"]
        generators = [grains["generator"][period, "6000", g] for g in ("1", "2")]
        for row in generators:
            unit = f"D.C. Cook {row['generator']}"
            power = 100 - D(row["percentOutage"])
            assert power == nrc[unit][day]
            assert D(row["outage"]) == D(row["capacity"]) * (100 - power) / 100
            eia_power[unit][day] = power
        for field in ("capacity", "outage"):
            assert sum((D(r[field]) for r in generators), D(0)) == D(facility[field])
        assert (period,) in grains["national"]
    assert len(grains["national"]) == len(grains["facility"]) == len(days)
    assert len(grains["generator"]) == 2 * len(days)
    nrc_runs = zero_runs(nrc)
    completed = [r for r in nrc_runs if r["complete"]]
    event = completed[0]
    assert event == {
        "unit": "D.C. Cook 1",
        "first": "2008-09-21",
        "last": "2009-12-17",
        "observations": 453,
        "complete": True,
    }
    assert event in zero_runs(eia_power)
    daily_controls = []
    for period, expected in (("2008-09-21", 0), ("2009-12-18", 3)):
        parser = Tables()
        parser.feed(files[f"nrc/{period.replace('-', '')}.html"])
        matches = [r for r in parser.rows if r and r[0] == "D.C. Cook 1"]
        assert len(matches) == 1 and int(matches[0][1]) == expected
        assert expected == nrc["D.C. Cook 1"][date.fromisoformat(period)]
        daily_controls.append({"date": period, "power_percent": expected})
    event_html = files["nrc/event-20080920.html"]
    assert "44507" in event_html and "D.C. Cook Unit 1" in event_html
    assert "high vibration" in event_html and "Main Generator Fire" in event_html
    examples = []
    for period in (
        "2008-09-20",
        "2008-09-21",
        "2009-12-17",
        "2009-12-18",
        "2009-12-23",
    ):
        examples.append(
            {
                "date": period,
                "generator": grains["generator"][period, "6000", "1"],
                "facility": grains["facility"][period, "6000"],
                "national": grains["national"][period,],
                "nrc_power_percent": nrc["D.C. Cook 1"][date.fromisoformat(period)],
            }
        )
    report = {
        "source_archive_sha256": manifest["archive_sha256"],
        "interval": [START.isoformat(), END.isoformat()],
        "eia_retrieved_at_utc": source["started_at_utc"],
        "eia_rows": {g: len(rows) for g, rows in grains.items()},
        "nrc_unit_day_observations": sum(len(r) for r in nrc.values()),
        "nrc_units": len(nrc),
        "nrc_zero_power_runs": len(nrc_runs),
        "completed_runs": len(completed),
        "boundary_censored_runs": len(nrc_runs) - len(completed),
        "completed_run_median_observations": median(
            r["observations"] for r in completed
        ),
        "longest_completed_runs": completed[:10],
        "cook_event": event,
        "eia_nrc_cook_comparisons": 2 * len(days),
        "cook_facility_day_reconciliations": len(days),
        "daily_html_controls": daily_controls,
        "examples": examples,
        "limitations": manifest["limitations"],
    }
    print(json.dumps(report, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
