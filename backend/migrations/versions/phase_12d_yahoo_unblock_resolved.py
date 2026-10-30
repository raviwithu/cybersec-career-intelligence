"""Unblock Yahoo jobs that an administrator resolved after their bulk-approval fetch failed

Revision ID: ph12dunblockresolved
Revises: ph12cblockeddeferred
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ph12dunblockresolved"
down_revision: Union[str, None] = "ph12cblockeddeferred"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The first ph12cblockeddeferred also blocked jobs the administrator deferred after the failed fetch;
    # a block only stands while the bulk approval is still the job's latest review.
    op.execute(
        """
        UPDATE yahoo_job_candidates SET ingestion_status = 'not_approved'
        WHERE ingestion_status = 'approval_blocked'
          AND (SELECT action FROM yahoo_job_reviews WHERE candidate_id = yahoo_job_candidates.id ORDER BY id DESC LIMIT 1) <> 'approve_after_fetch'
        """
    )


def downgrade() -> None:
    # The wrongly blocked rows are not recorded separately; nothing to undo.
    pass
