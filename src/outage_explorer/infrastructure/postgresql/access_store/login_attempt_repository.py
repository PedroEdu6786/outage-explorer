"""ORM operations for bounded, one-time login attempts and state cleanup."""

from datetime import datetime
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from outage_explorer.application.errors import LoginAttemptLimitError
from outage_explorer.domain.access import LoginAttempt
from outage_explorer.infrastructure.postgresql.access_store.access_record import (
    ApplicationSessionRecord,
    LoginAttemptRecord,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.session_scope import with_session

_ADMISSION_LOCK = 803079860865002


class PostgresqlLoginAttemptRepository:
    def __init__(self, pool: BoundedPostgresqlPool, *, attempt_limit: int) -> None:
        self._pool = pool
        self._attempt_limit = attempt_limit

    @with_session
    def create_attempt(
        self, session: Session, attempt: LoginAttempt, now: datetime
    ) -> None:
        # The lock, expired-row reclamation, capacity check and insert are atomic.
        session.execute(select(func.pg_advisory_xact_lock(_ADMISSION_LOCK)))
        session.execute(
            delete(LoginAttemptRecord).where(LoginAttemptRecord.expires_at <= now)
        )
        count = session.scalar(select(func.count()).select_from(LoginAttemptRecord))
        if count is not None and count >= self._attempt_limit:
            raise LoginAttemptLimitError("Login attempt capacity reached")
        session.add(
            LoginAttemptRecord(
                state_digest=attempt.state_digest,
                browser_binding_digest=attempt.browser_binding_digest,
                pkce_verifier=attempt.pkce_verifier,
                callback_uri=attempt.callback_uri,
                return_path=attempt.return_to,
                created_at=attempt.created_at,
                expires_at=attempt.expires_at,
            )
        )

    @with_session
    def consume_attempt(
        self,
        session: Session,
        state_digest: str,
        browser_binding_digest: str,
        now: datetime,
    ) -> LoginAttempt | None:
        record = session.scalar(
            delete(LoginAttemptRecord)
            .where(
                LoginAttemptRecord.state_digest == state_digest,
                LoginAttemptRecord.browser_binding_digest == browser_binding_digest,
                LoginAttemptRecord.created_at <= now,
                LoginAttemptRecord.expires_at > now,
            )
            .returning(LoginAttemptRecord)
        )
        return record.to_domain() if record is not None else None

    @with_session
    def cleanup(self, session: Session, now: datetime) -> tuple[int, int]:
        # Maintenance deletes both login-state tables in one transaction.
        sessions = cast(
            CursorResult[tuple[()]],
            session.execute(
                delete(ApplicationSessionRecord).where(
                    ApplicationSessionRecord.expires_at <= now
                )
            ),
        ).rowcount
        attempts = cast(
            CursorResult[tuple[()]],
            session.execute(
                delete(LoginAttemptRecord).where(LoginAttemptRecord.expires_at <= now)
            ),
        ).rowcount
        return sessions, attempts
