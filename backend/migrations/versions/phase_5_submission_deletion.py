"""audit research submission deletion without retaining source content

Revision ID: phase5submissiondelete
Revises: phase5industry
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase5submissiondelete"
down_revision: Union[str, None] = "phase5industry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "research_submission_audits" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "research_submission_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_submission_audits_submission_id", "research_submission_audits", ["submission_id"])


def downgrade() -> None:
    op.drop_index("ix_research_submission_audits_submission_id", table_name="research_submission_audits")
    op.drop_table("research_submission_audits")
