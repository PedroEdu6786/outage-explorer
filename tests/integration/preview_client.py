"""Non-HTTP preview caller: enter through fresh application-owned access checks."""

from types import SimpleNamespace
from unittest.mock import Mock

from outage_explorer.application.dto import RequestAccess
from outage_explorer.application.pagination.cursor import CursorPaginator
from outage_explorer.application.preview_request import PreviewRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.preview import PreviewService
from outage_explorer.domain.access import Role


class PreviewClient:
    def __init__(
        self,
        access,
        publications,
        inputs,
        execution,
        sequences,
        encoding,
        *,
        response_bytes,
    ):
        self.access = access
        self.service = PreviewService(
            publications,
            inputs,
            execution,
            sequences,
            encoding,
            CursorPaginator(encoding.bytes, response_bytes=response_bytes),
        )

    def page(self, token, dataset_id, **values):
        identity = self.access.authenticate(token)
        approved = self.access.require_dataset(identity, dataset_id)
        return self.service.read(approved, PreviewRequest.parse(**values))


def synthetic_access(user_id="user"):
    access = Mock(spec=AccessService)
    access.authenticate.return_value = RequestAccess(
        SimpleNamespace(id=user_id, role=Role.ADMIN)
    )
    access.require_dataset.side_effect = lambda context, dataset: (
        AccessService.require_dataset(access, context, dataset)
    )
    return access
