"""model selection and evaluation traceability

Revision ID: phase5models
Revises: phase5research
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase5models"
down_revision: Union[str, None] = "phase5research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "model_selection" not in tables:
        op.create_table(
            "model_selection",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("selected_model", sa.String(length=255)),
            sa.Column("mode", sa.String(length=20), nullable=False),
            sa.Column("evaluation_version", sa.String(length=80)),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "model_evaluations" not in tables:
        op.create_table(
            "model_evaluations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("evaluation_version", sa.String(length=80), nullable=False),
            sa.Column("model_name", sa.String(length=255), nullable=False),
            sa.Column("extraction_accuracy", sa.Float(), nullable=False),
            sa.Column("classification_accuracy", sa.Float(), nullable=False),
            sa.Column("json_validity", sa.Float(), nullable=False),
            sa.Column("hallucination_rate", sa.Float(), nullable=False),
            sa.Column("average_processing_ms", sa.Float(), nullable=False),
            sa.Column("overall_score", sa.Float(), nullable=False),
            sa.Column("error_message", sa.Text()),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        )

    indexes = {index["name"] for index in inspector.get_indexes("model_evaluations")}
    for name, column in (
        ("ix_model_evaluations_evaluation_version", "evaluation_version"),
        ("ix_model_evaluations_model_name", "model_name"),
        ("ix_model_evaluations_overall_score", "overall_score"),
    ):
        if name not in indexes:
            op.create_index(name, "model_evaluations", [column])

    submission_columns = {column["name"] for column in inspector.get_columns("research_submissions")}
    if "model_name" not in submission_columns:
        op.add_column("research_submissions", sa.Column("model_name", sa.String(length=255)))
    if "evaluation_version" not in submission_columns:
        op.add_column("research_submissions", sa.Column("evaluation_version", sa.String(length=80)))


def downgrade() -> None:
    op.drop_column("research_submissions", "evaluation_version")
    op.drop_column("research_submissions", "model_name")
    op.drop_index("ix_model_evaluations_overall_score", table_name="model_evaluations")
    op.drop_index("ix_model_evaluations_model_name", table_name="model_evaluations")
    op.drop_index("ix_model_evaluations_evaluation_version", table_name="model_evaluations")
    op.drop_table("model_evaluations")
    op.drop_table("model_selection")
