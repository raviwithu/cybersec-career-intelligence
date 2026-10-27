"""authorized job search configurations and processing records

Revision ID: phase6jobsearch
Revises: phase6research
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase6jobsearch"
down_revision: Union[str, None] = "phase6research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "automated_job_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("automated_source_id", sa.Integer(), sa.ForeignKey("automated_research_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False, server_default="unconfigured"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("experience_level", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("date_posted", sa.String(length=40), nullable=False, server_default="any"),
        sa.Column("employment_type", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("work_mode", sa.String(length=40), nullable=False, server_default="any"),
        sa.Column("max_results", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("search_frequency", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(length=30), nullable=False, server_default="never"),
        sa.Column("last_error", sa.Text()),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="administrator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_automated_job_searches_name"),
    )
    _indexes("automated_job_searches", ["automated_source_id", "name", "enabled", "next_run_at", "last_status"])

    op.create_table(
        "automated_job_search_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_id", sa.Integer(), sa.ForeignKey("automated_job_searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("provider_status", sa.String(length=40), nullable=False, server_default="unconfigured"),
        sa.Column("provider_total", sa.Integer()),
        sa.Column("results_retrieved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("results_queued", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("results_unavailable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("descriptions_retrieved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successfully_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_review_required", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_result_ids", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="scheduler"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("automated_job_search_runs", ["search_id", "trigger", "status", "created_at"])

    op.create_table(
        "automated_job_search_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_id", sa.Integer(), sa.ForeignKey("automated_job_searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("automated_job_search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255)),
        sa.Column("canonical_url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("description_url", sa.String(length=1000)),
        sa.Column("description_text", sa.Text()),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("content_version_id", sa.Integer(), sa.ForeignKey("research_content_versions.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("manual_review_reason", sa.Text()),
        sa.Column("duplicate_of_id", sa.Integer(), sa.ForeignKey("automated_job_search_results.id", ondelete="SET NULL")),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "canonical_url", name="uq_job_search_result_run_url"),
    )
    _indexes("automated_job_search_results", ["search_id", "run_id", "external_id", "canonical_url", "content_version_id", "content_hash", "status"])


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_automated_job_search_results_status", "automated_job_search_results"),
        ("ix_automated_job_search_results_content_hash", "automated_job_search_results"),
        ("ix_automated_job_search_results_content_version_id", "automated_job_search_results"),
        ("ix_automated_job_search_results_canonical_url", "automated_job_search_results"),
        ("ix_automated_job_search_results_external_id", "automated_job_search_results"),
        ("ix_automated_job_search_results_run_id", "automated_job_search_results"),
        ("ix_automated_job_search_results_search_id", "automated_job_search_results"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("automated_job_search_results")
    for index_name, table_name in (
        ("ix_automated_job_search_runs_created_at", "automated_job_search_runs"),
        ("ix_automated_job_search_runs_status", "automated_job_search_runs"),
        ("ix_automated_job_search_runs_trigger", "automated_job_search_runs"),
        ("ix_automated_job_search_runs_search_id", "automated_job_search_runs"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("automated_job_search_runs")
    for index_name, table_name in (
        ("ix_automated_job_searches_last_status", "automated_job_searches"),
        ("ix_automated_job_searches_next_run_at", "automated_job_searches"),
        ("ix_automated_job_searches_enabled", "automated_job_searches"),
        ("ix_automated_job_searches_name", "automated_job_searches"),
        ("ix_automated_job_searches_automated_source_id", "automated_job_searches"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("automated_job_searches")
