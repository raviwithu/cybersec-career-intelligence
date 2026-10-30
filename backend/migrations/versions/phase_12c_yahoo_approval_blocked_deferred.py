"""Also mark deferred Yahoo jobs whose bulk-approval fetch failed as approval_blocked

Revision ID: ph12cblockeddeferred
Revises: ph12bapprovalblocked
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ph12cblockeddeferred"
down_revision: Union[str, None] = "ph12bapprovalblocked"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ph12bapprovalblocked only moved pending jobs, but the inferred count it replaced also covered deferred ones.
    # Only jobs whose latest review is the bulk approval: a deferral made after the failed fetch already resolved the block.
    op.execute(
        """
        UPDATE yahoo_job_candidates SET ingestion_status = 'approval_blocked'
        WHERE ingestion_status = 'not_approved'
          AND description_status = 'failed'
          AND review_status = 'deferred'
          AND (SELECT action FROM yahoo_job_reviews WHERE candidate_id = yahoo_job_candidates.id ORDER BY id DESC LIMIT 1) = 'approve_after_fetch'
        """
    )


def downgrade() -> None:
    # ph12bapprovalblocked's downgrade resets every approval_blocked row; nothing to undo separately.
    pass
