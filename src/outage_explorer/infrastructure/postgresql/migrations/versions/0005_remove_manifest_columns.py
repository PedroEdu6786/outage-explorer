"""Remove obsolete manifest publication columns (ADR-0064).

Existing rows and references are preserved. The NOT VALID constraint leaves
historical summaries untouched while enforcing exact descriptors on new rows.
Readers reject historical summaries without exact resource descriptors.
"""

from alembic import op

revision = "0005_remove_manifest_columns"
down_revision = "0004_refresh_resource_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE published_generations DROP CONSTRAINT published_generation_layout"
    )
    op.execute(
        "ALTER TABLE published_generations DROP COLUMN manifest_key, DROP COLUMN manifest_digest"
    )
    op.execute("""
        ALTER TABLE published_generations ADD CONSTRAINT published_generation_layout
        CHECK (resource_generation_valid(id, datasets)) NOT VALID
    """)


def downgrade() -> None:
    raise RuntimeError("Cannot downgrade: removed manifest values cannot be restored")
