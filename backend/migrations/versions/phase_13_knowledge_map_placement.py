"""knowledge map placement: branch and display order on topic-domain links

Revision ID: ph13mapplacement
Revises: ph12dunblockresolved
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph13mapplacement"
down_revision: Union[str, None] = "ph12dunblockresolved"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing links keep map_branch NULL: they stay in Career Readiness but are not on the map.
    with op.batch_alter_table("knowledge_topic_domains") as batch_op:
        batch_op.add_column(sa.Column("map_branch", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_check_constraint("ck_knowledge_topic_domains_map_branch", "map_branch IN ('foundations','security','vulnerabilities')")
    op.create_index("ix_knowledge_topic_domains_map_placement", "knowledge_topic_domains", ["domain_id", "map_branch", "display_order"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_topic_domains_map_placement", table_name="knowledge_topic_domains")
    with op.batch_alter_table("knowledge_topic_domains") as batch_op:
        batch_op.drop_constraint("ck_knowledge_topic_domains_map_branch", type_="check")
        batch_op.drop_column("display_order")
        batch_op.drop_column("map_branch")
