"""Replay fixed historical EIA/NRC evidence; no network or product execution."""

import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent / "historical-omissions"
D = Decimal


class Tables(HTMLParser):
    """Read NRC table cells without interpreting markup as executable content."""

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


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    compressed = (HERE / "sources.json.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == manifest["archive_sha256"]
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        payload = stream.read(30_000_001)
    assert len(payload) <= 30_000_000
    files = json.loads(payload)["files"]
    assert files.keys() == manifest["files"].keys()
    for name, descriptor in manifest["files"].items():
        raw = files[name].encode("utf-8")
        assert len(raw) == descriptor["bytes"], name
        assert hashlib.sha256(raw).hexdigest() == descriptor["sha256"], name

    nrc = {}
    for year in ("2007", "2013", "2015"):
        records = csv.DictReader(io.StringIO(files[f"nrc/{year}.txt"]), delimiter="|")
        for record in records:
            day = datetime.strptime(record["ReportDt"].split()[0], "%m/%d/%Y")
            key = day.date().isoformat(), record["Unit"].strip()
            assert key not in nrc
            nrc[key] = int(record["Power"])

    daily_checks = []
    for day in ("2013-07-24", "2015-10-03", "2015-10-27"):
        parser = Tables()
        parser.feed(files[f"nrc/{day.replace('-', '')}.html"])
        rows = [r for r in parser.rows if r and r[0] == "River Bend 1"]
        assert len(rows) == 1
        assert int(rows[0][1]) == nrc[day, "River Bend 1"] == 100
        daily_checks.append({"date": day, "unit": rows[0][0], "power": 100})

    report = {
        "source_archive_sha256": manifest["archive_sha256"],
        "nrc_daily_vs_annual_checks": daily_checks,
        "samples": {},
        "limitations": manifest["limitations"],
    }
    for year in ("2007", "2013", "2015", "2017"):
        prefix = f"eia/{year}/"
        source = json.loads(files[prefix + "manifest.json"])
        assert source["status"] == "retrieved_with_empty_boundaries"
        for name, digest in source["artifacts"].items():
            assert hashlib.sha256(files[prefix + name].encode()).hexdigest() == digest
        first, last = map(
            date.fromisoformat, (source["requested_start"], source["requested_end"])
        )
        days = [
            (first + timedelta(days=i)).isoformat()
            for i in range((last - first).days + 1)
        ]
        grains = {}
        for grain, keys in {
            "national": ("period",),
            "facility": ("period", "facility"),
            "generator": ("period", "facility", "generator"),
        }.items():
            rows = {}
            pages = source["routes"][grain]["pages"]
            offset = 0
            previous = None
            for page in pages:
                assert page["offset"] == offset
                doc = json.loads(files[prefix + page["path"]])
                for row in doc["response"]["data"]:
                    key = tuple(row[k] for k in keys)
                    assert key not in rows
                    order = (key[0], *(int(k) for k in key[1:]))
                    assert previous is None or previous <= order
                    previous = order
                    assert row["period"] in days
                    c, o, p = (
                        D(row[k]) for k in ("capacity", "outage", "percentOutage")
                    )
                    assert all(v.is_finite() for v in (c, o, p))
                    assert c > 0 and 0 <= o <= c and 0 <= p <= 100
                    rows[key] = row
                offset += len(doc["response"]["data"])
            assert page["received_rows"] == 0
            assert offset == source["routes"][grain]["received_rows"]
            grains[grain] = rows

        daily = []
        facility_groups = defaultdict(list)
        for key, row in grains["generator"].items():
            assert key[:2] in grains["facility"]
            facility_groups[key[:2]].append(row)
        assert facility_groups.keys() == grains["facility"].keys()
        for key, rows in facility_groups.items():
            for field in ("capacity", "outage"):
                assert sum((D(r[field]) for r in rows), D(0)) == D(
                    grains["facility"][key][field]
                )
        missing = []
        for day in days:
            national = grains["national"][day,]
            for grain in ("facility", "generator"):
                rows = [r for k, r in grains[grain].items() if k[0] == day]
                for field in ("capacity", "outage"):
                    assert sum((D(r[field]) for r in rows), D(0)) == D(national[field])
            river = grains["generator"].get((day, "6462", "1"))
            facility = grains["facility"].get((day, "6462"))
            assert (river is None) == (facility is None)
            observed_nrc = nrc.get((day, "River Bend 1"))
            if river is None:
                missing.append({"date": day, "nrc_power": observed_nrc})
                if year in ("2013", "2015"):
                    assert observed_nrc is not None
            daily.append(
                {
                    "date": day,
                    "capacity_mw": national["capacity"],
                    "outage_mw": national["outage"],
                    "reported_percent": national["percentOutage"],
                    "calculated_percent": str(
                        100 * D(national["outage"]) / D(national["capacity"])
                    ),
                    "generator_count": sum(k[0] == day for k in grains["generator"]),
                    "river_bend": river,
                }
            )
        report["samples"][year] = {
            "interval": [days[0], days[-1]],
            "retrieved_at_utc": source["started_at_utc"],
            "rows": {k: len(v) for k, v in grains.items()},
            "reconciled_days": len(days),
            "reconciled_facility_day_groups": len(facility_groups),
            "capacity_and_outage_gaps_mw": "0",
            "river_bend_missing_days": missing,
            "missing_days_by_weekday": dict(
                Counter(date.fromisoformat(r["date"]).strftime("%A") for r in missing)
            ),
            "daily": daily,
        }
    print(json.dumps(report, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
