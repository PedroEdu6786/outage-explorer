"""Local bounded Parquet candidates; no activation, retrieval or publication."""

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from itertools import chain, zip_longest

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
    GrainSummary,
)
from outage_explorer.domain.observations import IDENTITY_FIELDS, Grain, Reason
from outage_explorer.domain.refresh import (
    EmptySourceError,
    ModeledRow,
    Origin,
    Quality,
    RefreshBounds,
    RefreshInputError,
    model_partition,
)
from outage_explorer.infrastructure.parquet.evidence import (
    replay_evidence,
    verify_evidence,
)
from outage_explorer.infrastructure.parquet.manifests import (
    load_manifest,
    manifest_bytes,
    persist_manifest,
    validate_manifest,
)
from outage_explorer.infrastructure.parquet.partitions import (
    DayMerge,
    day_sequence,
    incoming_day,
    index_modeled,
    merge_day,
    stage_dates,
)
from outage_explorer.infrastructure.parquet.schemas import (
    disposition_record,
    modeled_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


@dataclass
class _Accounting:
    grain: Grain
    counts: Counter[str] = field(default_factory=Counter)
    reasons: Counter[Reason] = field(default_factory=Counter)
    identities: set[tuple[str, ...]] = field(default_factory=set)
    observed_dates: set[date] = field(default_factory=set)
    usable_dates: set[date] = field(default_factory=set)

    def add(self, day: DayMerge, bounds: RefreshBounds) -> None:
        merged = day.merged
        quality = merged.incoming.quality
        for name in ("received", "selected", "excluded", "duplicate", "superseded"):
            self.counts[name] += getattr(quality, name)
        self.reasons.update(dict(quality.reason_counts))
        self.counts["active"] += merged.active_count
        self.counts["candidate"] += merged.candidate_count
        self.counts["invalid"] += len(merged.retained_invalid_keys)
        self.counts["absent"] += len(merged.absent_prior_rows)
        self.counts["outside"] += len(merged.carried_outside_keys)
        self.identities.update(merged.incoming.observed_identities)
        self.observed_dates.update(merged.incoming.observed_dates)
        self.usable_dates.update(row.observation.day for row in merged.incoming.rows)
        # Exact incoming coverage cardinalities are bounded separately from the
        # number of historical rows scanned, reusing explicit caller limits.
        if len(self.identities) > bounds.output_rows:
            raise ArtifactLimitError("Observed identity cardinality bound exceeded")
        if sum(self.reasons.values()) > bounds.reason_occurrences:
            raise ArtifactLimitError("Route reason occurrence bound exceeded")

    def summary(self) -> GrainSummary:
        c = self.counts
        if c["received"] == 0:
            raise EmptySourceError("Required route received no observations")
        quality = Quality(
            c["received"],
            c["selected"],
            c["excluded"],
            c["duplicate"],
            c["superseded"],
            tuple(
                sorted(
                    self.reasons.items(), key=lambda pair: (pair[0].field, pair[0].code)
                )
            ),
        )
        if quality.received != sum(
            (quality.selected, quality.excluded, quality.duplicate, quality.superseded)
        ):
            raise ArtifactError("Disposition counts do not reconcile")
        if c["candidate"] != c["selected"] + c["invalid"] + c["absent"] + c["outside"]:
            raise ArtifactError("Merge counts do not reconcile")
        return GrainSummary(
            self.grain,
            quality,
            c["active"],
            c["candidate"],
            c["invalid"],
            c["absent"],
            c["outside"],
            len(self.identities),
            len(self.observed_dates),
            len(self.usable_dates),
        )


def _outcome(summaries: tuple[GrainSummary, ...], initial: bool) -> str:
    if initial and any(summary.quality.selected == 0 for summary in summaries):
        raise RefreshInputError(
            "Initial load requires usable output in all three grains"
        )
    if not initial and any(summary.active_count == 0 for summary in summaries):
        raise RefreshInputError("Prior generation must contain all three grains")
    if all(summary.quality.selected == 0 for summary in summaries):
        return "retained_all_excluded"
    return "candidate"


class ParquetCandidateBuilder:
    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store

    def _inputs(
        self, evidence: Iterable[EvidenceBundle], bounds: RefreshBounds
    ) -> tuple[EvidenceBundle, ...]:
        bundles: dict[Grain, EvidenceBundle] = {}
        for bundle in evidence:
            if bundle.grain not in IDENTITY_FIELDS or bundle.grain in bundles:
                raise RefreshInputError(
                    "Expected exactly one evidence bundle per grain"
                )
            bundles[bundle.grain] = bundle
        if set(bundles) != set(IDENTITY_FIELDS):
            raise RefreshInputError("All three grains are required")
        if len({bundle.interval for bundle in bundles.values()}) != 1:
            raise RefreshInputError("Route intervals differ")
        interval = next(iter(bundles.values())).interval
        if (interval.end - interval.start).days + 1 > bounds.interval_days:
            raise ArtifactLimitError("Requested interval bound exceeded")
        for bundle in bundles.values():
            verify_evidence(self.store, bundle)
        return tuple(bundles[grain] for grain in IDENTITY_FIELDS)

    def _versions(self, bundles: tuple[EvidenceBundle, ...]) -> tuple[str, str]:
        identity = None
        for bundle in bundles:
            for row in replay_evidence(self.store, bundle):
                current = (
                    row.origin.run_id,
                    row.origin.contract_id,
                    row.origin.transformation_id,
                )
                if identity is not None and current != identity:
                    raise RefreshInputError(
                        "Mixed run, contract or transformation identities"
                    )
                identity = current
        if identity is None:
            raise EmptySourceError("Required route received no observations")
        return identity[1], identity[2]

    def build(
        self,
        generation_id: str,
        evidence: Iterable[EvidenceBundle],
        bounds: RefreshBounds,
        prior: CandidateManifest | None = None,
    ) -> CandidateManifest:
        if not generation_id or len(generation_id) > bounds.field_chars:
            raise RefreshInputError("Invalid generation identity")
        bundles = self._inputs(evidence, bounds)
        versions = self._versions(bundles)
        if prior is not None:
            self.verify(prior, bounds)
            if prior.outcome != "candidate" or generation_id == prior.generation_id:
                raise RefreshInputError("Base must be a different eligible generation")
        base = () if prior is None else prior.modeled
        inherited = () if prior is None else _dependencies(prior)
        modeled: list[ArtifactRef] = []
        dispositions: list[ArtifactRef] = []
        ledger: list[ArtifactRef] = []
        summaries = []
        for bundle in bundles:
            staged = stage_dates(self.store, bundle)
            previous = index_modeled(base, bundle.grain)
            account = _Accounting(bundle.grain)
            for day in day_sequence(bundle.interval, previous):
                part = merge_day(self.store, bundle, day, previous, bounds, staged)
                account.add(part, bounds)
                dispositions.extend(
                    self.store.write(
                        "dispositions",
                        bundle.grain,
                        day,
                        (
                            disposition_record(value)
                            for value in part.merged.incoming.decisions
                        ),
                    )
                )
                ledger.extend(
                    self.store.write("ledger", bundle.grain, day, part.ledger())
                )
                if not part.merged.incoming.rows:
                    modeled.extend(previous.get(day, ()))
                else:
                    modeled.extend(
                        self.store.write(
                            "modeled",
                            bundle.grain,
                            day,
                            (modeled_record(row) for row in part.merged.rows),
                        )
                    )
            summaries.append(account.summary())
        outcome = _outcome(tuple(summaries), prior is None)
        candidate = CandidateManifest(
            generation_id,
            None if prior is None else prior.generation_id,
            bundles[0].interval,
            bundles,
            inherited,
            base,
            tuple(modeled),
            tuple(dispositions),
            tuple(ledger),
            tuple(summaries),
            "candidate" if outcome == "candidate" else "retained_all_excluded",
            *versions,
            base_manifest_object=None if prior is None else prior.manifest_object,
        )
        self.verify(candidate, bounds)
        return persist_manifest(self.store, candidate)

    def verify(self, candidate: CandidateManifest, bounds: RefreshBounds) -> None:
        validate_manifest(candidate)
        if candidate.schema_version != "1":
            raise ArtifactError("Unsupported candidate schema version")
        if (
            not candidate.generation_id
            or len(candidate.generation_id) > bounds.field_chars
        ):
            raise ArtifactError("Invalid generation identity")
        bundles = self._inputs(candidate.evidence, bounds)
        if candidate.interval != bundles[0].interval:
            raise ArtifactError("Manifest interval disagrees with evidence")
        if self._versions(bundles) != (
            candidate.contract_id,
            candidate.transformation_id,
        ):
            raise ArtifactError("Manifest versions disagree with evidence")
        self._verify_references(candidate)
        for dependency in candidate.inherited_evidence:
            verify_evidence(self.store, dependency)
        if candidate.base_generation_id is None:
            if (
                candidate.base_modeled
                or candidate.inherited_evidence
                or candidate.base_manifest_object
            ):
                raise ArtifactError("Initial candidate cannot inherit data")
        elif (
            not candidate.base_modeled
            or candidate.base_generation_id == candidate.generation_id
        ):
            raise ArtifactError("Invalid base generation references")
        if candidate.base_generation_id is not None:
            if candidate.base_manifest_object is None:
                raise ArtifactError("Base generation lacks its immutable manifest")
            base = load_manifest(self.store, candidate.base_manifest_object)
            if (
                base.generation_id != candidate.base_generation_id
                or base.modeled != candidate.base_modeled
                or _dependencies(base) != candidate.inherited_evidence
            ):
                raise ArtifactError("Base references disagree with pinned manifest")
        summaries = []
        for bundle in bundles:
            previous = index_modeled(candidate.base_modeled, bundle.grain)
            actual = index_modeled(candidate.modeled, bundle.grain)
            expected_dates = set(previous)
            account = _Accounting(bundle.grain)
            for day in day_sequence(bundle.interval, previous):
                expected_dates.add(day)
                part = merge_day(self.store, bundle, day, previous, bounds)
                account.add(part, bounds)
                self._bind_history(part.old, candidate.inherited_evidence, bounds)
                self._equal_records(
                    actual.get(day, ()),
                    (modeled_record(row) for row in part.merged.rows),
                )
                self._equal_records(
                    _refs(candidate.dispositions, bundle.grain, day),
                    (disposition_record(row) for row in part.merged.incoming.decisions),
                )
                self._equal_records(
                    _refs(candidate.ledger, bundle.grain, day), part.ledger()
                )
            for collection in (
                candidate.modeled,
                candidate.dispositions,
                candidate.ledger,
            ):
                if any(
                    ref.grain == bundle.grain and ref.partition not in expected_dates
                    for ref in collection
                ):
                    raise ArtifactError("Unexpected artifact partition")
            summaries.append(account.summary())
        if tuple(summaries) != candidate.summaries:
            raise ArtifactError("Manifest quality or coverage does not reconcile")
        outcome = _outcome(tuple(summaries), candidate.base_generation_id is None)
        if outcome != candidate.outcome:
            raise ArtifactError("Incorrect candidate outcome")
        if candidate.manifest_object is not None:
            stored = b"".join(self.store.read(candidate.manifest_object))
            if stored != manifest_bytes(candidate):
                raise ArtifactError("Persisted manifest disagrees with candidate")

    def _verify_references(self, candidate: CandidateManifest) -> None:
        references: list[ArtifactRef] = []
        for kind, collection in (
            ("modeled", candidate.base_modeled),
            ("modeled", candidate.modeled),
            ("dispositions", candidate.dispositions),
            ("ledger", candidate.ledger),
        ):
            if any(
                ref.kind != kind or ref.grain not in IDENTITY_FIELDS
                for ref in collection
            ):
                raise ArtifactError("Unexpected artifact kind or grain")
            if len(
                {(ref.grain, ref.partition, ref.object.key) for ref in collection}
            ) != len(collection):
                raise ArtifactError("Repeated artifact reference")
            references.extend(collection)
        for evidence in (*candidate.evidence, *candidate.inherited_evidence):
            references.extend((*evidence.raw, *evidence.pages))
        if len(references) > self.store.bounds.objects:
            raise ArtifactLimitError("Manifest reference bound exceeded")
        unique = {ref.object.key: ref for ref in references}
        if (
            sum(ref.object.byte_count for ref in unique.values())
            > self.store.bounds.total_bytes
        ):
            raise ArtifactLimitError("Manifest byte bound exceeded")
        for ref in references:
            self.store.verify(ref)

    def _equal_records(
        self, references: tuple[ArtifactRef, ...], expected: Iterable[dict[str, object]]
    ) -> None:
        def actual() -> Iterator[dict[str, object]]:
            for ref in references:
                yield from self.store.records(ref)

        for got, wanted in zip_longest(actual(), expected):
            if got != wanted:
                raise ArtifactError(
                    "Artifact rows disagree with replay or merge ledger"
                )

    def _bind_history(
        self,
        rows: tuple[ModeledRow, ...],
        evidence: tuple[EvidenceBundle, ...],
        bounds: RefreshBounds,
    ) -> None:
        if not rows:
            return
        pending: dict[Origin, ModeledRow] = {row.origin: row for row in rows}
        if len(pending) != len(rows):
            raise ArtifactError("Repeated modeled origin")
        day = rows[0].observation.day
        for bundle in evidence:
            if bundle.grain != rows[0].origin.grain or not bundle.interval.contains(
                day
            ):
                continue
            incoming = incoming_day(self.store, bundle, day, None)
            first = next(incoming, None)
            if first is None:
                continue

            modeled = model_partition(
                bundle.grain, bundle.interval, chain((first,), incoming), bounds
            )
            for row in modeled.rows:
                retained = pending.get(row.origin)
                if retained is not None:
                    if modeled_record(retained) != modeled_record(row):
                        raise ArtifactError(
                            "Retained value disagrees with original evidence"
                        )
                    del pending[row.origin]
        if pending:
            raise ArtifactError("Retained origin lacks selected source evidence")


def _dependencies(prior: CandidateManifest) -> tuple[EvidenceBundle, ...]:
    # Preserve explicit evidence dependencies; no deletion/retention policy here.
    values = []
    seen = set()
    for bundle in (*prior.evidence, *prior.inherited_evidence):
        identity = tuple(ref.object.key for ref in bundle.pages)
        if identity not in seen:
            seen.add(identity)
            values.append(bundle)
    return tuple(values)


def _refs(
    references: tuple[ArtifactRef, ...], grain: Grain, day: date | None
) -> tuple[ArtifactRef, ...]:
    return tuple(
        ref for ref in references if ref.grain == grain and ref.partition == day
    )
