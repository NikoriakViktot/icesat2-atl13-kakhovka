"""ownership: which API client and which end user created a job / region

``client`` is the name of the API key (``API_KEYS`` = ``name:key[:ro]``);
``requested_by`` is the end user a trusted client (the Django BFF) acts for,
sent as the ``X-Requested-By`` header. Both are NULL for rows created before.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("jobs", "regions"):
        op.execute(f"ALTER TABLE icesat2.{table} ADD COLUMN client text, "
                   f"ADD COLUMN requested_by text")
    op.execute("CREATE INDEX jobs_owner_idx "
               "ON icesat2.jobs (client, requested_by, created_at DESC)")
    op.execute("CREATE INDEX regions_owner_idx ON icesat2.regions (client, requested_by)")


def downgrade() -> None:
    op.execute("DROP INDEX icesat2.regions_owner_idx")
    op.execute("DROP INDEX icesat2.jobs_owner_idx")
    for table in ("jobs", "regions"):
        op.execute(f"ALTER TABLE icesat2.{table} DROP COLUMN requested_by, DROP COLUMN client")
