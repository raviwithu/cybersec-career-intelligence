"""section-level knowledge proposals, provenance, review, and publication records

Revision ID: ph11knowledge
Revises: ph10topics
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph11knowledge"
down_revision: Union[str, None] = "ph10topics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index(name: str, table: str, column: str, unique: bool = False) -> None:
    op.create_index(name, table, [column], unique=unique)


def upgrade() -> None:
    op.add_column("knowledge_topics", sa.Column("topic_key", sa.String(length=240), nullable=True))
    op.execute("UPDATE knowledge_topics SET topic_key = slug WHERE topic_key IS NULL")
    _index("ix_knowledge_topics_topic_key", "knowledge_topics", "topic_key", unique=True)

    for name, column, definition in (
        ("schema_version", "schema_version", sa.String(length=20)),
        ("action", "action", sa.String(length=40)),
        ("section_type", "section_type", sa.String(length=50)),
        ("source_type", "source_type", sa.String(length=40)),
        ("idempotency_key", "idempotency_key", sa.String(length=160)),
        ("base_section_version", "base_section_version", sa.Integer()),
        ("original_content", "original_content", sa.JSON()),
        ("proposed_content", "proposed_content", sa.JSON()),
        ("change_reason", "change_reason", sa.String(length=500)),
    ):
        default = {
            "schema_version": "1.0", "action": "UPDATE_TOPIC", "source_type": "ai",
            "base_section_version": "0", "change_reason": "",
        }.get(name)
        op.add_column("knowledge_topic_proposals", sa.Column(name, definition, nullable=name in {"section_type", "idempotency_key", "original_content", "proposed_content"}, server_default=default))
    op.execute("UPDATE knowledge_topic_proposals SET proposed_content = proposed_snapshot WHERE proposed_content IS NULL")
    op.execute("UPDATE knowledge_topic_proposals SET original_content = original_snapshot WHERE original_content IS NULL")
    for name, column in (("action", "action"), ("section_type", "section_type"), ("source_type", "source_type"), ("base_section_version", "base_section_version")): 
        _index(f"ix_knowledge_topic_proposals_{name}_contract", "knowledge_topic_proposals", column)
    _index("ix_knowledge_topic_proposals_idempotency_key", "knowledge_topic_proposals", "idempotency_key", unique=True)

    op.create_table(
        "knowledge_topic_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("section_type", sa.String(length=50), nullable=False),
        sa.Column("published_content", sa.JSON(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("topic_id", "section_type", name="uq_knowledge_topic_section_type"),
    )
    _index("ix_knowledge_topic_sections_topic_id", "knowledge_topic_sections", "topic_id")
    _index("ix_knowledge_topic_sections_section_type", "knowledge_topic_sections", "section_type")
    _index("ix_knowledge_topic_sections_status", "knowledge_topic_sections", "status")

    op.create_table(
        "knowledge_topic_section_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("actor", sa.String(length=120), nullable=False, server_default="administrator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["section_id"], ["knowledge_topic_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_topic_proposals.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("section_id", "version", name="uq_knowledge_topic_section_version"),
    )
    for name, column in (("section_id", "section_id"), ("proposal_id", "proposal_id"), ("status", "status")):
        _index(f"ix_knowledge_topic_section_versions_{name}", "knowledge_topic_section_versions", column)

    op.create_table(
        "knowledge_topic_relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_topic_id", sa.Integer(), nullable=False),
        sa.Column("target_topic_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_topic_id", "target_topic_id", "relationship_type", name="uq_knowledge_topic_relationship"),
    )
    _index("ix_knowledge_topic_relationships_source_topic_id", "knowledge_topic_relationships", "source_topic_id")
    _index("ix_knowledge_topic_relationships_target_topic_id", "knowledge_topic_relationships", "target_topic_id")

    op.create_table(
        "knowledge_proposal_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("research_source_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("document_identifier", sa.String(length=500), nullable=True),
        sa.Column("source_title", sa.String(length=300), nullable=False),
        sa.Column("author", sa.String(length=300), nullable=True),
        sa.Column("publisher", sa.String(length=300), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("document_version", sa.String(length=120), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locator", sa.String(length=300), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("verification_status", sa.String(length=30), nullable=False, server_default="unverified"),
        sa.Column("access_scope", sa.String(length=30), nullable=False, server_default="public"),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_topic_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["research_source_id"], ["research_sources.id"], ondelete="SET NULL"),
    )
    for name, column in (("proposal_id", "proposal_id"), ("research_source_id", "research_source_id"), ("content_hash", "content_hash"), ("verification_status", "verification_status"), ("is_private", "is_private")):
        _index(f"ix_knowledge_proposal_sources_{name}", "knowledge_proposal_sources", column)

    op.create_table(
        "knowledge_review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("before_content", sa.JSON(), nullable=True),
        sa.Column("after_content", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_topic_proposals.id"], ondelete="CASCADE"),
    )
    for name, column in (("proposal_id", "proposal_id"), ("action", "action"), ("created_at", "created_at")):
        _index(f"ix_knowledge_review_decisions_{name}", "knowledge_review_decisions", column)

    op.create_table(
        "knowledge_publication_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=True),
        sa.Column("published_version", sa.Integer(), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("transaction_id", sa.String(length=80), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_topic_proposals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["knowledge_topic_sections.id"], ondelete="SET NULL"),
    )
    for name, column in (("proposal_id", "proposal_id"), ("topic_id", "topic_id"), ("section_id", "section_id"), ("transaction_id", "transaction_id"), ("published_at", "published_at")):
        _index(f"ix_knowledge_publication_records_{name}", "knowledge_publication_records", column)


def downgrade() -> None:
    for index in ("ix_knowledge_publication_records_published_at", "ix_knowledge_publication_records_transaction_id", "ix_knowledge_publication_records_section_id", "ix_knowledge_publication_records_topic_id", "ix_knowledge_publication_records_proposal_id"):
        op.drop_index(index, table_name="knowledge_publication_records")
    op.drop_table("knowledge_publication_records")
    for index in ("ix_knowledge_review_decisions_created_at", "ix_knowledge_review_decisions_action", "ix_knowledge_review_decisions_proposal_id"):
        op.drop_index(index, table_name="knowledge_review_decisions")
    op.drop_table("knowledge_review_decisions")
    for index in ("ix_knowledge_proposal_sources_is_private", "ix_knowledge_proposal_sources_verification_status", "ix_knowledge_proposal_sources_content_hash", "ix_knowledge_proposal_sources_research_source_id", "ix_knowledge_proposal_sources_proposal_id"):
        op.drop_index(index, table_name="knowledge_proposal_sources")
    op.drop_table("knowledge_proposal_sources")
    for index in ("ix_knowledge_topic_relationships_target_topic_id", "ix_knowledge_topic_relationships_source_topic_id"):
        op.drop_index(index, table_name="knowledge_topic_relationships")
    op.drop_table("knowledge_topic_relationships")
    for index in ("ix_knowledge_topic_section_versions_status", "ix_knowledge_topic_section_versions_proposal_id", "ix_knowledge_topic_section_versions_section_id"):
        op.drop_index(index, table_name="knowledge_topic_section_versions")
    op.drop_table("knowledge_topic_section_versions")
    for index in ("ix_knowledge_topic_sections_status", "ix_knowledge_topic_sections_section_type", "ix_knowledge_topic_sections_topic_id"):
        op.drop_index(index, table_name="knowledge_topic_sections")
    op.drop_table("knowledge_topic_sections")
    op.drop_index("ix_knowledge_topic_proposals_idempotency_key", table_name="knowledge_topic_proposals")
    for name in ("base_section_version", "source_type", "section_type", "action"):
        op.drop_index(f"ix_knowledge_topic_proposals_{name}_contract", table_name="knowledge_topic_proposals")
    for name in ("change_reason", "proposed_content", "original_content", "base_section_version", "idempotency_key", "source_type", "section_type", "action", "schema_version"):
        op.drop_column("knowledge_topic_proposals", name)
    op.drop_index("ix_knowledge_topics_topic_key", table_name="knowledge_topics")
    op.drop_column("knowledge_topics", "topic_key")
