"""Parent-side bounded transport for the isolated analytical worker."""

from outage_explorer.application.ports.execution import (
    PreviewRead,
    PreviewRows,
    QueryRead,
)
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.transport_requests import (
    RequestEncoder,
)
from outage_explorer.infrastructure.worker_runtime.transport_responses import (
    ResponseDecoder,
)


class WorkerTransport:
    """Stable parent adapter for approved requests and untrusted responses."""

    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile
        self.bounds = profile.encoding_bounds
        self._requests = RequestEncoder(profile)
        self._responses = ResponseDecoder(profile)

    def request(self, request: PreviewRead | QueryRead) -> bytes:
        return self._requests.request(request)

    def decode(
        self, raw: bytes, *, request: PreviewRead | QueryRead, exit_code: int
    ) -> PreviewRows | QueryOutput:
        return self._responses.decode(raw, request=request, exit_code=exit_code)
