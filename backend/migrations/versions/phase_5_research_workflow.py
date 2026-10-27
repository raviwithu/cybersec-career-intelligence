"""phase 5 research workflow

Revision ID: phase5research
Revises: edb4f0851c71
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase5research"
down_revision: Union[str, None] = "edb4f0851c71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("original_filename", sa.String(length=255)),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("extraction_payload", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["source_id"], ["research_sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index("ix_research_submissions_source_id", "research_submissions", ["source_id"], unique=True)
    op.create_index("ix_research_submissions_content_sha256", "research_submissions", ["content_sha256"])
    op.create_index("ix_research_submissions_status", "research_submissions", ["status"])
    op.create_table(
        "research_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("domain_id", sa.Integer()), sa.Column("career_level_id", sa.Integer()),
        sa.Column("category_id", sa.Integer()), sa.Column("competency_id", sa.Integer()),
        sa.Column("candidate_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200)),
        sa.Column("finding_type", sa.String(length=60), nullable=False),
        sa.Column("technical_knowledge", sa.Text(), nullable=False),
        sa.Column("practical_capability", sa.Text(), nullable=False),
        sa.Column("responsibilities", sa.Text(), nullable=False),
        sa.Column("proficiency_level", sa.String(length=40), nullable=False),
        sa.Column("importance", sa.String(length=40), nullable=False),
        sa.Column("experience_years_min", sa.Integer()), sa.Column("experience_years_max", sa.Integer()),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False), sa.Column("details", sa.JSON()),
        sa.ForeignKeyConstraint(["submission_id"], ["research_submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["security_domains.id"]),
        sa.ForeignKeyConstraint(["career_level_id"], ["career_levels.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["competency_categories.id"]),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"]),
    )
    op.create_index("ix_research_findings_submission_id", "research_findings", ["submission_id"])
    op.create_table(
        "draft_expectations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=False), sa.Column("career_level_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False), sa.Column("expectation_description", sa.Text(), nullable=False),
        sa.Column("proficiency_level", sa.String(length=40), nullable=False), sa.Column("importance", sa.String(length=40), nullable=False),
        sa.Column("responsibility_type", sa.String(length=80), nullable=False), sa.Column("experience_years_min", sa.Integer()),
        sa.Column("experience_years_max", sa.Integer()), sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewer_note", sa.Text()), sa.Column("reviewed_by", sa.String(length=120)), sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("published_expectation_id", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["research_submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["security_domains.id"]), sa.ForeignKeyConstraint(["career_level_id"], ["career_levels.id"]),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"]), sa.ForeignKeyConstraint(["published_expectation_id"], ["domain_level_expectations.id"]),
    )
    op.create_index("ix_draft_expectations_submission_id", "draft_expectations", ["submission_id"])
    op.create_index("ix_draft_expectations_domain_id", "draft_expectations", ["domain_id"])
    op.create_index("ix_draft_expectations_career_level_id", "draft_expectations", ["career_level_id"])
    op.create_index("ix_draft_expectations_competency_id", "draft_expectations", ["competency_id"])
    op.create_index("ix_draft_expectations_status", "draft_expectations", ["status"])
    op.create_table(
        "draft_evidence",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False), sa.Column("supporting_excerpt", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["draft_expectations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["research_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_draft_evidence_draft_id", "draft_evidence", ["draft_id"])
    op.create_index("ix_draft_evidence_source_id", "draft_evidence", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_draft_evidence_source_id", table_name="draft_evidence")
    op.drop_index("ix_draft_evidence_draft_id", table_name="draft_evidence")
    op.drop_table("draft_evidence")
    for index_name, table_name in (
        ("ix_draft_expectations_status", "draft_expectations"), ("ix_draft_expectations_competency_id", "draft_expectations"),
        ("ix_draft_expectations_career_level_id", "draft_expectations"), ("ix_draft_expectations_domain_id", "draft_expectations"),
        ("ix_draft_expectations_submission_id", "draft_expectations"),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("draft_expectations")
    op.drop_index("ix_research_findings_submission_id", table_name="research_findings")
    op.drop_table("research_findings")
    for index_name in ("ix_research_submissions_status", "ix_research_submissions_content_sha256", "ix_research_submissions_source_id"):
        op.drop_index(index_name, table_name="research_submissions")
    op.drop_table("research_submissions")
