"""Yahoo Mail LinkedIn job-alert ingestion workflow

Revision ID: ph12yahoomail
Revises: ph11knowledge
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph12yahoomail"
down_revision: Union[str, None] = "ph11knowledge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index(name: str, table: str, column: str) -> None:
    op.create_index(name, table, [column])


def upgrade() -> None:
    op.create_table(
        "yahoo_mail_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("auth_method", sa.String(length=30), nullable=False, server_default="app_password"),
        sa.Column("encrypted_app_password", sa.Text(), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False, server_default="Inbox"),
        sa.Column("initial_sync_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("automatic_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uidvalidity", sa.String(length=120), nullable=True),
        sa.Column("last_uid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="disconnected"),
        sa.Column("last_successful_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("messages_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("alerts_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_extracted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email_address", name="uq_yahoo_mail_connection_email"),
    )
    _index("ix_yahoo_mail_connections_email_address", "yahoo_mail_connections", "email_address")
    _index("ix_yahoo_mail_connections_automatic_sync_enabled", "yahoo_mail_connections", "automatic_sync_enabled")
    _index("ix_yahoo_mail_connections_next_sync_at", "yahoo_mail_connections", "next_sync_at")
    _index("ix_yahoo_mail_connections_enabled", "yahoo_mail_connections", "enabled")
    _index("ix_yahoo_mail_connections_status", "yahoo_mail_connections", "status")

    op.create_table(
        "yahoo_alert_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False, server_default="LinkedIn Job Alerts"),
        sa.Column("sender_address", sa.String(length=320), nullable=False, server_default="jobalerts-noreply@linkedin.com"),
        sa.Column("subject_pattern", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extraction_adapter", sa.String(length=60), nullable=False, server_default="linkedin_job_alert"),
        sa.Column("detection_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["yahoo_mail_connections.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("connection_id", "sender_address", name="uq_yahoo_alert_source_sender"),
    )
    _index("ix_yahoo_alert_sources_connection_id", "yahoo_alert_sources", "connection_id")
    _index("ix_yahoo_alert_sources_sender_address", "yahoo_alert_sources", "sender_address")
    _index("ix_yahoo_alert_sources_enabled", "yahoo_alert_sources", "enabled")

    op.create_table(
        "yahoo_mail_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="incremental"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("mailbox", sa.String(length=255), nullable=False, server_default="Inbox"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uidvalidity_before", sa.String(length=120), nullable=True),
        sa.Column("uidvalidity_after", sa.String(length=120), nullable=True),
        sa.Column("last_uid_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_uid_after", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("alerts_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_extracted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="scheduler"),
        sa.ForeignKeyConstraint(["connection_id"], ["yahoo_mail_connections.id"], ondelete="CASCADE"),
    )
    _index("ix_yahoo_mail_sync_runs_connection_id", "yahoo_mail_sync_runs", "connection_id")
    _index("ix_yahoo_mail_sync_runs_mode", "yahoo_mail_sync_runs", "mode")
    _index("ix_yahoo_mail_sync_runs_status", "yahoo_mail_sync_runs", "status")

    op.create_table(
        "yahoo_alert_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("sync_run_id", sa.Integer(), nullable=True),
        sa.Column("alert_source_id", sa.Integer(), nullable=True),
        sa.Column("mailbox", sa.String(length=255), nullable=False, server_default="Inbox"),
        sa.Column("uidvalidity", sa.String(length=120), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=500), nullable=True),
        sa.Column("sender_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authentication_headers", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("processing_status", sa.String(length=30), nullable=False, server_default="processed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["yahoo_mail_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["yahoo_mail_sync_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["alert_source_id"], ["yahoo_alert_sources.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("connection_id", "mailbox", "uidvalidity", "uid", name="uq_yahoo_alert_email_uid"),
    )
    for name, column in (("connection_id", "connection_id"), ("sync_run_id", "sync_run_id"), ("alert_source_id", "alert_source_id"), ("sender_address", "sender_address"), ("received_at", "received_at"), ("content_hash", "content_hash"), ("processing_status", "processing_status")):
        _index(f"ix_yahoo_alert_emails_{name}", "yahoo_alert_emails", column)

    op.create_table(
        "yahoo_job_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_email_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("employer", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("location", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("work_mode", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("job_url", sa.String(length=1000), nullable=False),
        sa.Column("source_provider", sa.String(length=80), nullable=False, server_default="LinkedIn Job Alerts"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("description_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description_status", sa.String(length=30), nullable=False, server_default="partial"),
        sa.Column("extraction_method", sa.String(length=60), nullable=False, server_default="linkedin_job_alert"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("duplicate_status", sa.String(length=30), nullable=False, server_default="unique"),
        sa.Column("duplicate_reason", sa.String(length=500), nullable=True),
        sa.Column("ingestion_status", sa.String(length=30), nullable=False, server_default="not_approved"),
        sa.Column("research_content_version_id", sa.Integer(), nullable=True),
        sa.Column("research_submission_id", sa.Integer(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alert_email_id"], ["yahoo_alert_emails.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["research_content_version_id"], ["research_content_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["research_submission_id"], ["research_submissions.id"], ondelete="SET NULL"),
    )
    for name, column in (("alert_email_id", "alert_email_id"), ("job_url", "job_url"), ("received_at", "received_at"), ("description_status", "description_status"), ("review_status", "review_status"), ("duplicate_status", "duplicate_status"), ("ingestion_status", "ingestion_status"), ("research_content_version_id", "research_content_version_id"), ("research_submission_id", "research_submission_id")):
        _index(f"ix_yahoo_job_candidates_{name}", "yahoo_job_candidates", column)

    op.create_table(
        "yahoo_job_provenance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("provenance_type", sa.String(length=40), nullable=False),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_label", sa.String(length=200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["yahoo_job_candidates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("candidate_id", "provenance_type", "source_url", name="uq_yahoo_job_provenance_source"),
    )
    _index("ix_yahoo_job_provenance_candidate_id", "yahoo_job_provenance", "candidate_id")

    op.create_table(
        "yahoo_job_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["yahoo_job_candidates.id"], ondelete="CASCADE"),
    )
    _index("ix_yahoo_job_reviews_candidate_id", "yahoo_job_reviews", "candidate_id")


def downgrade() -> None:
    op.drop_table("yahoo_job_reviews")
    op.drop_table("yahoo_job_provenance")
    op.drop_table("yahoo_job_candidates")
    op.drop_table("yahoo_alert_emails")
    op.drop_table("yahoo_mail_sync_runs")
    op.drop_table("yahoo_alert_sources")
    op.drop_table("yahoo_mail_connections")
