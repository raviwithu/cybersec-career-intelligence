"""unified Ollama and OpenWebUI model selection

Revision ID: phase5providers
Revises: phase5models
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "phase5providers"
down_revision: Union[str, None] = "phase5models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    selection_columns = _columns("model_selection")
    if "selected_provider" not in selection_columns:
        op.add_column("model_selection", sa.Column("selected_provider", sa.String(length=30), nullable=True, server_default="ollama"))

    evaluation_columns = _columns("model_evaluations")
    if "provider" not in evaluation_columns:
        op.add_column("model_evaluations", sa.Column("provider", sa.String(length=30), nullable=True, server_default="ollama"))
    if "model_id" not in evaluation_columns:
        op.add_column("model_evaluations", sa.Column("model_id", sa.String(length=255), nullable=True, server_default=""))

    submission_columns = _columns("research_submissions")
    if "model_provider" not in submission_columns:
        op.add_column("research_submissions", sa.Column("model_provider", sa.String(length=30), nullable=True))
    if "model_id" not in submission_columns:
        op.add_column("research_submissions", sa.Column("model_id", sa.String(length=255), nullable=True))

    for table, name, column in (
        ("model_evaluations", "ix_model_evaluations_provider", "provider"),
        ("model_evaluations", "ix_model_evaluations_model_id", "model_id"),
    ):
        if name not in _indexes(table):
            op.create_index(name, table, [column])


def downgrade() -> None:
    op.drop_index("ix_model_evaluations_model_id", table_name="model_evaluations")
    op.drop_index("ix_model_evaluations_provider", table_name="model_evaluations")
    op.drop_column("research_submissions", "model_id")
    op.drop_column("research_submissions", "model_provider")
    op.drop_column("model_evaluations", "model_id")
    op.drop_column("model_evaluations", "provider")
    op.drop_column("model_selection", "selected_provider")
