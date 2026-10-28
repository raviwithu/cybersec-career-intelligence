"""taxonomy management lifecycle, aliases, and audit history

Revision ID: ph9taxonomy
Revises: phase8jsearch
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph9taxonomy"
down_revision: Union[str, None] = "phase8jsearch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("security_domains", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_security_domains_is_active", "security_domains", ["is_active"])

    op.add_column("career_levels", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("career_levels", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.add_column("career_levels", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_career_levels_is_active", "career_levels", ["is_active"])

    op.add_column("competency_categories", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("competency_categories", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("competency_categories", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("competency_categories", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE competency_categories SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE competency_categories SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    with op.batch_alter_table("competency_categories") as batch_op:
        batch_op.alter_column("created_at", nullable=False)
        batch_op.alter_column("updated_at", nullable=False)
    op.create_index("ix_competency_categories_is_active", "competency_categories", ["is_active"])

    op.create_table(
        "security_domain_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=160), nullable=False),
        sa.Column("normalized_alias", sa.String(length=160), nullable=False),
        sa.Column("requires_context", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("context_hint", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["domain_id"], ["security_domains.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("normalized_alias", name="uq_security_domain_alias_normalized"),
    )
    op.create_index("ix_security_domain_aliases_domain_id", "security_domain_aliases", ["domain_id"])
    op.create_index("ix_security_domain_aliases_alias", "security_domain_aliases", ["alias"])
    op.create_index("ix_security_domain_aliases_normalized_alias", "security_domain_aliases", ["normalized_alias"])

    op.create_table(
        "career_level_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("career_level_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("normalized_alias", sa.String(length=80), nullable=False),
        sa.Column("requires_context", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("context_hint", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["career_level_id"], ["career_levels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("normalized_alias", name="uq_career_level_alias_normalized"),
    )
    op.create_index("ix_career_level_aliases_career_level_id", "career_level_aliases", ["career_level_id"])
    op.create_index("ix_career_level_aliases_alias", "career_level_aliases", ["alias"])
    op.create_index("ix_career_level_aliases_normalized_alias", "career_level_aliases", ["normalized_alias"])

    op.create_table(
        "competency_category_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("normalized_alias", sa.String(length=120), nullable=False),
        sa.Column("requires_context", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("context_hint", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["competency_categories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("normalized_alias", name="uq_competency_category_alias_normalized"),
    )
    op.create_index("ix_competency_category_aliases_category_id", "competency_category_aliases", ["category_id"])
    op.create_index("ix_competency_category_aliases_alias", "competency_category_aliases", ["alias"])
    op.create_index("ix_competency_category_aliases_normalized_alias", "competency_category_aliases", ["normalized_alias"])

    op.create_table(
        "taxonomy_change_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("taxonomy_type", sa.String(length=40), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("previous_values", sa.JSON(), nullable=True),
        sa.Column("updated_values", sa.JSON(), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False, server_default="administrator"),
        sa.Column("merge_source_id", sa.Integer(), nullable=True),
        sa.Column("merge_target_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_taxonomy_change_history_taxonomy_type", "taxonomy_change_history", ["taxonomy_type"])
    op.create_index("ix_taxonomy_change_history_entry_id", "taxonomy_change_history", ["entry_id"])
    op.create_index("ix_taxonomy_change_history_action", "taxonomy_change_history", ["action"])
    op.create_index("ix_taxonomy_change_history_merge_source_id", "taxonomy_change_history", ["merge_source_id"])
    op.create_index("ix_taxonomy_change_history_merge_target_id", "taxonomy_change_history", ["merge_target_id"])
    op.create_index("ix_taxonomy_change_history_created_at", "taxonomy_change_history", ["created_at"])


def downgrade() -> None:
    for index, table, columns in (
        ("ix_taxonomy_change_history_created_at", "taxonomy_change_history", ["created_at"]),
        ("ix_taxonomy_change_history_merge_target_id", "taxonomy_change_history", ["merge_target_id"]),
        ("ix_taxonomy_change_history_merge_source_id", "taxonomy_change_history", ["merge_source_id"]),
        ("ix_taxonomy_change_history_action", "taxonomy_change_history", ["action"]),
        ("ix_taxonomy_change_history_entry_id", "taxonomy_change_history", ["entry_id"]),
        ("ix_taxonomy_change_history_taxonomy_type", "taxonomy_change_history", ["taxonomy_type"]),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("taxonomy_change_history")

    for index, table in (
        ("ix_competency_category_aliases_normalized_alias", "competency_category_aliases"),
        ("ix_competency_category_aliases_alias", "competency_category_aliases"),
        ("ix_competency_category_aliases_category_id", "competency_category_aliases"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("competency_category_aliases")

    for index, table in (
        ("ix_career_level_aliases_normalized_alias", "career_level_aliases"),
        ("ix_career_level_aliases_alias", "career_level_aliases"),
        ("ix_career_level_aliases_career_level_id", "career_level_aliases"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("career_level_aliases")

    for index, table in (
        ("ix_security_domain_aliases_normalized_alias", "security_domain_aliases"),
        ("ix_security_domain_aliases_alias", "security_domain_aliases"),
        ("ix_security_domain_aliases_domain_id", "security_domain_aliases"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("security_domain_aliases")

    op.drop_index("ix_competency_categories_is_active", table_name="competency_categories")
    op.drop_column("competency_categories", "updated_at")
    op.drop_column("competency_categories", "created_at")
    op.drop_column("competency_categories", "display_order")
    op.drop_column("competency_categories", "is_active")

    op.drop_index("ix_career_levels_is_active", table_name="career_levels")
    op.drop_column("career_levels", "updated_at")
    op.drop_column("career_levels", "created_at")
    op.drop_column("career_levels", "is_active")

    op.drop_index("ix_security_domains_is_active", table_name="security_domains")
    op.drop_column("security_domains", "is_active")
