"""Parameterized repositories for seeded identities and fixed login state."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import (
    AccessConfigurationError,
    LoginAttemptLimitError,
    SeedConflictError,
)
from outage_explorer.domain.access import LoginAttempt, Role, SeededUser, Session
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool

_ADMISSION_LOCK = 803079860865002
_SEED_LOCK = 803079860865003


def _aware(*values: datetime) -> None:
    if any(value.tzinfo is None or value.utcoffset() is None for value in values):
        raise AccessConfigurationError("Access timestamps must include a timezone")


def _user(row: dict[str, Any]) -> SeededUser:
    return SeededUser(
        str(row["id"]),
        row["identity_issuer"],
        row["identity_subject"],
        row["email"],
        Role(row["role_code"]),
    )


class PostgresqlAccessStore:
    def __init__(
        self, pool: BoundedPostgresqlPool, *, attempt_limit: int = 1000
    ) -> None:
        if type(attempt_limit) is not int or not 1 <= attempt_limit <= 100000:
            raise AccessConfigurationError("Invalid login attempt bound")
        self._pool = pool
        self._attempt_limit = attempt_limit

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
        added = 0
        with self._pool.connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (_SEED_LOCK,))
            for role in Role:
                connection.execute(
                    "INSERT INTO roles(code) VALUES (%s) ON CONFLICT DO NOTHING",
                    (role.value,),
                )
            for item in identities:
                rows = connection.execute(
                    "SELECT * FROM users WHERE (identity_issuer=%s AND identity_subject=%s) OR lower(email)=lower(%s)",
                    (item.identity_issuer, item.identity_subject, item.email),
                ).fetchall()
                if rows:
                    if len(rows) != 1 or any(
                        rows[0][field] != value
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
                    connection.execute(
                        "INSERT INTO users(id, identity_issuer, identity_subject, email, role_code) VALUES (%s,%s,%s,%s,%s)",
                        (
                            uuid4(),
                            item.identity_issuer,
                            item.identity_subject,
                            item.email,
                            item.role,
                        ),
                    )
                    added += 1
        return added

    def find_user(self, issuer: str, subject: str) -> SeededUser | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT u.* FROM users u JOIN roles r ON r.code=u.role_code WHERE identity_issuer=%s AND identity_subject=%s",
                (issuer, subject),
            ).fetchone()
            return _user(row) if row else None

    def create_session(
        self,
        token_digest: str,
        user_id: str,
        established_at: datetime,
        expires_at: datetime,
    ) -> None:
        _aware(established_at, expires_at)
        with self._pool.connection() as connection:
            connection.execute(
                "INSERT INTO application_sessions(token_digest,user_id,established_at,expires_at) VALUES (%s,%s,%s,%s)",
                (token_digest, user_id, established_at, expires_at),
            )

    def resolve_session(self, token_digest: str, now: datetime) -> Session | None:
        _aware(now)
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT u.*, s.established_at, s.expires_at FROM application_sessions s JOIN users u ON u.id=s.user_id JOIN roles r ON r.code=u.role_code WHERE s.token_digest=%s AND s.revoked_at IS NULL AND s.established_at<=%s AND s.expires_at>%s",
                (token_digest, now, now),
            ).fetchone()
            return (
                Session(
                    token_digest, _user(row), row["established_at"], row["expires_at"]
                )
                if row
                else None
            )

    def revoke_session(self, token_digest: str, now: datetime) -> None:
        _aware(now)
        with self._pool.connection() as connection:
            connection.execute(
                "UPDATE application_sessions SET revoked_at=COALESCE(revoked_at,%s) WHERE token_digest=%s",
                (now, token_digest),
            )

    def create_attempt(self, attempt: LoginAttempt, now: datetime) -> None:
        _aware(now, attempt.created_at, attempt.expires_at)
        with self._pool.connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (_ADMISSION_LOCK,))
            count = connection.execute(
                "SELECT count(*) AS total FROM login_attempts"
            ).fetchone()
            if count is not None and count["total"] >= self._attempt_limit:
                raise LoginAttemptLimitError("Login attempt capacity reached")
            if attempt.expires_at <= now or attempt.created_at > now:
                raise AccessConfigurationError("Invalid login attempt interval")
            connection.execute(
                "INSERT INTO login_attempts(state_digest,browser_binding_digest,pkce_verifier,callback_uri,return_path,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    attempt.state_digest,
                    attempt.browser_binding_digest,
                    attempt.pkce_verifier,
                    attempt.callback_uri,
                    attempt.return_to,
                    attempt.created_at,
                    attempt.expires_at,
                ),
            )

    def consume_attempt(
        self, state_digest: str, browser_binding_digest: str, now: datetime
    ) -> LoginAttempt | None:
        _aware(now)
        with self._pool.connection() as connection:
            row = connection.execute(
                "DELETE FROM login_attempts WHERE state_digest=%s AND browser_binding_digest=%s AND created_at<=%s AND expires_at>%s RETURNING *",
                (state_digest, browser_binding_digest, now, now),
            ).fetchone()
            return (
                LoginAttempt(
                    row["state_digest"],
                    row["browser_binding_digest"],
                    row["pkce_verifier"],
                    row["callback_uri"],
                    row["return_path"],
                    row["created_at"],
                    row["expires_at"],
                )
                if row
                else None
            )

    def cleanup(self, now: datetime) -> tuple[int, int]:
        _aware(now)
        with self._pool.connection() as connection:
            sessions = connection.execute(
                "DELETE FROM application_sessions WHERE expires_at<=%s", (now,)
            ).rowcount
            attempts = connection.execute(
                "DELETE FROM login_attempts WHERE expires_at<=%s", (now,)
            ).rowcount
            return sessions, attempts
