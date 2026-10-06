"""Authenticated opaque visited-page cursors with independent bounded metadata."""

import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from threading import RLock

from outage_explorer.application.errors import (
    PreviewCapacityError,
    PreviewUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import PinnedInputs
from outage_explorer.application.ports.clock import Clock
from outage_explorer.application.ports.preview_sequences import (
    PreviewPosition,
    PreviewSequence,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import PublishedGeneration
from outage_explorer.domain.query_results import LIFETIME_SECONDS


@dataclass(frozen=True)
class PreviewBounds:
    per_user: int
    global_count: int
    metadata_bytes: int
    cursor_bytes: int

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Positive preview metadata bounds required")


@dataclass
class _State:
    sequence: PreviewSequence
    bytes: int
    active: int = 1
    retired: bool = False


class BoundedPreviewSequences:
    def __init__(self, clock: Clock, bounds: PreviewBounds, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("Cursor signing key requires at least 32 bytes")
        self._clock, self._bounds, self._key = clock, bounds, key
        self._states: dict[str, _State] = {}
        self._cursors: dict[str, tuple[str, tuple[str, ...] | None]] = {}
        self._bytes = 0
        self._lock = RLock()

    def create(
        self,
        user_id: str,
        dataset: Dataset,
        generation: PublishedGeneration,
        start: date | None,
        end: date | None,
        size: int,
        inputs: PinnedInputs,
    ) -> PreviewSequence:
        with self._lock:
            self.cleanup()
            # Charge all variable metadata including approved file identities.
            charge = (
                len(
                    repr(
                        (user_id, dataset, generation, start, end, size, inputs.files)
                    ).encode()
                )
                + 256
            )
            if (
                len(self._states) >= self._bounds.global_count
                or sum(s.sequence.user_id == user_id for s in self._states.values())
                >= self._bounds.per_user
                or self._bytes + charge > self._bounds.metadata_bytes
            ):
                raise PreviewCapacityError("Preview metadata capacity exhausted")
            sequence = PreviewSequence(
                secrets.token_urlsafe(24),
                user_id,
                dataset,
                generation,
                start,
                end,
                size,
                self._clock.now() + timedelta(seconds=LIFETIME_SECONDS),
                inputs,
            )
            self._states[sequence.id] = _State(sequence, charge)
            self._bytes += charge
            return sequence

    def cursor(self, sequence: PreviewSequence, after: tuple[str, ...] | None) -> str:
        with self._lock:
            state = self._states.get(sequence.id)
            if (
                state is None
                or state.retired
                or self._clock.now() >= sequence.expires_at
            ):
                raise PreviewUnavailableError("Preview unavailable")
            payload = json.dumps(
                [sequence.id, after], ensure_ascii=False, separators=(",", ":")
            ).encode()
            encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
            signature = base64.urlsafe_b64encode(
                hmac.digest(self._key, encoded, "sha256")
            ).rstrip(b"=")
            cursor = (encoded + b"." + signature).decode("ascii")
            if cursor not in self._cursors:
                charge = len(cursor.encode()) + len(payload) + 64
                if (
                    len(cursor) > self._bounds.cursor_bytes
                    or self._bytes + charge > self._bounds.metadata_bytes
                ):
                    raise PreviewCapacityError("Preview metadata capacity exhausted")
                self._cursors[cursor] = (sequence.id, after)
                state.bytes += charge
                self._bytes += charge
            return cursor

    def acquire(self, cursor: str, user_id: str, dataset: Dataset) -> PreviewPosition:
        with self._lock:
            self.cleanup()
            if not isinstance(cursor, str) or len(cursor) > self._bounds.cursor_bytes:
                raise PreviewUnavailableError("Preview unavailable")
            try:
                encoded, supplied = cursor.encode("ascii").split(b".")
                expected = base64.urlsafe_b64encode(
                    hmac.digest(self._key, encoded, "sha256")
                ).rstrip(b"=")
                if not hmac.compare_digest(supplied, expected):
                    raise ValueError
                sequence_id, after = self._cursors[cursor]
                state = self._states[sequence_id]
                if (
                    state.retired
                    or state.sequence.user_id != user_id
                    or state.sequence.dataset != dataset
                ):
                    raise ValueError
            except (ValueError, KeyError, UnicodeError):
                raise PreviewUnavailableError("Preview unavailable") from None
            state.active += 1
            return PreviewPosition(state.sequence, after)

    def release(self, sequence: PreviewSequence) -> None:
        with self._lock:
            state = self._states.get(sequence.id)
            if state is not None:
                state.active = max(0, state.active - 1)
            self.cleanup()

    def discard(self, sequence: PreviewSequence) -> None:
        with self._lock:
            state = self._states.get(sequence.id)
            if state is not None:
                state.retired = True
            self.cleanup()

    def cleanup(self) -> None:
        """Called by the supervising lifecycle as well as request admission."""
        with self._lock:
            for identity, state in tuple(self._states.items()):
                if self._clock.now() >= state.sequence.expires_at:
                    state.retired = True
                if state.retired and not state.active:
                    state.sequence.inputs.close()
                    self._bytes -= state.bytes
                    del self._states[identity]
                    self._cursors = {
                        c: p for c, p in self._cursors.items() if p[0] != identity
                    }

    def close(self) -> None:
        with self._lock:
            for state in self._states.values():
                state.retired = True
            self.cleanup()

    @property
    def active_leases(self) -> int:
        with self._lock:
            return sum(state.active for state in self._states.values())
