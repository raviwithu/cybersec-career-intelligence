"""knowledge map placement context: a per-domain note on a shared topic's placement

Revision ID: ph14placementcontext
Revises: ph13mapplacement
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph14placementcontext"
down_revision: Union[str, None] = "ph13mapplacement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One topic (e.g. SSRF) is reused across domains; the note says how it applies in each one. NULL means no note.
    with op.batch_alter_table("knowledge_topic_domains") as batch_op:
        batch_op.add_column(sa.Column("context_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_topic_domains") as batch_op:
        batch_op.drop_column("context_note")
