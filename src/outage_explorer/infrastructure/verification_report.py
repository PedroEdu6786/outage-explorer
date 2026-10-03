"""Deterministic JSON and Markdown renderings of a completed verification."""

import json
from fractions import Fraction
from pathlib import Path

from outage_explorer.application.dto import (
    Coverage,
    ReportLocations,
    VerificationReport,
)
from outage_explorer.application.errors import VerificationError
from outage_explorer.domain.observations import (
    IDENTITY_FIELDS,
    DailyResult,
    Disposition,
)


class LocalReportWriter:
    """Render both report formats and write them without overwriting evidence."""

    def write(self, report: VerificationReport, destination: str) -> ReportLocations:
        try:
            directory = Path(destination).resolve()
            json_path = directory / "report.json"
            markdown_path = directory / "report.md"
            _validate_output_paths(
                json_path, markdown_path, report.evidence.protected_paths
            )

            json_content = _render_json(report)
            markdown_content = _render_markdown(report)

            directory.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json_content, encoding="utf-8")
            markdown_path.write_text(markdown_content, encoding="utf-8")
            return ReportLocations(json=str(json_path), markdown=str(markdown_path))
        except OSError as error:
            raise VerificationError(
                f"Cannot write verification reports: {error}"
            ) from error


def _validate_output_paths(
    json_path: Path, markdown_path: Path, protected_paths: tuple[str, ...]
) -> None:
    if json_path.resolve() == markdown_path.resolve() or (
        json_path.exists()
        and markdown_path.exists()
        and json_path.samefile(markdown_path)
    ):
        raise VerificationError("Report output files must be distinct")

    sources = tuple(Path(path) for path in protected_paths)
    # samefile also prevents hard-link aliases from overwriting evidence.
    for output in (json_path, markdown_path):
        if any(
            output.resolve() == source or (output.exists() and output.samefile(source))
            for source in sources
        ):
            raise VerificationError("Reports cannot overwrite source evidence")


def _render_json(report: VerificationReport) -> str:
    return (
        json.dumps(
            report_document(report), indent=2, ensure_ascii=False, sort_keys=True
        )
        + "\n"
    )


def report_document(report: VerificationReport) -> dict[str, object]:
    document: dict[str, object] = {
        "report_version": 1,
        "evidence_manifest": json.loads(report.evidence.manifest_json),
        "manifest_sha256": report.evidence.manifest_sha256,
        "metric": report.metric,
        "limitations": report.limitations,
        "counts": dict(report.counts),
        "exclusion_reason_counts": dict(report.reason_counts),
        "coverage": [_coverage_document(day) for day in report.coverage],
        "source_records": [_source_record_document(item) for item in report.ledger],
    }
    if report.grain != "national":
        document.update(
            dataset=report.grain,
            source_accounting=_source_accounting(report),
            coverage=[
                {
                    **_coverage_document(day),
                    "identity": _identity_document(report, day.identity),
                }
                for day in report.coverage
            ],
            source_records=[
                {
                    **_source_record_document(item),
                    "identity": _identity_document(report, item.assessment.identity),
                }
                for item in report.ledger
            ],
        )
    return document


def _identity_document(
    report: VerificationReport, identity: tuple[str, ...] | None
) -> dict[str, str] | None:
    if not identity:
        return None
    return dict(zip(IDENTITY_FIELDS[report.grain], identity, strict=True))


def _source_accounting(report: VerificationReport) -> dict[str, object]:
    total = report.evidence.response_total
    return {
        "reported_total": total,
        "received_rows": len(report.evidence.records),
        "reported_total_matches_received": int(total) == len(report.evidence.records)
        if total is not None
        else None,
        "observed_entities": len(
            {day.identity for day in report.coverage if day.identity}
        ),
        "unavailable_entity_dates": sum(
            day.result is None for day in report.coverage if day.identity
        ),
        "roster_known": any(day.identity for day in report.coverage),
        "upstream_completeness": "unverified",
    }


def _coverage_document(day: Coverage) -> dict[str, object]:
    return {
        "period": day.period,
        "result": _result_document(day.result),
        "excluded_positions": day.excluded_positions,
    }


def _result_document(result: DailyResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "source_position": result.source_position,
        "reported_values": dict(result.observation.original),
        "offline_share_fraction": _fraction_document(result.fraction),
        "calculated_percentage": _fraction_document(result.percentage),
        "calculated_percentage_display": result.calculated_display,
        "reported_percentage_display": result.reported_display,
    }


def _fraction_document(value: Fraction) -> dict[str, str]:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _source_record_document(item: Disposition) -> dict[str, object]:
    assessment = item.assessment
    return {
        "source_position": assessment.position,
        "period": assessment.day.isoformat() if assessment.day else None,
        "disposition": item.status,
        "selected_position": item.selected_position,
        "reasons": [
            {"code": reason.code, "field": reason.field}
            for reason in assessment.reasons
        ],
    }


