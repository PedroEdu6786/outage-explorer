"""Read approved preview snapshots and preserve worker/input lifetimes."""

from dataclasses import dataclass

from outage_explorer.application.dto import PreviewAccess
from outage_explorer.application.errors import (
    DataUnavailableError,
)
from outage_explorer.application.pagination.cursor import CursorPage, CursorPaginator
from outage_explorer.application.ports.analytical_inputs import PublishedResourceInputs
from outage_explorer.application.ports.execution import (
    ExecutionReservation,
    IsolatedExecution,
    PreviewRead,
    PreviewRows,
)
from outage_explorer.application.ports.preview_sequences import (
    PreviewSequence,
    PreviewSequences,
)
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.application.preview_request import PreviewRequest
from outage_explorer.domain.datasets import Dataset


@dataclass
class _ActivePreviewLease:
    sequences: PreviewSequences
    sequence: PreviewSequence
    _closed: bool = False

    def close(self) -> None:
        if not self._closed:
            self.sequences.release(self.sequence)
            self._closed = True


class PreviewService:
    def __init__(
        self,
        publications: ResourcePublicationStore,
        inputs: PublishedResourceInputs,
        execution: IsolatedExecution,
        sequences: PreviewSequences,
        encoding: TabularEncoding,
        paginator: CursorPaginator,
    ) -> None:
        self._publications, self._inputs = publications, inputs
        self._execution, self._sequences, self._encoding = (
            execution,
            sequences,
            encoding,
        )
        self._paginator = paginator

    def read(
        self,
        access: PreviewAccess,
        request: PreviewRequest,
    ) -> dict[str, object]:
        dataset = access.dataset
        user_id = access.principal.id
        sequence: PreviewSequence | None = None
        execution_slot = None
        initial = request.cursor is None
        try:
            if request.cursor is not None:
                position = self._sequences.acquire(request.cursor, user_id, dataset)
                sequence, after = position.sequence, position.after
            else:
                after = None
            # Reserve before publication/files on initial reads; no download on busy.
            execution_slot = self._execution.acquire_slot()
            if sequence is None:
                sequence = self._start_sequence(
                    user_id, dataset, request, execution_slot
                )
            result = execution_slot.preview(
                PreviewRead(
                    dataset,
                    sequence.inputs.files,
                    sequence.start,
                    sequence.end,
                    after,
                    sequence.size,
                    sequence.facility,
                )
            )
            return self._response(sequence, after, result)
        except BaseException:
            if initial and sequence is not None:
                self._sequences.discard(sequence)
            raise
        finally:
            self._release_read(execution_slot, sequence)

    def _release_read(
        self,
        execution_slot: ExecutionReservation | None,
        sequence: PreviewSequence | None,
    ) -> None:
        # Unreaped workers retain capacity and pins until termination is proved.
        if execution_slot is not None:
            try:
                execution_slot.close()
            except BaseException:
                leases = (
                    ()
                    if sequence is None
                    else (_ActivePreviewLease(self._sequences, sequence),)
                )
                execution_slot.handoff(leases)
                raise
        if sequence is not None:
            self._sequences.release(sequence)

    def _start_sequence(
        self,
        user_id: str,
        dataset: Dataset,
        request: PreviewRequest,
        execution_slot: ExecutionReservation,
    ) -> PreviewSequence:
        generation = self._publications.active_generation()
        if generation is None:
            raise DataUnavailableError("Published data unavailable")
        inputs = self._inputs.prepare(generation, dataset)
        try:
            execution_slot.check_preparation()
            return self._sequences.create(
                user_id,
                dataset,
                generation,
                request.start,
                request.end,
                request.page_size,
                inputs,
                facility=request.facility,
            )
        except BaseException:
            inputs.close()
            raise

    def _response(
        self,
        sequence: PreviewSequence,
        after: tuple[str, ...] | None,
        result: PreviewRows,
    ) -> dict[str, object]:
        dataset = sequence.dataset
        page = CursorPage(
            rows=tuple(self._encoding.row(dataset.columns, row) for row in result.rows),
            keys=result.keys,
            has_more=result.has_more,
            size=sequence.size,
            after=after,
            cursor=lambda key: self._sequences.cursor(sequence, key),
            metadata={
                "dataset": dataset.id,
                "generation_id": sequence.generation.id,
                "columns": self._encoding.columns(dataset.columns),
                "expires_at": sequence.expires_at.isoformat().replace("+00:00", "Z"),
            },
        )
        return self._paginator.paginate(page)
