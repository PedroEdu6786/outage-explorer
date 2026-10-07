"""Explore fixed reconciliation evidence offline; no product or network calls."""

import io
import json
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from decimal import Decimal

from facility_row_count import reconcile
from historical_omissions import main as historical_replay

ZERO = Decimal(0)


def total(rows, field):
    return sum((Decimal(row[field]) for row in rows), ZERO)


def percent(outage, capacity):
    return 100 * outage / capacity


def extend(rows, reconciliation):
    national = {row["period"]: row for row in rows["national"]}
    by_day = {grain: defaultdict(list) for grain in ("facility", "generator")}
    for grain, days in by_day.items():
        for row in rows[grain]:
            days[row["period"]].append(row)

    daily = []
    for day, observation in sorted(national.items()):
        national_percent = percent(
            Decimal(observation["outage"]), Decimal(observation["capacity"])
        )
        metrics = {}
        for grain, days in by_day.items():
            values = days[day]
            capacity, outage = (
                total(values, field) for field in ("capacity", "outage")
            )
            metrics[grain] = {
                "capacity_weighted_percent": str(percent(outage, capacity)),
                "unweighted_mean_percent": str(
                    sum(
                        (
                            percent(Decimal(row["outage"]), Decimal(row["capacity"]))
                            for row in values
                        ),
                        ZERO,
                    )
                    / len(values)
                ),
                "weighted_minus_national_percentage_points": str(
                    percent(outage, capacity) - national_percent
                ),
            }
        categories = Counter()
        for row in by_day["generator"][day]:
            capacity, outage = Decimal(row["capacity"]), Decimal(row["outage"])
            category = (
                "zero" if outage == 0 else "full" if outage == capacity else "partial"
            )
            categories[category] += 1
        count = len(by_day["generator"][day])
        daily.append(
            {
                "period": day,
                "national_capacity_offline_percent": str(national_percent),
                "source_reported_percent": observation["percentOutage"],
                "grain_metrics": metrics,
                "generator_observation_categories": {
                    category: categories[category]
                    for category in ("zero", "partial", "full")
                },
                "generator_count": count,
                "nonzero_outage_observation_percent": str(
                    100 * Decimal(categories["partial"] + categories["full"]) / count
                ),
                "generator_id_occurrences": dict(
                    sorted(
                        Counter(
                            row["generator"] for row in by_day["generator"][day]
                        ).items()
                    )
                ),
            }
        )

    transitions = []
    days = sorted(national)
    for before, after in zip(days, days[1:], strict=False):
        previous = {
            (row["facility"], row["generator"]): row
            for row in by_day["generator"][before]
        }
        current = {
            (row["facility"], row["generator"]): row
            for row in by_day["generator"][after]
        }
        changes = []
        facility_changes = defaultdict(lambda: ZERO)
        for identity in sorted(previous.keys() & current.keys()):
            old, new = previous[identity], current[identity]
            delta = Decimal(new["outage"]) - Decimal(old["outage"])
            if delta:
                changes.append(
                    {
                        "facility": identity[0],
                        "generator": identity[1],
                        "facility_name": new["facilityName"],
                        "before_outage_mw": old["outage"],
                        "after_outage_mw": new["outage"],
                        "delta_outage_mw": str(delta),
                    }
                )
                facility_changes[identity[0]] += delta
        increases = sum(
            (
                Decimal(row["delta_outage_mw"])
                for row in changes
                if Decimal(row["delta_outage_mw"]) > 0
            ),
            ZERO,
        )
        decreases = sum(
            (
                Decimal(row["delta_outage_mw"])
                for row in changes
                if Decimal(row["delta_outage_mw"]) < 0
            ),
            ZERO,
        )
        national_delta = Decimal(national[after]["outage"]) - Decimal(
            national[before]["outage"]
        )
        facility_delta = total(by_day["facility"][after], "outage") - total(
            by_day["facility"][before], "outage"
        )
        generator_delta = total(by_day["generator"][after], "outage") - total(
            by_day["generator"][before], "outage"
        )
        previous_facilities = {
            row["facility"]: row for row in by_day["facility"][before]
        }
        current_facilities = {row["facility"]: row for row in by_day["facility"][after]}
        facility_attribution = []
        for identity in sorted(previous_facilities.keys() & current_facilities.keys()):
            reported_delta = Decimal(current_facilities[identity]["outage"]) - Decimal(
                previous_facilities[identity]["outage"]
            )
            unit_delta = facility_changes.get(identity, ZERO)
            if reported_delta or unit_delta:
                facility_attribution.append(
                    {
                        "facility": identity,
                        "reported_delta_outage_mw": str(reported_delta),
                        "matched_unit_delta_outage_mw": str(unit_delta),
                        "gap_mw": str(unit_delta - reported_delta),
                    }
                )
        transitions.append(
            {
                "before": before,
                "after": after,
                "national_delta_outage_mw": str(national_delta),
                "facility_delta_outage_mw": str(facility_delta),
                "generator_delta_outage_mw": str(generator_delta),
                "facility_minus_national_delta_mw": str(
                    facility_delta - national_delta
                ),
                "generator_minus_national_delta_mw": str(
                    generator_delta - national_delta
                ),
                "matched_unit_increases_mw": str(increases),
                "matched_unit_decreases_mw": str(decreases),
                "matched_unit_net_delta_mw": str(increases + decreases),
                "opposing_change_mw": str(min(increases, -decreases)),
                "matched_units_minus_national_delta_mw": str(
                    increases + decreases - national_delta
                ),
                "added_observation_keys": sorted(current.keys() - previous.keys()),
                "removed_observation_keys": sorted(previous.keys() - current.keys()),
                "matched_unit_changes": changes,
                "facility_change_attribution": facility_attribution,
                "matched_unit_change_by_facility_mw": {
                    key: str(value) for key, value in sorted(facility_changes.items())
                },
            }
        )

    differences = reconciliation["generator_to_facility_differences"]
    diagnostics = {}
    for field in ("capacity", "outage"):
        gaps = [Decimal(row["gap"]) for row in differences if row["field"] == field]
        diagnostics[field] = {
            "mismatched_facility_day_groups": len(gaps),
            "signed_gap_sum_mw": str(sum(gaps, ZERO)),
            "absolute_gap_sum_mw": str(sum((abs(gap) for gap in gaps), ZERO)),
        }
    return {
        "scope": "Exploratory calculations over the recorded September 2026 baseline",
        "sources": reconciliation["sources"],
        "daily_metric_and_identity_checks": daily,
        "daily_change_attribution": transitions,
        "facility_gap_diagnostics": diagnostics,
    }


