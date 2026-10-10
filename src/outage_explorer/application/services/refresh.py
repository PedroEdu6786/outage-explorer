"""Admin admission and fresh authorized reads; no source work at admission."""

import re
from collections.abc import Callable, Mapping

from outage_explorer.application.errors import InvalidRequestError
from outage_explorer.application.ports.access import SecurityMaterial
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation
from outage_explorer.domain.publication import RefreshConfiguration, RefreshRun

MIN_IDEMPOTENCY_KEY_LENGTH = 16
MAX_IDEMPOTENCY_KEY_LENGTH = 128
ALLOWED_IDEMPOTENCY_KEY_CHARACTERS = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
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

    def admit(self, token: str, key: str, request: Mapping[str, object]) -> RefreshRun:
        principal = self._access.authorize(
            token, AccessOperation.REFRESH_INITIATE
        ).principal
        self._validate_admission_request(key, request)

        key_digest = self._security.digest(key)
        existing_run = self._store.replay(principal.id, key_digest)
        if existing_run is not None:
            return existing_run

        configuration = self._configuration()
        return self._store.admit(principal.id, key_digest, configuration)

    @staticmethod
    def _validate_admission_request(
        idempotency_key: str, request_body: Mapping[str, object]
    ) -> None:
        # Refresh accepts an empty JSON object: callers cannot supply options.
        if not isinstance(request_body, Mapping):
            raise InvalidRequestError("Invalid refresh request")
        if len(request_body) != 0:
            raise InvalidRequestError("Invalid refresh request")

        if not isinstance(idempotency_key, str):
            raise InvalidRequestError("Invalid refresh request")
        if len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
            raise InvalidRequestError("Invalid refresh request")
        if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise InvalidRequestError("Invalid refresh request")

        for character in idempotency_key:
            if character not in ALLOWED_IDEMPOTENCY_KEY_CHARACTERS:
                raise InvalidRequestError("Invalid refresh request")

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
