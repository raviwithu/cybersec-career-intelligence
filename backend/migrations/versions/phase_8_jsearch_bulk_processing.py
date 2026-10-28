"""JSearch bulk retrieval metadata and processing metrics

Revision ID: phase8jsearch
Revises: phase7profiles
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase8jsearch"
down_revision: Union[str, None] = "phase7profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("automated_job_searches", sa.Column("country", sa.String(length=2), nullable=False, server_default="us"))
    op.add_column("automated_job_searches", sa.Column("max_pages", sa.Integer(), nullable=False, server_default="3"))

    op.add_column("automated_job_search_runs", sa.Column("pages_requested", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("automated_job_search_runs", sa.Column("api_requests_used", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("automated_job_search_runs", sa.Column("complete_descriptions", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("automated_job_search_runs", sa.Column("partial_descriptions", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("automated_job_search_runs", sa.Column("rate_limit_errors", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("automated_job_search_runs", sa.Column("quota_errors", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("automated_job_search_results", sa.Column("country", sa.String(length=2), nullable=False, server_default=""))
    op.add_column("automated_job_search_results", sa.Column("employment_type", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("automated_job_search_results", sa.Column("posted_at", sa.DateTime(timezone=True)))
    op.add_column("automated_job_search_results", sa.Column("description_complete", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("automated_job_search_results", "description_complete")
    op.drop_column("automated_job_search_results", "posted_at")
    op.drop_column("automated_job_search_results", "employment_type")
    op.drop_column("automated_job_search_results", "country")

    op.drop_column("automated_job_search_runs", "quota_errors")
    op.drop_column("automated_job_search_runs", "rate_limit_errors")
    op.drop_column("automated_job_search_runs", "partial_descriptions")
    op.drop_column("automated_job_search_runs", "complete_descriptions")
    op.drop_column("automated_job_search_runs", "api_requests_used")
    op.drop_column("automated_job_search_runs", "pages_requested")

    op.drop_column("automated_job_searches", "max_pages")
    op.drop_column("automated_job_searches", "country")
