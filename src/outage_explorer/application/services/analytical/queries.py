"""Authorize references before inputs; execute unchanged SQL once, then page retention."""

from outage_explorer.application.errors import (
    DataUnavailableError,
    InvalidRequestError,
)
from outage_explorer.application.ports.analytical_inputs import (
    PinnedInputs,
    PublishedResourceInputs,
)
from outage_explorer.application.ports.execution import (
    ExecutionReservation,
    IsolatedExecution,
    QueryRead,
)
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.query_results import (
    QueryResults,
    ResultReservation,
)
from outage_explorer.application.ports.sql_inspection import SqlInspector
from outage_explorer.application.services.access.service import AccessService
from outage_explorer.application.services.analytical.query_result_pager import (
    QueryResultPager,
)
from outage_explorer.domain.access import (
    AccessOperation,
    AnalyticalGrain,
    AuthorizedAccess,
)
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.query_results import ResultIdentity


class QueryService:
    def __init__(
        self,
        access: AccessService,
        inspector: SqlInspector,
        publications: ResourcePublicationStore,
        inputs: PublishedResourceInputs,
        execution: IsolatedExecution,
        results: QueryResults,
        pages: QueryResultPager,
    ) -> None:
        self._access, self._inspector = access, inspector
        self._publications, self._inputs = publications, inputs
        self._execution, self._results = execution, results
        self.pages = pages

    def _authorize(
        self, token: str, grains: frozenset[AnalyticalGrain]
    ) -> AuthorizedAccess:
        return self._access.authorize(
            token,
            AccessOperation.ANALYTICAL
            if grains
            else AccessOperation.ANALYTICAL_EXPRESSION,
            grains=grains,
        )

    def execute(
        self, token: str, sql: str, *, page: int = 1, page_size: int = 100
    ) -> dict[str, object]:
        self._access.resolve(token)
        grains = self._inspect_grains(sql)
        authorization = self._authorize(token, grains)
        identity = self._execute_once(
            authorization.principal.id, sql, grains, page_size
        )
        return self.pages.read_authorized(
            authorization, identity, page=page, page_size=page_size
        )

    def _inspect_grains(self, sql: str) -> frozenset[AnalyticalGrain]:
        inspected = self._inspector.inspect(sql)
        if inspected.sql != sql or inspected.reference_free != (not inspected.grains):
            raise InvalidRequestError("Invalid inspected SQL scope")
        return frozenset(AnalyticalGrain(grain) for grain in inspected.grains)

    def _execute_once(
        self,
        owner: str,
        sql: str,
        grains: frozenset[AnalyticalGrain],
        page_size: int,
    ) -> ResultIdentity:
        retained = self._results.reserve(owner)
        execution: ExecutionReservation | None = None
        pins: list[PinnedInputs] = []
        try:
            execution = self._execution.acquire_slot()
            request, generation_id = self._prepare_query(sql, grains, execution, pins)
            output = execution.query(request)
            # Prove worker termination before releasing pins or retaining success.
            execution.close()
            execution = None
            for pin in pins:
                pin.close()
            pins.clear()
            return retained.complete(output, grains, generation_id, page_size)
        finally:
            self._release_execution(execution, pins, retained)

    def _prepare_query(
        self,
        sql: str,
        grains: frozenset[AnalyticalGrain],
        execution: ExecutionReservation,
        pins: list[PinnedInputs],
    ) -> tuple[QueryRead, str | None]:
        if not grains:
            return QueryRead(sql, ()), None

        generation = self._publications.active_generation()
        if generation is None:
            raise DataUnavailableError("Published data unavailable")
        relations = []
        for dataset in PUBLIC_DATASETS:
            if AnalyticalGrain(dataset.grain) in grains:
                pin = self._inputs.prepare(generation, dataset)
                pins.append(pin)
                execution.check_preparation()
                relations.append((dataset, pin.files))
        return QueryRead(sql, tuple(relations)), generation.id

    @staticmethod
    def _release_execution(
        execution: ExecutionReservation | None,
        pins: list[PinnedInputs],
        retained: ResultReservation,
    ) -> None:
        # If reaping fails, hold pins/capacity until the supervisor resolves it.
        if execution is not None:
            try:
                execution.close()
            except BaseException:
                execution.handoff((*pins, retained))
                raise
        for pin in pins:
            pin.close()
        retained.close()