def _render_markdown(report: VerificationReport) -> str:
    sections = [
        _markdown_evidence_summary(report),
        _markdown_row_accounting(report),
        _markdown_daily_results(report),
        _markdown_excluded_records(report),
        ["## Evidence limits", "", *(f"- {limit}" for limit in report.limitations)],
    ]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


def _markdown_evidence_summary(report: VerificationReport) -> list[str]:
    manifest = json.loads(report.evidence.manifest_json)
    return [
        f"# {report.grain.title()} data verification",
        "",
        report.metric,
        "",
        "Examined interval: **2026-09-01 through 2026-09-30**, inclusive.",
        f"Evidence: **{manifest['bundle_id']}** ({manifest['evidence_kind']}).",
        f"Recorded retrieval: {manifest['retrieved_at_utc']}.",
        f"Source: <{manifest['source_url']}>",
        "",
        f"Manifest SHA-256: `{report.evidence.manifest_sha256}`.",
        "Request parameters, exact fractions, source values and record dispositions: [JSON report](report.json).",
        "Replay uses the original bundle's manifest and these unchanged artifact identities:",
        "",
        *(
            f"- `{item.name}` — SHA-256 `{item.sha256}`"
            for item in report.evidence.artifacts
        ),
    ]


def _markdown_row_accounting(report: VerificationReport) -> list[str]:
    reasons = [f"- {reason}: {count}" for reason, count in report.reason_counts]
    source = []
    if report.grain != "national":
        accounting = _source_accounting(report)
        source = [
            "",
            f"Reported response total: {accounting['reported_total']}; received rows: {accounting['received_rows']}.",
            f"Observed entities: {accounting['observed_entities']}; unavailable entity/dates: {accounting['unavailable_entity_dates']}.",
            "Coverage is relative to the observed roster; upstream completeness is unverified.",
        ]
        if not accounting["roster_known"]:
            source.append(
                "No identifiable entity roster; all 30 dates are unavailable."
            )
        if accounting["reported_total_matches_received"] is False:
            source.append(
                "The reported total differs from received rows; pagination/completeness semantics remain unresolved."
            )
    return [
        "## Row accounting",
        "",
        *(f"- {name}: {count}" for name, count in report.counts),
        "",
        "Exclusion reason occurrences (a row may have several):",
        "",
        *(reasons or ["None."]),
        *source,
    ]


def _markdown_daily_results(report: VerificationReport) -> list[str]:
    if report.grain != "national":
        return [
            "## Daily entity results",
            "",
            "Source positions are zero-based indices in the snapshot's `response.data`.",
            "Names come from each selected record; identifiers define coverage.",
            "",
            "| Date | Facility | Generator | Facility name | Capacity (MW) | Outage (MW) | Calculated (%) | EIA-reported (%) | Source position |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            *(_markdown_entity_row(day) for day in report.coverage),
        ]
    return [
        "## Daily results",
        "",
        "Source positions are zero-based indices in the snapshot's `response.data`.",
        "",
        "| Date | Capacity (MW) | Outage (MW) | Calculated (%) | EIA-reported (%) | Source position |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
        *(_markdown_daily_row(day) for day in report.coverage),
    ]


def _markdown_entity_row(day: Coverage) -> str:
    facility = _escape_cell(day.identity[0]) if day.identity else "unknown"
    generator = _escape_cell(day.identity[1]) if len(day.identity) == 2 else "—"
    name = (
        _escape_cell(day.result.observation.facility_name or "")
        if day.result
        else "unavailable"
    )
    row = _markdown_daily_row(day)
    return row.replace(
        f"| {day.period} |", f"| {day.period} | {facility} | {generator} | {name} |", 1
    )


def _escape_cell(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _markdown_daily_row(day: Coverage) -> str:
    result = day.result
    if result is None:
        cause = (
            f"excluded positions {', '.join(map(str, day.excluded_positions))}"
            if day.excluded_positions
            else "no observation"
        )
        return f"| {day.period} | unavailable | unavailable | unavailable | unavailable | {cause} |"

    values = dict(result.observation.original)
    return (
        f"| {day.period} | {values['capacity']} | {values['outage']} "
        f"| {result.calculated_display} | {result.reported_display} "
        f"| {result.source_position} |"
    )


def _markdown_excluded_records(report: VerificationReport) -> list[str]:
    excluded = [item for item in report.ledger if item.status == "excluded"]
    lines = ["## Excluded records", ""]
    for item in excluded:
        reasons = "; ".join(
            f"{reason.field}: {reason.code}" for reason in item.assessment.reasons
        )
        lines.append(f"- Source position {item.assessment.position}: {reasons}")
    if not excluded:
        lines.append("None.")
    return lines
