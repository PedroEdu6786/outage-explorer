"""Offline contributor verification of the fixed daily EIA baselines."""

from collections import Counter
from datetime import date, timedelta
from fractions import Fraction

from outage_explorer.application.dto import (
    Coverage,
    ReportLocations,
    VerificationReport,
)
from outage_explorer.application.errors import VerificationError
from outage_explorer.application.ports.evidence import RecordedEvidence, ReportWriter
from outage_explorer.domain.observations import (
    Assessment,
    DailyResult,
    Disposition,
    Grain,
    SourceRecord,
    assess,
    calculate,
    select_daily,
)

BASELINE_START = date(2026, 9, 1)
BASELINE_END = date(2026, 9, 30)
METRIC = (
    "Daily share of EIA-reported nuclear capacity out of service, "
    "including full outages and partial output reductions."
)
LIMITATIONS = (
    "The September 1–30, 2026 baseline does not prove correctness across all source history.",
    "The recorded sample's constant capacity does not demonstrate historical capacity changes.",
    "Exact historical capacity-data vintage remains unverified; capacity is not reconstructed.",
    "Daily reported status does not establish reactor shutdown proportion or full-day averages.",
    "The metric does not establish outage duration, lost energy or outage causes.",
    "Recorded EIA evidence does not independently prove physical operation.",
    "Source order provides deterministic selection, not proof of revision recency.",
)
DETAIL_LIMITATIONS = (
    "Coverage uses only identities observed in this bundle; it does not prove a complete upstream roster.",
    "Response totals and received rows are separate evidence; pagination completeness remains unverified.",
    "Facility/generator shares describe individual observations, not the national fleet share.",
    "No cross-grain reconciliation or replacement of national values is performed.",
)


def _assess_interval(
    records: tuple[SourceRecord, ...], grain: Grain
) -> tuple[Assessment, ...]:
    assessments = tuple(assess(record, grain) for record in records)
    if any(
        item.day is not None and not BASELINE_START <= item.day <= BASELINE_END
        for item in assessments
    ):
        raise VerificationError(
            "Evidence includes dates outside the fixed September 2026 interval"
        )
    return assessments


def _selected_results(
    ledger: tuple[Disposition, ...],
) -> dict[tuple[date, tuple[str, ...]], DailyResult]:
    results = {}
    for item in ledger:
        observation = item.assessment.observation
        if item.status != "selected" or observation is None:
            continue
        result = calculate(observation, item.assessment.position)
        if (
            result.fraction * Fraction(observation.capacity)
            != Fraction(observation.outage)
            or result.percentage != result.fraction * 100
        ):
            raise VerificationError("Calculation invariant failed")
        results[(observation.day, observation.identity)] = result
    return results


def _excluded_positions(
    assessments: tuple[Assessment, ...], grain: Grain
) -> dict[tuple[date, tuple[str, ...]], list[int]]:
    exclusions: dict[tuple[date, tuple[str, ...]], list[int]] = {}
    for item in assessments:
        if item.day is None or item.observation is not None:
            continue
        # Unknown identities belong to the ledger, never another entity.
        if item.identity is not None or grain == "national":
            exclusions.setdefault((item.day, item.identity or ()), []).append(
                item.position
            )
    return exclusions


def _coverage(
    assessments: tuple[Assessment, ...],
    results: dict[tuple[date, tuple[str, ...]], DailyResult],
    grain: Grain,
) -> tuple[Coverage, ...]:
    identities = sorted(
        {item.identity for item in assessments if item.identity is not None}
    ) or [()]
    exclusions = _excluded_positions(assessments, grain)
    coverage = []
    for offset in range((BASELINE_END - BASELINE_START).days + 1):
        day = BASELINE_START + timedelta(days=offset)
        for identity in identities:
            key = (day, identity)
            coverage.append(
                Coverage(
                    day.isoformat(),
                    results.get(key),
                    tuple(sorted(exclusions.get(key, []))),
                    identity,
                )
            )
    return tuple(coverage)


def _counts(ledger: tuple[Disposition, ...]) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter(item.status for item in ledger)
    return (
        ("received", len(ledger)),
        *(
            (name, counts[name])
            for name in ("selected", "excluded", "duplicate", "superseded")
        ),
    )


def _reason_counts(assessments: tuple[Assessment, ...]) -> tuple[tuple[str, int], ...]:
    reasons = Counter(reason.code for item in assessments for reason in item.reasons)
    return tuple(sorted(reasons.items()))


class VerifyBaseline:
    def __init__(
        self, evidence: RecordedEvidence, writer: ReportWriter, grain: Grain
    ) -> None:
        self._evidence = evidence
        self._writer = writer
        self.grain = grain

    def verify(self, bundle_reference: str) -> VerificationReport:
        evidence = self._evidence.load(bundle_reference)
        assessments = _assess_interval(evidence.records, self.grain)
        ledger = select_daily(assessments)
        results = _selected_results(ledger)
        return VerificationReport(
            evidence,
            _coverage(assessments, results, self.grain),
            ledger,
            _counts(ledger),
            _reason_counts(assessments),
            METRIC,
            LIMITATIONS + (DETAIL_LIMITATIONS if self.grain != "national" else ()),
            self.grain,
        )

    def run(self, bundle_reference: str, destination: str) -> ReportLocations:
        return self._writer.write(self.verify(bundle_reference), destination)


class VerifyNationalBaseline(VerifyBaseline):
    def __init__(self, evidence: RecordedEvidence, writer: ReportWriter) -> None:
        super().__init__(evidence, writer, "national")
