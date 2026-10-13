"""Authorized numbered reads from one retained SQL result."""

from outage_explorer.application.errors import (
    InvalidRequestError,
    QueryPageError,
    QueryUnavailableError,
)
from outage_explorer.application.pagination.numbered import NumberedPaginator
from outage_explorer.application.ports.query_results import QueryResults, ResultReader
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation, AuthorizedAccess
from outage_explorer.domain.query_results import ResultIdentity


class QueryResultPager:
    def __init__(self, access: AccessService, results: QueryResults) -> None:
        self._access = access
        self._results = results

    @staticmethod
    def validate(page: int, page_size: int | None) -> None:
        """Keep direct callers within the same bounds as validated HTTP requests."""
        try:
            NumberedPaginator.validate(page, page_size)
        except ValueError as exc:
            raise InvalidRequestError("Invalid SQL pagination") from exc

    def read(
        self, token: str, query_id: str, *, page: int = 1, page_size: int | None = None
    ) -> dict[str, object]:
        principal = self._access.resolve(token).user
        self.validate(page, page_size)
        reader = self._results.acquire(query_id, principal.id)
        try:
            grains = reader.identity.grains
            self._access.authorize(
                token,
                AccessOperation.ANALYTICAL
                if grains
                else AccessOperation.ANALYTICAL_EXPRESSION,
                grains=grains,
            )
            return self._response(reader, page, page_size)
        finally:
            reader.close()

    def read_authorized(
        self,
        authorization: AuthorizedAccess,
        identity: ResultIdentity,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        """Read the first page using the scope approved for this execution."""
        reader = self._results.acquire(identity.id, authorization.principal.id)
        try:
            if reader.identity != identity or authorization.grains != identity.grains:
                raise QueryUnavailableError("Query result unavailable")
            return self._response(reader, page, page_size)
        finally:
            reader.close()

    @staticmethod
    def _response(
        reader: ResultReader, page: int, page_size: int | None
    ) -> dict[str, object]:
        """Build a numbered page from an already authorized retained reader."""
        if page_size is not None and page_size != reader.identity.page_size:
            raise QueryPageError("page_size_mismatch")
        response = NumberedPaginator.paginate(reader.page(page))
        response.pop("encoding_version", None)
        return response
