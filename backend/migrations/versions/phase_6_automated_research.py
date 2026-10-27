"""automated research collection, analysis, and change detection

Revision ID: phase6research
aRevises: phase5submissiondelete
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase6research"
down_revision: Union[str, None] = "phase5submissiondelete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automated_research_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("collection_frequency", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("applicable_industries", sa.JSON(), nullable=False),
        sa.Column("applicable_domains", sa.JSON(), nullable=False),
        sa.Column("applicable_career_levels", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("collection_status", sa.String(length=30), nullable=False, server_default="never"),
        sa.Column("last_successful_collection", sa.DateTime(timezone=True)),
        sa.Column("last_attempted_collection", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="administrator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_automated_research_sources_name"),
    )
    op.create_index("ix_automated_research_sources_name", "automated_research_sources", ["name"])
    op.create_index("ix_automated_research_sources_source_type", "automated_research_sources", ["source_type"])
    op.create_index("ix_automated_research_sources_enabled", "automated_research_sources", ["enabled"])
    op.create_index("ix_automated_research_sources_collection_status", "automated_research_sources", ["collection_status"])
    op.create_index("ix_automated_research_sources_next_run_at", "automated_research_sources", ["next_run_at"])

    op.create_table(
        "research_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("automated_research_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", name="uq_research_schedule_source"),
    )
    op.create_index("ix_research_schedules_source_id", "research_schedules", ["source_id"])
    op.create_index("ix_research_schedules_enabled", "research_schedules", ["enabled"])
    op.create_index("ix_research_schedules_paused", "research_schedules", ["paused"])
    op.create_index("ix_research_schedules_next_run_at", "research_schedules", ["next_run_at"])

    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("requested_source_ids", sa.JSON(), nullable=False),
        sa.Column("target_filters", sa.JSON(), nullable=False),
        sa.Column("sources_collected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_collections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="scheduler"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_runs_trigger", "research_runs", ["trigger"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_index("ix_research_runs_created_at", "research_runs", ["created_at"])

    op.create_table(
        "research_collection_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("automated_research_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("http_status", sa.Integer()),
        sa.Column("items_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_collected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_research_collection_attempts_run_id", "research_collection_attempts", ["run_id"])
    op.create_index("ix_research_collection_attempts_source_id", "research_collection_attempts", ["source_id"])
    op.create_index("ix_research_collection_attempts_status", "research_collection_attempts", ["status"])

    op.create_table(
        "research_content_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registry_source_id", sa.Integer(), sa.ForeignKey("automated_research_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("research_source_id", sa.Integer(), sa.ForeignKey("research_sources.id", ondelete="SET NULL")),
        sa.Column("canonical_url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content_size", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="collected"),
        sa.Column("duplicate_of_id", sa.Integer(), sa.ForeignKey("research_content_versions.id", ondelete="SET NULL")),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_content_versions_registry_source_id", "research_content_versions", ["registry_source_id"])
    op.create_index("ix_research_content_versions_research_source_id", "research_content_versions", ["research_source_id"])
    op.create_index("ix_research_content_versions_canonical_url", "research_content_versions", ["canonical_url"])
    op.create_index("ix_research_content_versions_content_hash", "research_content_versions", ["content_hash"])
    op.create_index("ix_research_content_versions_status", "research_content_versions", ["status"])

    op.create_table(
        "research_automation_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_version_id", sa.Integer(), sa.ForeignKey("research_content_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("research_submissions.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(length=30)),
        sa.Column("model_id", sa.String(length=255)),
        sa.Column("prompt_version", sa.String(length=80), nullable=False, server_default="phase6-v1"),
        sa.Column("analysis_version", sa.String(length=80), nullable=False, server_default="phase6-v1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("content_version_id", name="uq_research_automation_analysis_version"),
    )
    op.create_index("ix_research_automation_analyses_content_version_id", "research_automation_analyses", ["content_version_id"])
    op.create_index("ix_research_automation_analyses_submission_id", "research_automation_analyses", ["submission_id"])
    op.create_index("ix_research_automation_analyses_status", "research_automation_analyses", ["status"])

    op.create_table(
        "research_change_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registry_source_id", sa.Integer(), sa.ForeignKey("automated_research_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("research_runs.id", ondelete="SET NULL")),
        sa.Column("previous_version_id", sa.Integer(), sa.ForeignKey("research_content_versions.id", ondelete="SET NULL")),
        sa.Column("current_version_id", sa.Integer(), sa.ForeignKey("research_content_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="detected"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_change_events_registry_source_id", "research_change_events", ["registry_source_id"])
    op.create_index("ix_research_change_events_run_id", "research_change_events", ["run_id"])
    op.create_index("ix_research_change_events_change_type", "research_change_events", ["change_type"])
    op.create_index("ix_research_change_events_status", "research_change_events", ["status"])

    op.create_table(
        "research_automation_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("automated_research_sources.id", ondelete="SET NULL")),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("research_runs.id", ondelete="SET NULL")),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_automation_audits")
    for index_name, table_name in (
        ("ix_research_change_events_status", "research_change_events"),
        ("ix_research_change_events_change_type", "research_change_events"),
        ("ix_research_change_events_run_id", "research_change_events"),
        ("ix_research_change_events_registry_source_id", "research_change_events"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("research_change_events")
    for index_name, table_name in (
        ("ix_research_automation_analyses_status", "research_automation_analyses"),
        ("ix_research_automation_analyses_submission_id", "research_automation_analyses"),
        ("ix_research_automation_analyses_content_version_id", "research_automation_analyses"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("research_automation_analyses")
    for index_name, table_name in (
        ("ix_research_content_versions_status", "research_content_versions"),
        ("ix_research_content_versions_content_hash", "research_content_versions"),
        ("ix_research_content_versions_canonical_url", "research_content_versions"),
        ("ix_research_content_versions_research_source_id", "research_content_versions"),
        ("ix_research_content_versions_registry_source_id", "research_content_versions"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("research_content_versions")
    for index_name, table_name in (
        ("ix_research_collection_attempts_status", "research_collection_attempts"),
        ("ix_research_collection_attempts_source_id", "research_collection_attempts"),
        ("ix_research_collection_attempts_run_id", "research_collection_attempts"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("research_collection_attempts")
    for index_name, table_name in (
        ("ix_research_runs_created_at", "research_runs"),
        ("ix_research_runs_status", "research_runs"),
        ("ix_research_runs_trigger", "research_runs"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("research_runs")
    for index_name, table_name in (
        ("ix_research_schedules_next_run_at", "research_schedules"),
        ("ix_research_schedules_paused", "research_schedules"),
        ("ix_research_schedules_enabled", "research_schedules"),
        ("ix_research_schedules_source_id", "research_schedules"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("research_schedules")
    for index_name in (
        "ix_automated_research_sources_next_run_at",
        "ix_automated_research_sources_collection_status",
        "ix_automated_research_sources_enabled",
        "ix_automated_research_sources_source_type",
        "ix_automated_research_sources_name",
    ):
        op.drop_index(index_name, table_name="automated_research_sources")
    op.drop_table("automated_research_sources")
