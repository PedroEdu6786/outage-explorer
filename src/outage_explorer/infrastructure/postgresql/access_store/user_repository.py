"""ORM operations for seeded identity linkage."""

from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import SeedConflictError
from outage_explorer.domain.access import Role, SeededUser
from outage_explorer.infrastructure.postgresql.access_store.access_record import (
    RoleRecord,
    UserRecord,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.session_scope import with_session

_SEED_LOCK = 803079860865003


class PostgresqlUserRepository:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    @with_session
    def seed(self, session: Session, identities: tuple[SeedIdentity, ...]) -> int:
        # Serialize matching and insertion; the schema has no unique email index.
        session.execute(select(func.pg_advisory_xact_lock(_SEED_LOCK)))
        for role in Role:
            session.execute(
                insert(RoleRecord)
                .values(code=role.value)
                .on_conflict_do_nothing(index_elements=[RoleRecord.code])
            )
        added = 0
        for item in identities:
            records = session.scalars(
                select(UserRecord).where(
                    or_(
                        (UserRecord.identity_issuer == item.identity_issuer)
                        & (UserRecord.identity_subject == item.identity_subject),
                        func.lower(UserRecord.email) == func.lower(item.email),
                    )
                )
            ).all()
            if records:
                if len(records) != 1 or any(
                    getattr(records[0], field) != value
                    for field, value in (
                        ("identity_issuer", item.identity_issuer),
                        ("identity_subject", item.identity_subject),
                        ("email", item.email),
                        ("role_code", item.role),
                    )
                ):
                    raise SeedConflictError(
                        "Seed identity conflicts with existing linkage"
                    )
            else:
                session.add(
                    UserRecord(
                        id=str(uuid4()),
                        identity_issuer=item.identity_issuer,
                        identity_subject=item.identity_subject,
                        email=item.email,
                        role_code=item.role,
                    )
                )
                session.flush()
                added += 1
        return added

    @with_session
    def find_user(
        self, session: Session, issuer: str, subject: str
    ) -> SeededUser | None:
        record = session.scalar(
            select(UserRecord)
            .join(RoleRecord, RoleRecord.code == UserRecord.role_code)
            .where(
                UserRecord.identity_issuer == issuer,
                UserRecord.identity_subject == subject,
            )
        )
        return record.to_domain() if record is not None else None
