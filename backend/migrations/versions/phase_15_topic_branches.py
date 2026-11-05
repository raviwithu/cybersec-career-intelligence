"""knowledge map topic branches: Foundations, Security and Common Vulnerabilities belong to topics, not domains

Revision ID: ph15topicbranches
Revises: ph14placementcontext
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ph15topicbranches"
down_revision: Union[str, None] = "ph14placementcontext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A placement can sit under a parent topic in the same domain, in one of that topic's branches. NULL: directly under the domain.
    with op.batch_alter_table("knowledge_topic_domains") as batch_op:
        batch_op.add_column(sa.Column("parent_topic_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_knowledge_topic_domains_parent_topic", "knowledge_topics", ["parent_topic_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_knowledge_topic_domains_parent_topic_id", ["parent_topic_id"])
    # Topics already nested under a parent topic placed in the same domain keep that nesting; every other placement now
    # sits directly under its domain.
    op.execute("""
        UPDATE knowledge_topic_domains SET parent_topic_id = (
            SELECT t.parent_topic_id FROM knowledge_topics t WHERE t.id = knowledge_topic_domains.topic_id
        )
        WHERE map_branch IS NOT NULL AND EXISTS (
            SELECT 1 FROM knowledge_topics t JOIN knowledge_topic_domains p ON p.topic_id = t.parent_topic_id
            WHERE t.id = knowledge_topic_domains.topic_id AND p.domain_id = knowledge_topic_domains.domain_id AND p.map_branch IS NOT NULL
        )
    """)


def downgrade() -> None:
    with op.batch_alter_table("knowledge_topic_domains") as batch_op:
        batch_op.drop_index("ix_knowledge_topic_domains_parent_topic_id")
        batch_op.drop_constraint("fk_knowledge_topic_domains_parent_topic", type_="foreignkey")
        batch_op.drop_column("parent_topic_id")
