"""Single-use browser-bound login; no transaction spans provider work."""

from datetime import timedelta

from outage_explorer.application.dto import EstablishedSession, LoginRedirect
from outage_explorer.application.errors import (
    AccessConfigurationError,
    UnauthenticatedError,
)
from outage_explorer.application.ports.access import (
    AttemptStore,
    IdentityProvider,
    SecurityMaterial,
    SessionStore,
    UserStore,
)
from outage_explorer.application.ports.clock import Clock
from outage_explorer.domain.access import LoginAttempt, Role


class LoginService:
    def __init__(
        self,
        provider: IdentityProvider,
        users: UserStore,
        sessions: SessionStore,
        attempts: AttemptStore,
        security: SecurityMaterial,
        clock: Clock,
        *,
        callback_uri: str,
        allowed_destinations: frozenset[str] = frozenset({"/"}),
        session_seconds: int = 3600,
        attempt_seconds: int = 600,
    ) -> None:
        if (
            type(session_seconds) is not int
            or not 1 <= session_seconds <= 86400
            or type(attempt_seconds) is not int
            or not 1 <= attempt_seconds <= 3600
            or not callback_uri
            or not allowed_destinations
            or any(
                not path.startswith("/")
                or path.startswith("//")
                or "\\" in path
                or "#" in path
                or "?" in path
                for path in allowed_destinations
            )
        ):
            raise AccessConfigurationError("Invalid login configuration")
        self._provider = provider
        self._users = users
        self._sessions = sessions
        self._attempts = attempts
        self._security = security
        self._clock = clock
        self._session_seconds = session_seconds
        self._attempt_seconds = attempt_seconds
        self._callback_uri = callback_uri
        self._destinations = allowed_destinations

    def begin(self, return_to: str = "/") -> LoginRedirect:
        if return_to not in self._destinations:
            raise UnauthenticatedError("Login failed")
        state, binding, verifier = (self._security.random_token() for _ in range(3))
        now = self._clock.now()
        expiry = now + timedelta(seconds=self._attempt_seconds)
        attempt = LoginAttempt(
            self._security.digest(state),
            self._security.digest(binding),
            verifier,
            self._callback_uri,
            return_to,
            now,
            expiry,
        )
        url = self._provider.authorization_url(
            self._callback_uri, state, self._security.pkce_challenge(verifier)
        )
        self._attempts.create_attempt(attempt, now)
        return LoginRedirect(url, binding, expiry)

    def complete(
        self, code: str, state: str, browser_binding: str
    ) -> EstablishedSession:
        if any(
            not isinstance(value, str)
            or not value
            or len(value) > 4096
            or not value.isascii()
            for value in (code, state, browser_binding)
        ):
            raise UnauthenticatedError("Login failed")
        now = self._clock.now()
        attempt = self._attempts.consume_attempt(
            self._security.digest(state), self._security.digest(browser_binding), now
        )
        if (
            attempt is None
            or not attempt.created_at <= now < attempt.expires_at
            or attempt.callback_uri != self._callback_uri
            or attempt.return_to not in self._destinations
        ):
            raise UnauthenticatedError("Login failed")
        identity = self._provider.exchange(
            code, attempt.pkce_verifier, attempt.callback_uri
        )
        user = self._users.find_user(identity.issuer, identity.subject)
        if user is None or user.role not in Role:
            raise UnauthenticatedError("Login failed")
        token = self._security.random_token()
        established = self._clock.now()
        expiry = established + timedelta(seconds=self._session_seconds)
        self._sessions.create_session(
            self._security.digest(token), user.id, established, expiry
        )
        return EstablishedSession(token, user, expiry, attempt.return_to)
