"""private competency profiles for Phase 7 intelligence

Revision ID: phase7profiles
Revises: phase6jobsearch
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase7profiles"
down_revision: Union[str, None] = "phase6jobsearch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "competency_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_token_hash", sa.String(length=128), nullable=False),
        sa.Column("target_industry_id", sa.Integer(), nullable=True),
        sa.Column("target_domain_id", sa.Integer(), nullable=True),
        sa.Column("target_career_level_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_industry_id"], ["industries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_domain_id"], ["security_domains.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_career_level_id"], ["career_levels.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("profile_token_hash", name="uq_competency_profile_token_hash"),
    )
    op.create_index("ix_competency_profiles_id", "competency_profiles", ["id"])
    op.create_index("ix_competency_profiles_target_industry_id", "competency_profiles", ["target_industry_id"])
    op.create_index("ix_competency_profiles_target_domain_id", "competency_profiles", ["target_domain_id"])
    op.create_index("ix_competency_profiles_target_career_level_id", "competency_profiles", ["target_career_level_id"])
    op.create_table(
        "competency_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("proficiency", sa.String(length=30), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["competency_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", "competency_id", name="uq_competency_assessment_profile_competency"),
    )
    op.create_index("ix_competency_assessments_profile_id", "competency_assessments", ["profile_id"])
    op.create_index("ix_competency_assessments_competency_id", "competency_assessments", ["competency_id"])


def downgrade() -> None:
    op.drop_index("ix_competency_assessments_competency_id", table_name="competency_assessments")
    op.drop_index("ix_competency_assessments_profile_id", table_name="competency_assessments")
    op.drop_table("competency_assessments")
    op.drop_index("ix_competency_profiles_target_career_level_id", table_name="competency_profiles")
    op.drop_index("ix_competency_profiles_target_domain_id", table_name="competency_profiles")
    op.drop_index("ix_competency_profiles_target_industry_id", table_name="competency_profiles")
    op.drop_index("ix_competency_profiles_id", table_name="competency_profiles")
    op.drop_table("competency_profiles")
