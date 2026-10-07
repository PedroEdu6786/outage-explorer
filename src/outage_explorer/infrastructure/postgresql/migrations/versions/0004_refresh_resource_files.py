"""Store exact three-resource descriptors without a manifest (ADR-0062).

Existing manifest-format rows, foreign keys, coordination and immutability
triggers are untouched. A resource-format row is identified by NULL manifest
columns plus a database-validated exact descriptor array; old rows are never
converted or backfilled and are rejected by resource readers instead.
"""

from alembic import op

revision = "0004_refresh_resource_files"
down_revision = "0003_refresh_timestamps"
branch_labels = None
depends_on = None

_VALID = r"""
CREATE FUNCTION resource_generation_valid(generation uuid, descriptors jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(descriptors) <> 'array' THEN false ELSE COALESCE(
        jsonb_array_length(descriptors) = 3
        AND (
            SELECT count(DISTINCT item ->> 'grain') = 3
                AND count(DISTINCT item ->> 'object_key') = 3
            FROM jsonb_array_elements(descriptors) AS item
        )
        AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(descriptors) AS item
            WHERE COALESCE(NOT (
                jsonb_typeof(item) = 'object'
                AND item ->> 'grain' IN ('national', 'facility', 'generator')
                AND item ->> 'schema_version' = 'v1'
                AND jsonb_typeof(item -> 'rows') = 'number'
                AND item ->> 'rows' ~ '^[1-9][0-9]*$'
                AND jsonb_typeof(item -> 'byte_count') = 'number'
                AND item ->> 'byte_count' ~ '^[1-9][0-9]*$'
                AND jsonb_typeof(item -> 'sha256') = 'string'
                AND item ->> 'sha256' ~ '^[0-9a-f]{64}$'
                AND item ->> 'start' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                AND item ->> 'end' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                AND item ->> 'start' <= item ->> 'end'
                AND jsonb_typeof(item -> 'object_key') = 'string'
                AND length(item ->> 'object_key') BETWEEN 1 AND 1024
                AND item ->> 'object_key' ~ '^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$'
                AND item ->> 'object_key' !~ '(^|/)\.{1,2}(/|$)'
                AND item ->> 'object_key' LIKE '%/generations/' || generation::text || '/'
                    || (CASE item ->> 'grain'
                        WHEN 'national' THEN 'national.parquet'
                        WHEN 'facility' THEN 'facilities.parquet'
                        ELSE 'generators.parquet' END)
            ), true)
        ),
        false) END
$$
"""


def upgrade() -> None:
    op.execute(_VALID)
    op.execute(
        "ALTER TABLE published_generations ALTER COLUMN manifest_key DROP NOT NULL, ALTER COLUMN manifest_digest DROP NOT NULL"
    )
    op.execute("""
        ALTER TABLE published_generations ADD CONSTRAINT published_generation_layout CHECK (
            (manifest_key IS NOT NULL AND manifest_digest IS NOT NULL)
            OR (manifest_key IS NULL AND manifest_digest IS NULL
                AND resource_generation_valid(id, datasets))
        )
    """)


def downgrade() -> None:
    # Dropping the descriptor layout would orphan immutable history; never rewrite it.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM published_generations WHERE manifest_key IS NULL) THEN
                RAISE EXCEPTION 'Cannot downgrade: resource-format publication history exists';
            END IF;
        END
        $$
    """)
    op.execute(
        "ALTER TABLE published_generations DROP CONSTRAINT published_generation_layout"
    )
    op.execute(
        "ALTER TABLE published_generations ALTER COLUMN manifest_key SET NOT NULL, ALTER COLUMN manifest_digest SET NOT NULL"
    )
    op.execute("DROP FUNCTION resource_generation_valid(uuid, jsonb)")
