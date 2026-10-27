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
    if "domain_accuracy" not in evaluation_columns:
        op.add_column("model_evaluations", sa.Column("domain_accuracy", sa.Float(), nullable=True, server_default="0"))
    if "career_level_accuracy" not in evaluation_columns:
        op.add_column("model_evaluations", sa.Column("career_level_accuracy", sa.Float(), nullable=True, server_default="0"))

    submission_columns = _columns("research_submissions")
    if "model_provider" not in submission_columns:
        op.add_column("research_submissions", sa.Column("model_provider", sa.String(length=30), nullable=True))
    if "model_id" not in submission_columns:
        op.add_column("research_submissions", sa.Column("model_id", sa.String(length=255), nullable=True))

    op.execute("UPDATE model_selection SET selected_provider = 'ollama' WHERE selected_provider IS NULL")
    op.execute("UPDATE model_evaluations SET provider = 'ollama' WHERE provider IS NULL")
    op.execute("UPDATE model_evaluations SET model_id = model_name WHERE model_id IS NULL OR model_id = ''")
    op.execute("UPDATE model_evaluations SET domain_accuracy = classification_accuracy WHERE domain_accuracy IS NULL")
    op.execute("UPDATE model_evaluations SET career_level_accuracy = classification_accuracy WHERE career_level_accuracy IS NULL")
    with op.batch_alter_table("model_selection") as batch:
        batch.alter_column("selected_provider", existing_type=sa.String(length=30), nullable=False)
    with op.batch_alter_table("model_evaluations") as batch:
        batch.alter_column("provider", existing_type=sa.String(length=30), nullable=False)
        batch.alter_column("model_id", existing_type=sa.String(length=255), nullable=False)
        batch.alter_column("domain_accuracy", existing_type=sa.Float(), nullable=False)
        batch.alter_column("career_level_accuracy", existing_type=sa.Float(), nullable=False)

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
    op.drop_column("model_evaluations", "career_level_accuracy")
    op.drop_column("model_evaluations", "domain_accuracy")
    op.drop_column("model_evaluations", "model_id")
    op.drop_column("model_evaluations", "provider")
    op.drop_column("model_selection", "selected_provider")
