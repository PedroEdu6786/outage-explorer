"""Admin admission and fresh authorized reads; no source work at admission."""

import re
from collections.abc import Callable

from outage_explorer.application.dto import RefreshAdmissionRequest, RequestAccess
from outage_explorer.application.errors import InvalidRequestError
from outage_explorer.application.ports.access import SecurityMaterial
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.publication import RefreshConfiguration, RefreshRun


class RefreshService:
    def __init__(
        self,
        access: AccessService,
        store: RefreshStore,
        configuration: Callable[[], RefreshConfiguration],
        security: SecurityMaterial,
    ) -> None:
        self._access = access
        self._store = store
        self._configuration = configuration
        self._security = security

    def authorize(self, token: str) -> RequestAccess:
        """Resolve fresh Admin access for non-HTTP callers before invoking a use case."""
        request_access = self._access.authenticate(token)
        return self._access.require_roles(request_access, ("admin",))

    def admit(
        self, request_access: RequestAccess, request: RefreshAdmissionRequest
    ) -> RefreshRun:
        principal = request_access.principal
        key_digest = self._security.digest(request.idempotency_key)
        existing_run = self._store.replay(principal.id, key_digest)
        if existing_run is not None:
            return existing_run

        configuration = self._configuration()
        return self._store.admit(principal.id, key_digest, configuration)

    def status(self, request_access: RequestAccess, run_id: str) -> RefreshRun | None:
        if (
            not isinstance(run_id, str)
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", run_id
            )
            is None
        ):
            raise InvalidRequestError("Invalid refresh identity")
        return self._store.get_run(run_id)

    def latest(self, request_access: RequestAccess) -> RefreshRun | None:
        return self._store.latest()
