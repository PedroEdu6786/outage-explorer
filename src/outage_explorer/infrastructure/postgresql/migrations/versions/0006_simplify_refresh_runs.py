"""Remove unused refresh metadata and constant idempotency dimensions (ADR-0065)."""

from alembic import op

revision = "0006_simplify_refresh_runs"
down_revision = "0005_remove_manifest_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION preserve_refresh_history()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'published_generations' OR TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Durable publication history is immutable';
            END IF;
            IF (NEW.id, NEW.requester_id, NEW.key_digest,
                NEW.configuration, NEW.base_generation_id, NEW.admitted_at)
                IS DISTINCT FROM
                (OLD.id, OLD.requester_id, OLD.key_digest,
                OLD.configuration, OLD.base_generation_id, OLD.admitted_at) THEN
                RAISE EXCEPTION 'Refresh admission is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        ALTER TABLE refresh_runs
        DROP CONSTRAINT refresh_runs_requester_id_operation_key_digest_key,
        DROP COLUMN operation,
        DROP COLUMN request_identity,
        DROP COLUMN updated_at,
        ADD CONSTRAINT refresh_runs_requester_key UNIQUE (requester_id, key_digest)
    """)


def downgrade() -> None:
    raise RuntimeError("Cannot downgrade: removed refresh metadata cannot be restored")
