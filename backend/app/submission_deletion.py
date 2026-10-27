from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import (
    DraftEvidence,
    DraftExpectation,
    ExpectationRevision,
    ExpectationSource,
    PublicationBatch,
    ResearchFinding,
    ResearchFindingDomain,
    ResearchFindingIndustry,
    ResearchSource,
    ResearchSubmission,
    ResearchSubmissionAudit,
    ReviewAudit,
    ReviewChange,
)

PROCESSING_STATUSES = {"received", "processing"}


class SubmissionDeletionBlocked(Exception):
    def __init__(self, detail: str, status_code: int = 409):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _published_dependencies(db: Session, submission: ResearchSubmission) -> list[str]:
    dependencies: list[str] = []
    published_drafts = list(db.scalars(select(DraftExpectation.id).where(
        DraftExpectation.submission_id == submission.id,
        (DraftExpectation.status == "published") | DraftExpectation.published_expectation_id.is_not(None),
    )).all())
    if published_drafts:
        dependencies.append(f"published draft expectations {published_drafts}")

    published_changes = list(db.scalars(select(ReviewChange.id).where(
        ReviewChange.submission_id == submission.id,
        ReviewChange.status == "published",
    )).all())
    if published_changes:
        dependencies.append(f"published review changes {published_changes}")

    published_batches = list(db.scalars(select(PublicationBatch.id).where(
        PublicationBatch.submission_id == submission.id,
        PublicationBatch.status == "published",
    )).all())
    if published_batches:
        dependencies.append(f"published publication batches {published_batches}")

    published_expectations = list(db.scalars(select(ExpectationSource.expectation_id).where(
        ExpectationSource.source_id == submission.source_id,
    )).all())
    if published_expectations:
        dependencies.append(f"published expectations {published_expectations}")
    return dependencies


def _source_is_used_elsewhere(db: Session, source_id: int, draft_ids: list[int]) -> bool:
    other_draft_evidence = db.scalar(select(func.count()).select_from(DraftEvidence).where(
        DraftEvidence.source_id == source_id,
        ~DraftEvidence.draft_id.in_(draft_ids) if draft_ids else True,
    )) or 0
    expectation_evidence = db.scalar(select(func.count()).select_from(ExpectationSource).where(
        ExpectationSource.source_id == source_id,
    )) or 0
    return bool(other_draft_evidence or expectation_evidence)


def delete_submission(db: Session, submission_id: int, actor: str) -> None:
    try:
        submission = db.scalar(select(ResearchSubmission).where(ResearchSubmission.id == submission_id).with_for_update())
        if submission is None:
            raise SubmissionDeletionBlocked("Research submission was not found", 404)
        if submission.status in PROCESSING_STATUSES:
            raise SubmissionDeletionBlocked(
                "This research submission is still being processed; wait for analysis to finish before deleting it",
            )

        dependencies = _published_dependencies(db, submission)
        if dependencies:
            raise SubmissionDeletionBlocked(
                "This research submission contributed to published knowledge and cannot be deleted: " + "; ".join(dependencies),
            )

        finding_ids = list(db.scalars(select(ResearchFinding.id).where(ResearchFinding.submission_id == submission_id)).all())
        draft_ids = list(db.scalars(select(DraftExpectation.id).where(DraftExpectation.submission_id == submission_id)).all())
        change_ids = list(db.scalars(select(ReviewChange.id).where(ReviewChange.submission_id == submission_id)).all())
        batch_ids = list(db.scalars(select(PublicationBatch.id).where(
            PublicationBatch.submission_id == submission_id,
            PublicationBatch.status != "published",
        )).all())

        db.add(ResearchSubmissionAudit(
            submission_id=submission_id,
            action="deleted",
            actor=actor,
            previous_status=submission.status,
        ))

        if change_ids:
            db.execute(delete(ReviewAudit).where(ReviewAudit.change_id.in_(change_ids)))
            db.execute(delete(ExpectationRevision).where(ExpectationRevision.change_id.in_(change_ids)))
            db.execute(delete(ReviewChange).where(ReviewChange.id.in_(change_ids)))
        if draft_ids:
            db.execute(delete(DraftEvidence).where(DraftEvidence.draft_id.in_(draft_ids)))
            db.execute(delete(DraftExpectation).where(DraftExpectation.id.in_(draft_ids)))
        if finding_ids:
            db.execute(delete(ResearchFindingDomain).where(ResearchFindingDomain.finding_id.in_(finding_ids)))
            db.execute(delete(ResearchFindingIndustry).where(ResearchFindingIndustry.finding_id.in_(finding_ids)))
            db.execute(delete(ResearchFinding).where(ResearchFinding.id.in_(finding_ids)))

        if batch_ids:
            for batch_id in set(batch_ids):
                remaining_changes = db.scalar(select(func.count()).select_from(ReviewChange).where(ReviewChange.publication_batch_id == batch_id)) or 0
                if not remaining_changes:
                    db.execute(delete(PublicationBatch).where(PublicationBatch.id == batch_id))

        source_id = submission.source_id
        source_shared = _source_is_used_elsewhere(db, source_id, draft_ids)
        db.delete(submission)
        if not source_shared:
            db.delete(db.get(ResearchSource, source_id))
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
