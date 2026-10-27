"""research review and controlled publication workflow

Revision ID: phase5review
Revises: phase5providers
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase5review"
down_revision: Union[str, None] = "phase5providers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table_name in ("domain_level_expectations", "draft_expectations"):
        if table_name in tables:
            existing_columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
            for column_name in ("technical_knowledge", "practical_capability", "qualifications", "tools_technologies"):
                if column_name not in existing_columns:
                    op.add_column(table_name, sa.Column(column_name, sa.Text(), nullable=False, server_default=""))

    if "research_finding_domains" not in tables:
        op.create_table(
            "research_finding_domains",
            sa.Column("finding_id", sa.Integer(), nullable=False),
            sa.Column("domain_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["finding_id"], ["research_findings.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["domain_id"], ["security_domains.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("finding_id", "domain_id"),
        )

    if "publication_batches" not in tables:
        op.create_table(
            "publication_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("submission_id", sa.Integer()),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_by", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("error_message", sa.Text()),
            sa.ForeignKeyConstraint(["submission_id"], ["research_submissions.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_publication_batches_submission_id", "publication_batches", ["submission_id"])
        op.create_index("ix_publication_batches_status", "publication_batches", ["status"])

    if "review_changes" not in tables:
        op.create_table(
            "review_changes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("submission_id", sa.Integer(), nullable=False),
            sa.Column("finding_id", sa.Integer(), nullable=False),
            sa.Column("draft_id", sa.Integer()),
            sa.Column("target_competency_id", sa.Integer()),
            sa.Column("target_expectation_id", sa.Integer()),
            sa.Column("merge_target_competency_id", sa.Integer()),
            sa.Column("publication_batch_id", sa.Integer()),
            sa.Column("change_type", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("original_snapshot", sa.JSON(), nullable=False),
            sa.Column("proposed_snapshot", sa.JSON(), nullable=False),
            sa.Column("reviewer_snapshot", sa.JSON()),
            sa.Column("reviewer_note", sa.Text()),
            sa.Column("reviewed_by", sa.String(length=120)),
            sa.Column("reviewed_at", sa.DateTime(timezone=True)),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["submission_id"], ["research_submissions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["finding_id"], ["research_findings.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["draft_id"], ["draft_expectations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["target_competency_id"], ["competencies.id"]),
            sa.ForeignKeyConstraint(["target_expectation_id"], ["domain_level_expectations.id"]),
            sa.ForeignKeyConstraint(["merge_target_competency_id"], ["competencies.id"]),
            sa.ForeignKeyConstraint(["publication_batch_id"], ["publication_batches.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("finding_id", name="uq_review_change_finding"),
        )
        for name, column in (
            ("ix_review_changes_submission_id", "submission_id"),
            ("ix_review_changes_finding_id", "finding_id"),
            ("ix_review_changes_draft_id", "draft_id"),
            ("ix_review_changes_target_competency_id", "target_competency_id"),
            ("ix_review_changes_target_expectation_id", "target_expectation_id"),
            ("ix_review_changes_merge_target_competency_id", "merge_target_competency_id"),
            ("ix_review_changes_publication_batch_id", "publication_batch_id"),
            ("ix_review_changes_status", "status"),
        ):
            op.create_index(name, "review_changes", [column])

    if "review_audits" not in tables:
        op.create_table(
            "review_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=30), nullable=False),
            sa.Column("actor", sa.String(length=120), nullable=False),
            sa.Column("before_snapshot", sa.JSON()),
            sa.Column("after_snapshot", sa.JSON()),
            sa.Column("note", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["change_id"], ["review_changes.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_review_audits_change_id", "review_audits", ["change_id"])

    if "expectation_revisions" not in tables:
        op.create_table(
            "expectation_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("expectation_id", sa.Integer(), nullable=False),
            sa.Column("change_id", sa.Integer()),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["expectation_id"], ["domain_level_expectations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["change_id"], ["review_changes.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_expectation_revisions_expectation_id", "expectation_revisions", ["expectation_id"])
        op.create_index("ix_expectation_revisions_change_id", "expectation_revisions", ["change_id"])


    if "research_findings" in tables:
        with op.batch_alter_table("research_findings") as batch:
            batch.alter_column("confidence", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    op.drop_index("ix_expectation_revisions_change_id", table_name="expectation_revisions")
    op.drop_index("ix_expectation_revisions_expectation_id", table_name="expectation_revisions")
    op.drop_table("expectation_revisions")
    op.drop_index("ix_review_audits_change_id", table_name="review_audits")
    op.drop_table("review_audits")
    for name in (
        "ix_review_changes_status",
        "ix_review_changes_publication_batch_id",
        "ix_review_changes_merge_target_competency_id",
        "ix_review_changes_target_expectation_id",
        "ix_review_changes_target_competency_id",
        "ix_review_changes_draft_id",
        "ix_review_changes_finding_id",
        "ix_review_changes_submission_id",
    ):
        op.drop_index(name, table_name="review_changes")
    op.drop_table("review_changes")
    op.drop_index("ix_publication_batches_status", table_name="publication_batches")
    op.drop_index("ix_publication_batches_submission_id", table_name="publication_batches")
    op.drop_table("publication_batches")
    op.drop_table("research_finding_domains")
    for table_name in ("draft_expectations", "domain_level_expectations"):
        with op.batch_alter_table(table_name) as batch:
            for column_name in ("tools_technologies", "qualifications", "practical_capability", "technical_knowledge"):
                batch.drop_column(column_name)
    with op.batch_alter_table("research_findings") as batch:
        batch.alter_column("confidence", existing_type=sa.Float(), nullable=False)
