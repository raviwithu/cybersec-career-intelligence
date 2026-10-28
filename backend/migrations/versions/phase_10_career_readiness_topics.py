"""research-driven career readiness knowledge topics

Revision ID: ph10topics
Revises: ph9taxonomy
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph10topics"
down_revision: Union[str, None] = "ph9taxonomy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index(name: str, table: str, column: str) -> None:
    op.create_index(name, table, [column])


def upgrade() -> None:
    op.create_table(
        "knowledge_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("slug", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("parent_topic_id", sa.Integer(), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("publication_status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["competency_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_topic_id"], ["knowledge_topics.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("slug", name="uq_knowledge_topic_slug"),
    )
    _index("ix_knowledge_topics_name", "knowledge_topics", "name")
    _index("ix_knowledge_topics_slug", "knowledge_topics", "slug")
    _index("ix_knowledge_topics_category_id", "knowledge_topics", "category_id")
    _index("ix_knowledge_topics_parent_topic_id", "knowledge_topics", "parent_topic_id")
    _index("ix_knowledge_topics_publication_status", "knowledge_topics", "publication_status")
    _index("ix_knowledge_topics_is_active", "knowledge_topics", "is_active")

    op.create_table(
        "knowledge_topic_domains",
        sa.Column("topic_id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), primary_key=True),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["security_domains.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("topic_id", "domain_id", name="uq_knowledge_topic_domain"),
    )
    _index("ix_knowledge_topic_domains_domain_id", "knowledge_topic_domains", "domain_id")

    op.create_table(
        "knowledge_topic_industries",
        sa.Column("topic_id", sa.Integer(), primary_key=True),
        sa.Column("industry_id", sa.Integer(), primary_key=True),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["industry_id"], ["industries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("topic_id", "industry_id", name="uq_knowledge_topic_industry"),
    )
    _index("ix_knowledge_topic_industries_industry_id", "knowledge_topic_industries", "industry_id")

    op.create_table(
        "knowledge_topic_levels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("career_level_id", sa.Integer(), nullable=False),
        sa.Column("industry_id", sa.Integer(), nullable=True),
        sa.Column("expectation", sa.Text(), nullable=False, server_default=""),
        sa.Column("practical_capability", sa.Text(), nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["career_level_id"], ["career_levels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["industry_id"], ["industries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("topic_id", "career_level_id", "industry_id", name="uq_knowledge_topic_level_industry"),
    )
    _index("ix_knowledge_topic_levels_topic_id", "knowledge_topic_levels", "topic_id")
    _index("ix_knowledge_topic_levels_career_level_id", "knowledge_topic_levels", "career_level_id")
    _index("ix_knowledge_topic_levels_industry_id", "knowledge_topic_levels", "industry_id")

    op.create_table(
        "knowledge_topic_competencies",
        sa.Column("topic_id", sa.Integer(), primary_key=True),
        sa.Column("competency_id", sa.Integer(), primary_key=True),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("topic_id", "competency_id", name="uq_knowledge_topic_competency"),
    )
    _index("ix_knowledge_topic_competencies_competency_id", "knowledge_topic_competencies", "competency_id")

    op.create_table(
        "knowledge_topic_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.Integer(), nullable=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("proposal_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="review"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("original_snapshot", sa.JSON(), nullable=True),
        sa.Column("proposed_snapshot", sa.JSON(), nullable=False),
        sa.Column("ai_interpretation", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_status", sa.String(length=30), nullable=False, server_default="ai-derived"),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["research_findings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("fingerprint", name="uq_knowledge_topic_proposal_fingerprint"),
    )
    for name, column in (("finding_id", "finding_id"), ("topic_id", "topic_id"), ("proposal_type", "proposal_type"), ("status", "status"), ("fingerprint", "fingerprint")):
        _index(f"ix_knowledge_topic_proposals_{name}", "knowledge_topic_proposals", column)

    op.create_table(
        "knowledge_topic_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.String(length=30), nullable=False, server_default="supporting"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["research_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_topic_proposals.id"], ondelete="SET NULL"),
    )
    for name, column in (("topic_id", "topic_id"), ("source_id", "source_id"), ("proposal_id", "proposal_id")):
        _index(f"ix_knowledge_topic_evidence_{name}", "knowledge_topic_evidence", column)

    op.create_table(
        "knowledge_topic_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False, server_default="administrator"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["research_sources.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("topic_id", "version", name="uq_knowledge_topic_version"),
    )
    _index("ix_knowledge_topic_versions_topic_id", "knowledge_topic_versions", "topic_id")
    _index("ix_knowledge_topic_versions_source_id", "knowledge_topic_versions", "source_id")

    op.create_table(
        "knowledge_topic_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False, server_default="administrator"),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_topic_proposals.id"], ondelete="SET NULL"),
    )
    for name, column in (("topic_id", "topic_id"), ("proposal_id", "proposal_id"), ("action", "action"), ("created_at", "created_at")):
        _index(f"ix_knowledge_topic_audits_{name}", "knowledge_topic_audits", column)


def downgrade() -> None:
    for index, table in (
        ("ix_knowledge_topic_audits_created_at", "knowledge_topic_audits"),
        ("ix_knowledge_topic_audits_action", "knowledge_topic_audits"),
        ("ix_knowledge_topic_audits_proposal_id", "knowledge_topic_audits"),
        ("ix_knowledge_topic_audits_topic_id", "knowledge_topic_audits"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("knowledge_topic_audits")

    for index, table in (("ix_knowledge_topic_versions_source_id", "knowledge_topic_versions"), ("ix_knowledge_topic_versions_topic_id", "knowledge_topic_versions")):
        op.drop_index(index, table_name=table)
    op.drop_table("knowledge_topic_versions")

    for index, table in (("ix_knowledge_topic_evidence_proposal_id", "knowledge_topic_evidence"), ("ix_knowledge_topic_evidence_source_id", "knowledge_topic_evidence"), ("ix_knowledge_topic_evidence_topic_id", "knowledge_topic_evidence")):
        op.drop_index(index, table_name=table)
    op.drop_table("knowledge_topic_evidence")

    for index, table in (("ix_knowledge_topic_proposals_fingerprint", "knowledge_topic_proposals"), ("ix_knowledge_topic_proposals_status", "knowledge_topic_proposals"), ("ix_knowledge_topic_proposals_proposal_type", "knowledge_topic_proposals"), ("ix_knowledge_topic_proposals_topic_id", "knowledge_topic_proposals"), ("ix_knowledge_topic_proposals_finding_id", "knowledge_topic_proposals")):
        op.drop_index(index, table_name=table)
    op.drop_table("knowledge_topic_proposals")

    op.drop_index("ix_knowledge_topic_competencies_competency_id", table_name="knowledge_topic_competencies")
    op.drop_table("knowledge_topic_competencies")

    for index, table in (("ix_knowledge_topic_levels_industry_id", "knowledge_topic_levels"), ("ix_knowledge_topic_levels_career_level_id", "knowledge_topic_levels"), ("ix_knowledge_topic_levels_topic_id", "knowledge_topic_levels")):
        op.drop_index(index, table_name=table)
    op.drop_table("knowledge_topic_levels")

    op.drop_index("ix_knowledge_topic_industries_industry_id", table_name="knowledge_topic_industries")
    op.drop_table("knowledge_topic_industries")

    op.drop_index("ix_knowledge_topic_domains_domain_id", table_name="knowledge_topic_domains")
    op.drop_table("knowledge_topic_domains")

    for index, table in (("ix_knowledge_topics_is_active", "knowledge_topics"), ("ix_knowledge_topics_publication_status", "knowledge_topics"), ("ix_knowledge_topics_parent_topic_id", "knowledge_topics"), ("ix_knowledge_topics_category_id", "knowledge_topics"), ("ix_knowledge_topics_slug", "knowledge_topics"), ("ix_knowledge_topics_name", "knowledge_topics")):
        op.drop_index(index, table_name=table)
    op.drop_table("knowledge_topics")
