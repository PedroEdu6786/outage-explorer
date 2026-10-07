"""Replay the bounded September samples and saved probes; no network or app imports."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("capacity", "outage")
KEYS = {
    "national": ("period",),
    "facility": ("period", "facility"),
    "generator": ("period", "facility", "generator"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row, grain):
    return tuple(row[field] for field in KEYS[grain])


def index(rows, grain):
    result = {key(row, grain): row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate {grain} keys; investigate before summing")
    return result


def sums(rows):
    return {
        field: sum((Decimal(row[field]) for row in rows), Decimal(0))
        for field in FIELDS
    }


def reconcile():
    rows, sources, counts = {}, {}, {}
    expected_days = {
        (date(2026, 9, 1) + timedelta(days=offset)).isoformat() for offset in range(30)
    }
    for grain in KEYS:
        folder = ROOT / "data" / "verification" / f"{grain}-2026-09"
        manifest = json.loads((folder / "manifest.json").read_text())
        for filename, expected in manifest["artifacts"].items():
            if digest(folder / filename) != expected:
                raise ValueError(f"Evidence hash differs: {grain}/{filename}")
        snapshot = folder / manifest["snapshot"]
        document = json.loads(snapshot.read_text())
        rows[grain] = document["response"]["data"]
        index(rows[grain], grain)
        if {row["period"] for row in rows[grain]} != expected_days:
            raise ValueError(f"Unexpected {grain} date coverage")
        sources[grain] = {
            "snapshot": str(snapshot.relative_to(ROOT)),
            "sha256": digest(snapshot),
            "retrieved_at_utc": document["retrieved_at_utc"],
            "api_version": document["apiVersion"],
        }
        entity_days = defaultdict(set)
        for row in rows[grain]:
            entity_days[key(row, grain)[1:]].add(row["period"])
        counts[grain] = {
            "advertised_total": int(document["response"]["total"]),
            "received_rows": len(rows[grain]),
            "unique_keys": len(index(rows[grain], grain)),
            "observed_entities": len(entity_days),
            "missing_days_within_observed_roster": sum(
                len(expected_days - days) for days in entity_days.values()
            ),
        }

    facilities = index(rows["facility"], "facility")
    generators = defaultdict(list)
    for row in rows["generator"]:
        generators[key(row, "facility")].append(row)
    missing_parents = sorted(generators.keys() - facilities.keys())
    without_children = sorted(facilities.keys() - generators.keys())
    differences = []
    for identity in sorted(generators.keys() & facilities.keys()):
        totals = sums(generators[identity])
        for field in FIELDS:
            parent = Decimal(facilities[identity][field])
            if totals[field] != parent:
                differences.append(
                    {
                        "key": identity,
                        "field": field,
                        "facility": str(parent),
                        "generator_sum": str(totals[field]),
                        "gap": str(totals[field] - parent),
                    }
                )

    daily = []
    for national in sorted(rows["national"], key=lambda row: row["period"]):
        day = national["period"]
        detail = {
            grain: [row for row in rows[grain] if row["period"] == day]
            for grain in ("facility", "generator")
        }
        totals = {grain: sums(values) for grain, values in detail.items()}
        daily.append(
            {
                "period": day,
                "facility_rows": len(detail["facility"]),
                "generator_rows": len(detail["generator"]),
                "national": {field: national[field] for field in FIELDS},
                "detail_sums": {
                    grain: {field: str(value) for field, value in values.items()}
                    for grain, values in totals.items()
                },
                "gaps_from_national": {
                    grain: {
                        field: str(values[field] - Decimal(national[field]))
                        for field in FIELDS
                    }
                    for grain, values in totals.items()
                },
                "facilities_by_generator_count": dict(
                    sorted(
                        Counter(
                            len(generators[key(row, "facility")])
                            for row in detail["facility"]
                        ).items()
                    )
                ),
            }
        )

    result = {
        "scope": "Recorded September 1–30, 2026 cross-grain reconciliation",
        "sources": sources,
        "counts": counts,
        "facility_advertised_minus_received": counts["facility"]["advertised_total"]
        - counts["facility"]["received_rows"],
        "generator_groups": len(generators),
        "generator_rows_without_parent": sum(
            len(generators[identity]) for identity in missing_parents
        ),
        "missing_parent_keys": missing_parents,
        "facility_keys_without_generators": without_children,
        "generator_to_facility_differences": differences,
        "daily_reconciliation": daily,
        "browns_ferry_example": {
            "facility": facilities.get(("2026-09-01", "46")),
            "generators": generators.get(("2026-09-01", "46"), []),
        },
    }
    return rows, facilities, generators, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reconciliation-only",
        action="store_true",
        help="Replay the 30-day reconciliation without the separate live-probe analysis",
    )
    args = parser.parse_args()
    rows, facilities, generators, result = reconcile()
    if args.reconciliation_only:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    probe_path = ROOT / "docs/challenge/evidence/facility-row-count/live-probes.json"
    if (
        digest(probe_path)
        != "1e8e485a23b799a88d641b4f757ace59b80d93991e422cadfaa2c1e0878ff311"
    ):
        raise ValueError("Live-probe evidence hash differs")
    probes = json.loads(probe_path.read_text())["probes"]
    by_id = {probe["id"]: probe for probe in probes}
    probe_rows = {
        probe_id: probe["response"]["data"] for probe_id, probe in by_id.items()
    }
    baseline_day = [r for r in rows["facility"] if r["period"] == "2026-09-01"]
    paged = probe_rows["facility-day-page-1"] + probe_rows["facility-day-page-2"]
    live_checks = {
        "paged_union_equals_full_day": index(paged, "facility")
        == index(probe_rows["facility-day"], "facility"),
        "full_day_equals_recorded_baseline": index(baseline_day, "facility")
        == index(probe_rows["facility-day"], "facility"),
        "browns_ferry_generators_equal_baseline": index(
            probe_rows["browns-ferry-generators"], "generator"
        )
        == index(generators[("2026-09-01", "46")], "generator"),
    }
    for probe_id in ("browns-ferry-facility", "clinton-facility"):
        live_checks[f"{probe_id}_equals_baseline"] = (
            all(
                facilities.get(key(row, "facility")) == row
                for row in probe_rows[probe_id]
            )
            and len(probe_rows[probe_id]) == 1
        )

    example = result.pop("browns_ferry_example")
    result.update(
        {
            "scope": "Recorded September 1–30, 2026 plus eight October 3 live probes",
            "live_evidence": {
                "path": str(probe_path.relative_to(ROOT)),
                "sha256": digest(probe_path),
                "checks": live_checks,
                "probes": [
                    {
                        "id": probe["id"],
                        "http_status": probe["http_status"],
                        "api_version": probe["apiVersion"],
                        "retrieved_at_utc": probe["retrieved_at_utc"],
                        "advertised_total": int(probe["response"]["total"]),
                        "received_rows": len(probe["response"]["data"]),
                    }
                    for probe in probes
                ],
            },
        }
    )
    result["browns_ferry_example"] = example
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
