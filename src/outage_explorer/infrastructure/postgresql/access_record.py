"""ORM mappings for seeded users and bounded application login state."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outage_explorer.domain.access import LoginAttempt, Role, SeededUser
from outage_explorer.infrastructure.postgresql.orm_base import Base


class RoleRecord(Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(Text, primary_key=True)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    identity_issuer: Mapped[str] = mapped_column(Text)
    identity_subject: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    role_code: Mapped[str] = mapped_column(Text, ForeignKey("roles.code"))

    def to_domain(self) -> SeededUser:
        return SeededUser(
            self.id,
            self.identity_issuer,
            self.identity_subject,
            self.email,
            Role(self.role_code),
        )


class ApplicationSessionRecord(Base):
    __tablename__ = "application_sessions"

    token_digest: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    established_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttemptRecord(Base):
    __tablename__ = "login_attempts"

    state_digest: Mapped[str] = mapped_column(Text, primary_key=True)
    browser_binding_digest: Mapped[str] = mapped_column(Text)
    pkce_verifier: Mapped[str] = mapped_column(Text)
    callback_uri: Mapped[str] = mapped_column(Text)
    return_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_domain(self) -> LoginAttempt:
        return LoginAttempt(
            self.state_digest,
            self.browser_binding_digest,
            self.pkce_verifier,
            self.callback_uri,
            self.return_path,
            self.created_at,
            self.expires_at,
        )
