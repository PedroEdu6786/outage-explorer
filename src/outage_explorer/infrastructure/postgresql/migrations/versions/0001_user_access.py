"""Essential seeded users and bounded application login state."""

from alembic import op

revision = "0001_user_access"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE roles (
            code text PRIMARY KEY CHECK (code IN ('viewer', 'analyst', 'admin'))
        )
    """)
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY,
            identity_issuer text NOT NULL CHECK (btrim(identity_issuer) <> '' AND length(identity_issuer) <= 2048),
            identity_subject text NOT NULL CHECK (btrim(identity_subject) <> '' AND length(identity_subject) <= 2048),
            email text NOT NULL CHECK (btrim(email) <> '' AND length(email) <= 320),
            role_code text NOT NULL REFERENCES roles(code),
            UNIQUE (identity_issuer, identity_subject)
        )
    """)
    op.execute("""
        CREATE TABLE application_sessions (
            token_digest text PRIMARY KEY CHECK (token_digest ~ '^[0-9a-f]{64}$'),
            user_id uuid NOT NULL REFERENCES users(id),
            established_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            revoked_at timestamptz,
            CHECK (expires_at > established_at),
            CHECK (revoked_at IS NULL OR revoked_at >= established_at)
        )
    """)
    op.execute("""
        CREATE INDEX application_sessions_expiry ON application_sessions(expires_at)
    """)
    op.execute("""
        CREATE FUNCTION preserve_session_lease() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.established_at IS DISTINCT FROM OLD.established_at
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
               OR NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                RAISE EXCEPTION 'Application session lease is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER application_session_lease BEFORE UPDATE ON application_sessions
        FOR EACH ROW EXECUTE FUNCTION preserve_session_lease()
    """)
    op.execute("""
        CREATE TABLE login_attempts (
            state_digest text PRIMARY KEY CHECK (state_digest ~ '^[0-9a-f]{64}$'),
            browser_binding_digest text NOT NULL
                CHECK (browser_binding_digest ~ '^[0-9a-f]{64}$'),
            pkce_verifier text NOT NULL CHECK (
                length(pkce_verifier) BETWEEN 43 AND 128
                AND pkce_verifier ~ '^[A-Za-z0-9._~-]+$'
            ),
            callback_uri text NOT NULL CHECK (btrim(callback_uri) <> '' AND length(callback_uri) <= 2048),
            return_path text NOT NULL CHECK (
                length(return_path) BETWEEN 1 AND 2048
                AND left(return_path, 1) = '/' AND left(return_path, 2) <> '//'
            ),
            created_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK (expires_at > created_at)
        )
    """)
    op.execute("CREATE INDEX login_attempts_expiry ON login_attempts(expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE login_attempts")
    op.execute("DROP TABLE application_sessions")
    op.execute("DROP FUNCTION preserve_session_lease()")
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE roles")
