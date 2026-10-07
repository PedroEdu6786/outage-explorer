"""Admin admission and fresh authorized reads; no source work at admission."""

import re
from collections.abc import Callable, Mapping

from outage_explorer.application.errors import InvalidRequestError
from outage_explorer.application.ports.access import SecurityMaterial
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation
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

    def admit(self, token: str, key: str, request: Mapping[str, object]) -> RefreshRun:
        principal = self._access.authorize(
            token, AccessOperation.REFRESH_INITIATE
        ).principal
        if (
            not isinstance(request, Mapping)
            or not isinstance(key, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key, flags=re.ASCII) is None
            or request
        ):
            raise InvalidRequestError("Invalid refresh request")
        digest = self._security.digest(key)
        replay = self._store.replay(principal.id, digest)
        if replay is not None:
            return replay
        return self._store.admit(principal.id, digest, self._configuration())

    def status(self, token: str, run_id: str) -> RefreshRun | None:
        self._access.authorize(token, AccessOperation.REFRESH_OUTCOME)
        if (
            not isinstance(run_id, str)
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", run_id
            )
            is None
        ):
            raise InvalidRequestError("Invalid refresh identity")
        return self._store.get_run(run_id)

    def latest(self, token: str) -> RefreshRun | None:
        self._access.authorize(token, AccessOperation.REFRESH_OUTCOME)
        return self._store.latest()
