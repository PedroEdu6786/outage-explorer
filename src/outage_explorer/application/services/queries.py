"""Authorize references before inputs; execute unchanged SQL once, then page retention."""

from outage_explorer.application.errors import (
    DataUnavailableError,
    InvalidRequestError,
    QueryPageError,
)
from outage_explorer.application.ports.analytical_inputs import (
    PinnedInputs,
    PublishedInputs,
)
from outage_explorer.application.ports.execution import IsolatedExecution, QueryRead
from outage_explorer.application.ports.publication import PublicationStore
from outage_explorer.application.ports.query_results import QueryResults
from outage_explorer.application.ports.sql_inspection import SqlInspector
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation, AnalyticalGrain
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.query_results import validate_page


class QueryService:
    def __init__(
        self,
        access: AccessService,
        inspector: SqlInspector,
        publications: PublicationStore,
        inputs: PublishedInputs,
        execution: IsolatedExecution,
        results: QueryResults,
    ) -> None:
        self._access, self._inspector = access, inspector
        self._publications, self._inputs = publications, inputs
        self._execution, self._results = execution, results

    def _authorize(self, token: str, grains: frozenset[AnalyticalGrain]) -> str:
        authorization = self._access.authorize(
            token,
            AccessOperation.ANALYTICAL
            if grains
            else AccessOperation.ANALYTICAL_EXPRESSION,
            grains=grains,
        )
        return authorization.principal.id

    def execute(
        self, token: str, sql: str, *, page: int = 1, page_size: int = 100
    ) -> dict[str, object]:
        self._access.resolve(token)
        try:
            validate_page(page, page_size)
        except ValueError as exc:
            raise InvalidRequestError("Invalid SQL pagination") from exc
        inspected = self._inspector.inspect(sql)
        if inspected.sql != sql or inspected.reference_free != (not inspected.grains):
            raise InvalidRequestError("Invalid inspected SQL scope")
        grains = frozenset(AnalyticalGrain(grain) for grain in inspected.grains)
        owner = self._authorize(token, grains)
        retained = self._results.reserve(owner)
        execution = None
        pins: list[PinnedInputs] = []
        try:
            execution = self._execution.reserve()
            generation = self._publications.active_generation() if grains else None
            if grains and generation is None:
                raise DataUnavailableError("Published data unavailable")
            relations = []
            for dataset in PUBLIC_DATASETS:
                if AnalyticalGrain(dataset.grain) in grains:
                    assert generation is not None
                    pin = self._inputs.prepare(generation, dataset)
                    pins.append(pin)
                    execution.check_preparation()
                    relations.append((dataset, pin.files))
            output = execution.query(QueryRead(sql, tuple(relations)))
            # Prove worker termination before releasing pins or retaining success.
            execution.close()
            execution = None
            for pin in pins:
                pin.close()
            pins.clear()
            identity = retained.complete(
                output, grains, None if generation is None else generation.id, page_size
            )
            return self.page(token, identity.id, page=page, page_size=page_size)
        finally:
            # If reaping fails, hold pins/capacity rather than expose files to a
            # still-live worker. The supervisor must resolve uncertain liveness.
            if execution is not None:
                execution.close()
            for pin in pins:
                pin.close()
            retained.close()

    def page(
        self, token: str, query_id: str, *, page: int = 1, page_size: int | None = None
    ) -> dict[str, object]:
        principal = self._access.resolve(token).user
        try:
            validate_page(page, page_size)
        except ValueError as exc:
            raise InvalidRequestError("Invalid SQL pagination") from exc
        reader = self._results.acquire(query_id, principal.id)
        try:
            self._authorize(token, reader.identity.grains)
            if page_size is not None and page_size != reader.identity.page_size:
                raise QueryPageError("page_size_mismatch")
            response = reader.page(page)
            response.pop(
                "encoding_version", None
            )  # Internal spool version is not HTTP metadata.
            return response
        finally:
            reader.close()
