"""Validated access-store facade over focused PostgreSQL repositories."""

from datetime import datetime

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import (
    AccessConfigurationError,
    SeedConflictError,
)
from outage_explorer.domain.access import (
    LoginAttempt,
    Role,
    SeededUser,
    Session,
    SessionLease,
)
from outage_explorer.infrastructure.postgresql.login_attempt_repository import (
    PostgresqlLoginAttemptRepository,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.session_repository import (
    PostgresqlSessionRepository,
)
from outage_explorer.infrastructure.postgresql.user_repository import (
    PostgresqlUserRepository,
)


class PostgresqlAccessStore:
    def __init__(
        self,
        pool: BoundedPostgresqlPool,
        *,
        attempt_limit: int = 1000,
        users: PostgresqlUserRepository | None = None,
        sessions: PostgresqlSessionRepository | None = None,
        attempts: PostgresqlLoginAttemptRepository | None = None,
    ) -> None:
        if type(attempt_limit) is not int or not 1 <= attempt_limit <= 100000:
            raise AccessConfigurationError("Invalid login attempt bound")
        self._users = users or PostgresqlUserRepository(pool)
        self._sessions = sessions or PostgresqlSessionRepository(pool)
        self._attempts = attempts or PostgresqlLoginAttemptRepository(
            pool, attempt_limit=attempt_limit
        )

    def seed(self, identities: tuple[SeedIdentity, ...]) -> int:
        keys = [(item.identity_issuer, item.identity_subject) for item in identities]
        emails = [item.email.casefold() for item in identities]
        if (
            not identities
            or len(set(keys)) != len(keys)
            or len(set(emails)) != len(emails)
        ):
            raise SeedConflictError("Duplicate or empty seed identities")
        for item in identities:
            if item.role not in {role.value for role in Role} or any(
                not value.strip() or len(value) > bound
                for value, bound in (
                    (item.identity_issuer, 2048),
                    (item.identity_subject, 2048),
                    (item.email, 320),
                )
            ):
                raise SeedConflictError("Invalid seed identity")
        return self._users.seed(identities)

    def find_user(self, issuer: str, subject: str) -> SeededUser | None:
        return self._users.find_user(issuer, subject)

    def create_session(
        self,
        token_digest: str,
        user_id: str,
        established_at: datetime,
        expires_at: datetime,
    ) -> None:
        try:
            SessionLease(established_at, expires_at)
        except ValueError as error:
            raise AccessConfigurationError(str(error)) from None
        self._sessions.create_session(token_digest, user_id, established_at, expires_at)

    def resolve_session(self, token_digest: str, now: datetime) -> Session | None:
        return self._sessions.resolve_session(token_digest, now)

    def revoke_session(self, token_digest: str, now: datetime) -> None:
        self._sessions.revoke_session(token_digest, now)

    def create_attempt(self, attempt: LoginAttempt, now: datetime) -> None:
        if attempt.expires_at <= now or attempt.created_at > now:
            raise AccessConfigurationError("Invalid login attempt interval")
        self._attempts.create_attempt(attempt, now)

    def consume_attempt(
        self, state_digest: str, browser_binding_digest: str, now: datetime
    ) -> LoginAttempt | None:
        return self._attempts.consume_attempt(state_digest, browser_binding_digest, now)

    def cleanup(self, now: datetime) -> tuple[int, int]:
        return self._attempts.cleanup(now)
