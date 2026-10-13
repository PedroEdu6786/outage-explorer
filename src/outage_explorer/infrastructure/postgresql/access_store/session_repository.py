"""ORM operations for application session leases."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from outage_explorer.domain.access import Session as AccessSession
from outage_explorer.infrastructure.postgresql.access_store.access_record import (
    ApplicationSessionRecord,
    RoleRecord,
    UserRecord,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.session_scope import with_session


class PostgresqlSessionRepository:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    @with_session
    def create_session(
        self,
        session: Session,
        token_digest: str,
        user_id: str,
        established_at: datetime,
        expires_at: datetime,
    ) -> None:
        session.add(
            ApplicationSessionRecord(
                token_digest=token_digest,
                user_id=user_id,
                established_at=established_at,
                expires_at=expires_at,
            )
        )

    @with_session
    def resolve_session(
        self, session: Session, token_digest: str, now: datetime
    ) -> AccessSession | None:
        row = session.execute(
            select(ApplicationSessionRecord, UserRecord)
            .join(UserRecord, UserRecord.id == ApplicationSessionRecord.user_id)
            .join(RoleRecord, RoleRecord.code == UserRecord.role_code)
            .where(
                ApplicationSessionRecord.token_digest == token_digest,
                ApplicationSessionRecord.revoked_at.is_(None),
                ApplicationSessionRecord.established_at <= now,
                ApplicationSessionRecord.expires_at > now,
            )
        ).one_or_none()
        if row is None:
            return None
        lease, user = row
        return AccessSession(
            token_digest, user.to_domain(), lease.established_at, lease.expires_at
        )

    @with_session
    def revoke_session(
        self, session: Session, token_digest: str, now: datetime
    ) -> None:
        session.execute(
            update(ApplicationSessionRecord)
            .where(ApplicationSessionRecord.token_digest == token_digest)
            .values(revoked_at=func.coalesce(ApplicationSessionRecord.revoked_at, now))
        )
