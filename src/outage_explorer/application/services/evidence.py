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
from outage_explorer.domain.observations import Grain, assess, calculate, select_daily

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


class VerifyBaseline:
    def __init__(
        self, evidence: RecordedEvidence, writer: ReportWriter, grain: Grain
    ) -> None:
        self._evidence = evidence
        self._writer = writer
        self.grain = grain

    def verify(self, bundle_reference: str) -> VerificationReport:
        evidence = self._evidence.load(bundle_reference)
        assessments = tuple(assess(record, self.grain) for record in evidence.records)
        if any(
            item.day is not None and not BASELINE_START <= item.day <= BASELINE_END
            for item in assessments
        ):
            raise VerificationError(
                "Evidence includes dates outside the fixed September 2026 interval"
            )
        ledger = select_daily(assessments)
        results = {}
        for item in ledger:
            observation = item.assessment.observation
            if item.status == "selected" and observation is not None:
                result = calculate(observation, item.assessment.position)
                if (
                    result.fraction * Fraction(observation.capacity)
                    != Fraction(observation.outage)
                    or result.percentage != result.fraction * 100
                ):
                    raise VerificationError("Calculation invariant failed")
                results[(observation.day, observation.identity)] = result
        identities = sorted(
            {item.identity for item in assessments if item.identity is not None}
        ) or [()]
        exclusions: dict[tuple[date, tuple[str, ...]], list[int]] = {}
        for assessment in assessments:
            if assessment.day is not None and assessment.observation is None:
                # Unknown identities belong to the ledger, never another entity.
                if assessment.identity is not None or self.grain == "national":
                    exclusions.setdefault(
                        (assessment.day, assessment.identity or ()), []
                    ).append(assessment.position)
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
        counts: Counter[str] = Counter(item.status for item in ledger)
        reasons = Counter(
            reason.code for item in assessments for reason in item.reasons
        )
        return VerificationReport(
            evidence,
            tuple(coverage),
            ledger,
            (
                ("received", len(ledger)),
                *(
                    (name, counts[name])
                    for name in ("selected", "excluded", "duplicate", "superseded")
                ),
            ),
            tuple(sorted(reasons.items())),
            METRIC,
            LIMITATIONS
            + (
                (
                    "Coverage uses only identities observed in this bundle; it does not prove a complete upstream roster.",
                    "Response totals and received rows are separate evidence; pagination completeness remains unverified.",
                    "Facility/generator shares describe individual observations, not the national fleet share.",
                    "No cross-grain reconciliation or replacement of national values is performed.",
                )
                if self.grain != "national"
                else ()
            ),
            self.grain,
        )

    def run(self, bundle_reference: str, destination: str) -> ReportLocations:
        return self._writer.write(self.verify(bundle_reference), destination)


class VerifyNationalBaseline(VerifyBaseline):
    def __init__(self, evidence: RecordedEvidence, writer: ReportWriter) -> None:
        super().__init__(evidence, writer, "national")