def historical_summary():
    # Reuse the existing hash/pagination/NRC checks, rather than trust a summary file.
    output = io.StringIO()
    with redirect_stdout(output):
        historical_replay()
    report = json.loads(output.getvalue())
    samples = []
    for year, sample in report["samples"].items():
        samples.append(
            {
                "year": year,
                "interval": sample["interval"],
                "reconciled_days": sample["reconciled_days"],
                "reconciled_facility_day_groups": sample[
                    "reconciled_facility_day_groups"
                ],
                "capacity_and_outage_gaps_mw": sample["capacity_and_outage_gaps_mw"],
                "river_bend_missing_dates": len(sample["river_bend_missing_days"]),
                "missing_dates_with_nrc_full_power": sum(
                    row["nrc_power"] == 100 for row in sample["river_bend_missing_days"]
                ),
            }
        )
    daily = {row["date"]: row for row in report["samples"]["2015"]["daily"]}
    day, previous = daily["2015-10-03"], daily["2015-10-02"]
    outage, capacity, adjacent_capacity = (
        Decimal(value)
        for value in (day["outage_mw"], day["capacity_mw"], previous["capacity_mw"])
    )
    actual = percent(outage, capacity)
    reference = percent(outage, adjacent_capacity)
    return {
        "archive_sha256": report["source_archive_sha256"],
        "samples": samples,
        "total_reconciled_days": sum(row["reconciled_days"] for row in samples),
        "total_facility_day_groups": sum(
            row["reconciled_facility_day_groups"] for row in samples
        ),
        "denominator_sensitivity_example": {
            "period": day["date"],
            "facility": "6462",
            "generator": "1",
            "outage_mw": str(outage),
            "reported_capacity_mw": str(capacity),
            "previous_day_capacity_mw": str(adjacent_capacity),
            "capacity_difference_mw": str(capacity - adjacent_capacity),
            "reported_input_share_percent": str(actual),
            "same_outage_previous_capacity_reference_percent": str(reference),
            "difference_percentage_points": str(actual - reference),
            "interpretation": "Sensitivity only; adjacent-date capacity is not a verified same-day correction",
        },
    }


def main():
    rows, _, _, reconciliation = reconcile()
    result = extend(rows, reconciliation)
    result["historical_coverage_checks"] = historical_summary()
    result["combined_sample_coverage"] = {
        "sampled_dates": len(reconciliation["daily_reconciliation"])
        + result["historical_coverage_checks"]["total_reconciled_days"],
        "facility_day_groups": reconciliation["generator_groups"]
        + result["historical_coverage_checks"]["total_facility_day_groups"],
        "interpretation": "Five nonoverlapping sampled intervals, not continuous historical coverage",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
