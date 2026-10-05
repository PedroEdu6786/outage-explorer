"""Fresh authorization, snapshot-bound keyset reads and complete-row byte bounds."""

from datetime import date

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
    InvalidRequestError,
)
from outage_explorer.application.ports.analytical_inputs import PublishedInputs
from outage_explorer.application.ports.execution import IsolatedExecution, PreviewRead
from outage_explorer.application.ports.preview_sequences import (
    PreviewSequence,
    PreviewSequences,
)
from outage_explorer.application.ports.publication import PublicationStore
from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation, AnalyticalGrain
from outage_explorer.domain.datasets import PUBLIC_DATASETS


class PreviewService:
    def __init__(
        self,
        access: AccessService,
        publications: PublicationStore,
        inputs: PublishedInputs,
        execution: IsolatedExecution,
        sequences: PreviewSequences,
        encoding: TabularEncoding,
        *,
        response_bytes: int,
    ) -> None:
        if type(response_bytes) is not int or response_bytes <= 0:
            raise ValueError("Positive preview response byte bound required")
        self._access, self._publications, self._inputs = access, publications, inputs
        self._execution, self._sequences, self._encoding = (
            execution,
            sequences,
            encoding,
        )
        self._response_bytes = response_bytes

    def page(
        self,
        token: str,
        dataset_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        size: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        # Invalid/unknown IDs still resolve identity before returning an error.
        self._access.resolve(token)
        dataset = next(
            (item for item in PUBLIC_DATASETS if item.id == dataset_id), None
        )
        if dataset is None:
            raise DataUnavailableError("Dataset unavailable")
        authorization = self._access.authorize(
            token,
            AccessOperation.ANALYTICAL,
            grains=frozenset({AnalyticalGrain(dataset.grain)}),
        )
        if cursor is not None and any(
            value is not None for value in (start, end, size)
        ):
            raise InvalidRequestError("Continuation accepts only its cursor")
        if cursor is None and (
            any(value is not None and type(value) is not date for value in (start, end))
            or start is not None
            and end is not None
            and start > end
            or size is not None
            and (type(size) is not int or not 1 <= size <= 500)
        ):
            raise InvalidRequestError("Invalid preview parameters")
        sequence: PreviewSequence | None = None
        reservation = None
        initial = cursor is None
        try:
            if cursor is not None:
                position = self._sequences.acquire(
                    cursor, authorization.principal.id, dataset
                )
                sequence, after = position.sequence, position.after
            else:
                after = None
            # Reserve before publication/files on initial reads; no download on busy.
            reservation = self._execution.reserve()
            if sequence is None:
                generation = self._publications.active_generation()
                if generation is None:
                    raise DataUnavailableError("Published data unavailable")
                inputs = self._inputs.prepare(generation, dataset)
                try:
                    reservation.check_preparation()
                    sequence = self._sequences.create(
                        authorization.principal.id,
                        dataset,
                        generation,
                        start,
                        end,
                        100 if size is None else size,
                        inputs,
                    )
                except BaseException:
                    inputs.close()
                    raise
            result = reservation.preview(
                PreviewRead(
                    dataset,
                    sequence.inputs.files,
                    sequence.start,
                    sequence.end,
                    after,
                    sequence.size,
                )
            )
            if (
                len(result.rows) != len(result.keys)
                or len(result.rows) > sequence.size
                or result.has_more
                and not result.rows
            ):
                raise AnalyticalResourceError("Invalid preview worker output")
            page_cursor = self._sequences.cursor(sequence, after)
            columns = self._encoding.columns(dataset.columns)
            rows = [self._encoding.row(dataset.columns, row) for row in result.rows]
            count = len(rows)
            while True:
                has_more = result.has_more or count < len(rows)
                next_cursor = (
                    self._sequences.cursor(sequence, result.keys[count - 1])
                    if has_more and count
                    else None
                )
                response: dict[str, object] = {
                    "dataset": dataset.id,
                    "generation_id": sequence.generation.id,
                    "columns": columns,
                    "rows": rows[:count],
                    "page_size": sequence.size,
                    "page_cursor": page_cursor,
                    "next_cursor": next_cursor,
                    "has_more": has_more,
                    "expires_at": sequence.expires_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                }
                if self._encoding.bytes(response) <= self._response_bytes and (
                    count or not rows
                ):
                    return response
                count -= 1
                if count < 1:
                    raise AnalyticalResourceError(
                        "Preview row or envelope exceeds response byte bound"
                    )
        except BaseException:
            if initial and sequence is not None:
                self._sequences.discard(sequence)
            raise
        finally:
            # An unreaped worker can still use its inputs. Retain both capacity
            # and the active pin until the runtime supervisor proves termination.
            if reservation is not None:
                reservation.close()
            if sequence is not None:
                self._sequences.release(sequence)
