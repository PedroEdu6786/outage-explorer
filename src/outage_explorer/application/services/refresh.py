"""Admin admission and fresh authorized reads; no source work at admission."""

import re
from collections.abc import Callable

from outage_explorer.application.dto import RequestAccess
from outage_explorer.application.errors import InvalidRequestError, RefreshBusyError
from outage_explorer.application.ports.access import SecurityMaterial
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.refresh_request import RefreshAdmissionRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.publication import RefreshConfiguration, RefreshRun
from outage_explorer.domain.publication_policy import (
    RefreshAdmissionSlotBusyError,
    replay_or_require_available,
    require_initial_load_start,
)

# Canonical lowercase UUID text: 8-4-4-4-12 hexadecimal characters.
REFRESH_RUN_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def is_valid_run_id(run_id: object) -> bool:
    return (
        isinstance(run_id, str) and REFRESH_RUN_ID_PATTERN.fullmatch(run_id) is not None
    )


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
        """Legacy direct-call adapter; currently used only by tests.

        TODO: Move test setup to AccessService and remove this method when the
        non-HTTP access contract in ADR-0066 is updated. HTTP uses route guards.
        """
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
        with self._store.admission_transaction() as admission:
            existing_run = admission.replay(principal.id, key_digest)
            try:
                replay = replay_or_require_available(
                    existing_run, admission.active_run_id
                )
            except RefreshAdmissionSlotBusyError:
                raise RefreshBusyError("Refresh already admitted") from None
            if replay is not None:
                return replay

            admission.require_supported_base()
            require_initial_load_start(configuration, admission.base_generation_id)
            return admission.create_queued_run(principal.id, key_digest, configuration)

    def status(self, request_access: RequestAccess, run_id: str) -> RefreshRun | None:
        if not is_valid_run_id(run_id):
            raise InvalidRequestError("Invalid refresh identity")
        return self._store.get_run(run_id)

    def latest(self, request_access: RequestAccess) -> RefreshRun | None:
        return self._store.latest()
