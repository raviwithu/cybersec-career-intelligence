"""Record blocked Yahoo bulk approvals with an explicit ingestion status

Revision ID: ph12bapprovalblocked
Revises: ph12yahoomail
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ph12bapprovalblocked"
down_revision: Union[str, None] = "ph12yahoomail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Jobs whose scheduler fetch failed after a bulk approval were previously only inferable from the review history.
    op.execute(
        """
        UPDATE yahoo_job_candidates SET ingestion_status = 'approval_blocked'
        WHERE ingestion_status = 'not_approved'
          AND description_status = 'failed'
          AND review_status = 'pending'
          AND id IN (SELECT candidate_id FROM yahoo_job_reviews WHERE action = 'approve_after_fetch')
        """
    )


def downgrade() -> None:
    op.execute("UPDATE yahoo_job_candidates SET ingestion_status = 'not_approved' WHERE ingestion_status = 'approval_blocked'")
