"""Record actual refresh start/finish times without inventing historical values."""

from alembic import op

revision = "0003_refresh_timestamps"
down_revision = "0002_data_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE refresh_runs ADD COLUMN started_at timestamptz, ADD COLUMN finished_at timestamptz"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE refresh_runs DROP COLUMN finished_at, DROP COLUMN started_at"
    )
