"""Add durable refresh coordination and immutable publication history."""

from alembic import op

revision = "0002_data_api"
down_revision = "0001_user_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE refresh_runs (
            id uuid PRIMARY KEY,
            requester_id uuid NOT NULL REFERENCES users(id),
            operation text NOT NULL DEFAULT 'refresh' CHECK (operation = 'refresh'),
            key_digest text NOT NULL CHECK (key_digest ~ '^[0-9a-f]{64}$'),
            request_identity text NOT NULL CHECK (length(request_identity) BETWEEN 1 AND 256),
            configuration jsonb NOT NULL,
            base_generation_id uuid,
            status text NOT NULL CHECK (status IN ('accepted','running','succeeded','retained','failed','interrupted','publication_unknown')),
            stage text NOT NULL CHECK (stage IN ('queued','retrieving','modeling','persisting','verifying','publishing','finished')),
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            epoch bigint,
            generation_id uuid,
            publication text NOT NULL CHECK (publication IN ('pending','published','not_published','unknown')),
            quality_json jsonb CHECK (octet_length(quality_json::text) <= 65536),
            failure text CHECK (failure IN ('configuration','prior_integrity','retrieval','resource','representation','artifact_integrity','unusable_input','report','interrupted','internal')),
            no_publication_reason text CHECK (no_publication_reason = 'all_incoming_rows_excluded'),
            UNIQUE (requester_id, operation, key_digest),
            CHECK ((status IN ('accepted','running') AND publication = 'pending')
                OR (status = 'succeeded' AND publication = 'published' AND generation_id IS NOT NULL)
                OR (status IN ('retained','failed','interrupted') AND publication = 'not_published')
                OR (status = 'publication_unknown' AND publication = 'unknown'))
        )
    """)
    op.execute("""
        CREATE TABLE published_generations (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL UNIQUE REFERENCES refresh_runs(id),
            base_generation_id uuid REFERENCES published_generations(id),
            manifest_key text NOT NULL CHECK (length(manifest_key) BETWEEN 1 AND 2048),
            manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
            verification_version text NOT NULL CHECK (verification_version = 'v1'),
            verified_at timestamptz NOT NULL,
            datasets jsonb NOT NULL CHECK (jsonb_array_length(datasets) = 3)
        )
    """)
    op.execute(
        "ALTER TABLE refresh_runs ADD FOREIGN KEY (base_generation_id) REFERENCES published_generations(id)"
    )
    op.execute(
        "ALTER TABLE refresh_runs ADD FOREIGN KEY (generation_id) REFERENCES published_generations(id)"
    )
    op.execute("""
        CREATE TABLE refresh_coordination (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            active_run_id uuid REFERENCES refresh_runs(id),
            epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0),
            owner_identity text,
            lease_until timestamptz,
            active_generation_id uuid REFERENCES published_generations(id),
            CHECK ((owner_identity IS NULL) = (lease_until IS NULL)),
            CHECK (owner_identity IS NULL OR active_run_id IS NOT NULL)
        )
    """)
    op.execute("INSERT INTO refresh_coordination(singleton) VALUES (true)")
    op.execute("CREATE INDEX refresh_latest ON refresh_runs(admitted_at DESC, id DESC)")
    op.execute("""
        CREATE FUNCTION preserve_refresh_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'published_generations' OR TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Durable publication history is immutable';
            END IF;
            IF (NEW.id, NEW.requester_id, NEW.operation, NEW.key_digest, NEW.request_identity,
                NEW.configuration, NEW.base_generation_id, NEW.admitted_at)
                IS DISTINCT FROM
                (OLD.id, OLD.requester_id, OLD.operation, OLD.key_digest, OLD.request_identity,
                OLD.configuration, OLD.base_generation_id, OLD.admitted_at) THEN
                RAISE EXCEPTION 'Refresh admission is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER refresh_snapshot BEFORE UPDATE OR DELETE ON refresh_runs FOR EACH ROW EXECUTE FUNCTION preserve_refresh_history()"
    )
    op.execute(
        "CREATE TRIGGER publication_history BEFORE UPDATE OR DELETE ON published_generations FOR EACH ROW EXECUTE FUNCTION preserve_refresh_history()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE refresh_coordination")
    op.execute(
        "ALTER TABLE refresh_runs DROP CONSTRAINT refresh_runs_base_generation_id_fkey"
    )
    op.execute(
        "ALTER TABLE refresh_runs DROP CONSTRAINT refresh_runs_generation_id_fkey"
    )
    op.execute("DROP TABLE published_generations")
    op.execute("DROP TABLE refresh_runs")
    op.execute("DROP FUNCTION preserve_refresh_history()")
