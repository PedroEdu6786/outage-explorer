"""Validate the complete bounded three-grain transient input set."""

from collections.abc import Iterable

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.candidates import TransientInput
from outage_explorer.domain.observations import IDENTITY_FIELDS, Grain
from outage_explorer.domain.refresh import (
    EmptySourceError,
    RefreshBounds,
    RefreshInputError,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


class CandidateInputValidator:
    """Check all three inputs before any grain writes a candidate file."""

    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store

    def validate(
        self, inputs: Iterable[TransientInput], bounds: RefreshBounds
    ) -> tuple[TransientInput, ...]:
        collected: dict[Grain, TransientInput] = {}
        total_bytes = 0
        identity: tuple[str, str, str] | None = None
        for item in inputs:
            self.store.check()
            self._validate_input_grain_and_rows(item, collected, bounds)
            total_bytes = self._validate_input_limits(item, total_bytes, bounds)
            identity = self._validate_input_identity(item, identity, bounds)
            collected[item.grain] = item
        if set(collected) != set(IDENTITY_FIELDS):
            raise RefreshInputError("All three grains are required")
        if len({item.interval for item in collected.values()}) != 1:
            raise RefreshInputError("Route intervals differ")
        return tuple(collected[grain] for grain in IDENTITY_FIELDS)

    @staticmethod
    def _validate_input_grain_and_rows(
        item: TransientInput,
        collected: dict[Grain, TransientInput],
        bounds: RefreshBounds,
    ) -> None:
        if item.grain not in IDENTITY_FIELDS or item.grain in collected:
            raise RefreshInputError("Expected one transient input per grain")
        if not item.rows:
            raise EmptySourceError("Required route received no observations")
        if len(item.rows) > bounds.incoming_rows:
            raise ArtifactLimitError("Incoming dataset row bound exceeded")

    def _validate_input_limits(
        self, item: TransientInput, total_bytes: int, bounds: RefreshBounds
    ) -> int:
        if type(item.byte_count) is not int or item.byte_count <= 0:
            raise ArtifactError("Invalid transient input byte count")
        total_bytes += item.byte_count
        if total_bytes > self.store.bounds.total_bytes:
            raise ArtifactLimitError("Aggregate transient input byte bound exceeded")
        interval_days = (item.interval.end - item.interval.start).days + 1
        if interval_days > bounds.interval_days:
            raise ArtifactLimitError("Requested interval bound exceeded")
        return total_bytes

    @staticmethod
    def _validate_input_identity(
        item: TransientInput,
        expected: tuple[str, str, str] | None,
        bounds: RefreshBounds,
    ) -> tuple[str, str, str]:
        identity = item.run_id, item.contract_id, item.transformation_id
        if expected is not None and identity != expected:
            raise RefreshInputError("Mixed run, contract or transformation identities")
        if any(not value or len(value) > bounds.field_chars for value in identity):
            raise RefreshInputError("Invalid transient version identity")
        return identity
