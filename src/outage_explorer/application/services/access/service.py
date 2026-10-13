"""Resolve fresh local identity and invalidate only the supplied session."""

from outage_explorer.application.dto import (
    CatalogAccess,
    CurrentIdentity,
    PreviewAccess,
    RequestAccess,
)
from outage_explorer.application.errors import (
    DatasetUnavailableError,
    ForbiddenError,
    UnauthenticatedError,
)
from outage_explorer.application.ports.access import SecurityMaterial, SessionStore
from outage_explorer.application.ports.clock import Clock
from outage_explorer.domain.access import (
    AccessOperation,
    AnalyticalGrain,
    AuthorizedAccess,
    Role,
    Session,
    permits_scope,
)
from outage_explorer.domain.datasets import PUBLIC_DATASETS


class AccessService:
    def __init__(
        self, sessions: SessionStore, security: SecurityMaterial, clock: Clock
    ) -> None:
        self._sessions = sessions
        self._security = security
        self._clock = clock

    def _digest(self, token: str) -> str:
        if (
            not isinstance(token, str)
            or len(token) != 43
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for character in token
            )
        ):
            raise UnauthenticatedError("Authentication required")
        return self._security.digest(token)

    def resolve(self, token: str) -> Session:
        digest = self._digest(token)
        now = self._clock.now()
        session = self._sessions.resolve_session(digest, now)
        if (
            session is None
            or session.token_digest != digest
            or not session.established_at <= now < session.expires_at
            or session.user.role not in Role
        ):
            raise UnauthenticatedError("Authentication required")
        return session

    def current_identity(self, token: str) -> CurrentIdentity:
        session = self.resolve(token)
        return CurrentIdentity(
            session.user, session.expires_at, self._security.csrf_token(token)
        )

    def logout(self, token: str) -> None:
        self._sessions.revoke_session(self._digest(token), self._clock.now())

    def authorize(
        self,
        token: str,
        operation: AccessOperation,
        *,
        grains: frozenset[AnalyticalGrain] = frozenset(),
    ) -> AuthorizedAccess:
        """Call for every use-case/page with all server-derived referenced grains.

        Caller roles, browser dataset labels and previous decisions are not inputs.
        Downstream services own reference extraction and result ownership; workers
        receive only approved analytical inputs, never session/store capabilities.
        """
        session = self.resolve(token)
        if not permits_scope(session.user.role, operation, grains):
            raise ForbiddenError("Access denied")
        return AuthorizedAccess(session.user, grains)

    def authenticate(self, token: str) -> RequestAccess:
        return RequestAccess(self.resolve(token).user)

    def require_roles(
        self, request_access: RequestAccess, roles: tuple[str, ...]
    ) -> RequestAccess:
        if request_access.principal.role.value not in roles:
            raise ForbiddenError("Access denied")
        return request_access

    def require_dataset(
        self, request_access: RequestAccess, dataset_id: str
    ) -> PreviewAccess:
        """Approve a public dataset using this request's authenticated identity."""
        dataset = next(
            (item for item in PUBLIC_DATASETS if item.id == dataset_id), None
        )
        if dataset is None:
            raise DatasetUnavailableError("Dataset unavailable")
        grains = frozenset({AnalyticalGrain(dataset.grain)})
        if not permits_scope(
            request_access.principal.role, AccessOperation.ANALYTICAL, grains
        ):
            # Unknown and forbidden dataset IDs have the same public outcome.
            raise DatasetUnavailableError("Dataset unavailable")
        return PreviewAccess(request_access.principal, dataset)

    def require_catalog(self, request_access: RequestAccess) -> CatalogAccess:
        """Approve the public datasets visible to this request's role."""
        role = request_access.principal.role
        datasets = tuple(
            dataset
            for dataset in PUBLIC_DATASETS
            if role is not Role.VIEWER or dataset.id == "national"
        )
        grains = frozenset(AnalyticalGrain(dataset.grain) for dataset in datasets)
        if not permits_scope(role, AccessOperation.ANALYTICAL, grains):
            raise ForbiddenError("Access denied")
        return CatalogAccess(request_access.principal, datasets)

    def validate_csrf(self, token: str, supplied: str) -> RequestAccess:
        request_access = self.authenticate(token)
        if not self._security.verify_csrf(token, supplied):
            raise ForbiddenError("Access denied")
        return request_access
