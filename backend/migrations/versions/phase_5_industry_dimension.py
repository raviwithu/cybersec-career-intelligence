"""Add configurable industry taxonomy and industry-scoped expectations.

Revision ID: phase5industry
Revises: phase5review
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "phase5industry"
down_revision: Union[str, None] = "phase5review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "industries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("industries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_industries_name"),
        sa.UniqueConstraint("slug", name="uq_industries_slug"),
    )
    op.create_index("ix_industries_parent_id", "industries", ["parent_id"])
    op.create_index("ix_industries_slug", "industries", ["slug"])
    op.create_index("ix_industries_is_active", "industries", ["is_active"])
    op.create_table(
        "industry_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("industry_id", sa.Integer(), sa.ForeignKey("industries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(length=180), nullable=False),
        sa.Column("normalized_alias", sa.String(length=180), nullable=False),
        sa.Column("requires_context", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("context_hint", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("normalized_alias", name="uq_industry_alias_normalized"),
    )
    op.create_index("ix_industry_aliases_industry_id", "industry_aliases", ["industry_id"])
    op.create_index("ix_industry_aliases_alias", "industry_aliases", ["alias"])
    op.create_index("ix_industry_aliases_normalized_alias", "industry_aliases", ["normalized_alias"])

    with op.batch_alter_table("domain_level_expectations") as batch:
        batch.add_column(sa.Column("industry_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_expectations_industry", "industries", ["industry_id"], ["id"])
    op.create_index("ix_domain_level_expectations_industry_id", "domain_level_expectations", ["industry_id"])

    with op.batch_alter_table("draft_expectations") as batch:
        batch.add_column(sa.Column("industry_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_drafts_industry", "industries", ["industry_id"], ["id"])
    op.create_index("ix_draft_expectations_industry_id", "draft_expectations", ["industry_id"])

    with op.batch_alter_table("research_findings") as batch:
        batch.add_column(sa.Column("primary_industry_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("industry_classification_status", sa.String(length=30), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("industry_classification_evidence", sa.Text(), nullable=False, server_default=""))
        batch.create_foreign_key("fk_findings_primary_industry", "industries", ["primary_industry_id"], ["id"])
    op.create_index("ix_research_findings_primary_industry_id", "research_findings", ["primary_industry_id"])
    op.create_index("ix_research_findings_industry_classification_status", "research_findings", ["industry_classification_status"])
    op.create_table(
        "research_finding_industries",
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("research_findings.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("industry_id", sa.Integer(), sa.ForeignKey("industries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("classification_role", sa.String(length=20), nullable=False, server_default="secondary"),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("finding_id", "industry_id", name="uq_research_finding_industry"),
    )


def downgrade() -> None:
    op.drop_table("research_finding_industries")
    op.drop_index("ix_research_findings_industry_classification_status", table_name="research_findings")
    op.drop_index("ix_research_findings_primary_industry_id", table_name="research_findings")
    with op.batch_alter_table("research_findings") as batch:
        batch.drop_constraint("fk_findings_primary_industry", type_="foreignkey")
        batch.drop_column("industry_classification_evidence")
        batch.drop_column("industry_classification_status")
        batch.drop_column("primary_industry_id")
    op.drop_index("ix_draft_expectations_industry_id", table_name="draft_expectations")
    with op.batch_alter_table("draft_expectations") as batch:
        batch.drop_constraint("fk_drafts_industry", type_="foreignkey")
        batch.drop_column("industry_id")
    op.drop_index("ix_domain_level_expectations_industry_id", table_name="domain_level_expectations")
    with op.batch_alter_table("domain_level_expectations") as batch:
        batch.drop_constraint("fk_expectations_industry", type_="foreignkey")
        batch.drop_column("industry_id")
    op.drop_index("ix_industry_aliases_normalized_alias", table_name="industry_aliases")
    op.drop_index("ix_industry_aliases_alias", table_name="industry_aliases")
    op.drop_index("ix_industry_aliases_industry_id", table_name="industry_aliases")
    op.drop_table("industry_aliases")
    op.drop_index("ix_industries_is_active", table_name="industries")
    op.drop_index("ix_industries_slug", table_name="industries")
    op.drop_index("ix_industries_parent_id", table_name="industries")
    op.drop_table("industries")
