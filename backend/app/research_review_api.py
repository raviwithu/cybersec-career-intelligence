from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .database import get_db
from .models import (
    CareerLevel,
    Competency,
    CompetencyCategory,
    ExpectationRevision,
    ResearchFinding,
    ResearchFindingDomain,
    ResearchSource,
    ResearchSubmission,
    ReviewAudit,
    ReviewChange,
    SecurityDomain,
)
from .research_review_schemas import (
    HistoryResponse,
    PublicationPreviewResponse,
    PublicationRequest,
    PublicationResponse,
    ReviewActionRequest,
    ReviewComparisonResponse,
    ReviewDashboardResponse,
    ReviewFindingResponse,
    ReviewMergeRequest,
    ReviewModifyRequest,
    ReviewMutationResponse,
    ReviewSubmissionDetail,
)
from .research_review_service import (
    accept_change,
    change_response,
    compare_change,
    domain_impact,
    ensure_all_changes,
    ensure_submission_changes,
    finding_response,
    merge_change,
    modify_change,
    publication_preview,
    publish_changes,
    reject_change,
    submission_summary,
)

router = APIRouter(prefix="/research/review", tags=["research-review"])


def _submission_query():
    return select(ResearchSubmission).options(
        selectinload(ResearchSubmission.source),
        selectinload(ResearchSubmission.findings).selectinload(ResearchFinding.domains).selectinload(ResearchFindingDomain.domain),
        selectinload(ResearchSubmission.findings).selectinload(ResearchFinding.domain),
        selectinload(ResearchSubmission.findings).selectinload(ResearchFinding.career_level),
        selectinload(ResearchSubmission.findings).selectinload(ResearchFinding.category),
        selectinload(ResearchSubmission.findings).selectinload(ResearchFinding.competency).selectinload(Competency.category),
        selectinload(ResearchSubmission.review_changes),
    )


def _get_submission(db: Session, submission_id: int) -> ResearchSubmission:
    item = db.scalar(_submission_query().where(ResearchSubmission.id == submission_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Research submission was not found")
    return item


def _change_query():
    return select(ReviewChange).options(
        selectinload(ReviewChange.finding).selectinload(ResearchFinding.domains).selectinload(ResearchFindingDomain.domain),
        selectinload(ReviewChange.finding).selectinload(ResearchFinding.domain),
        selectinload(ReviewChange.finding).selectinload(ResearchFinding.career_level),
        selectinload(ReviewChange.finding).selectinload(ResearchFinding.category),
        selectinload(ReviewChange.finding).selectinload(ResearchFinding.competency).selectinload(Competency.category),
        selectinload(ReviewChange.audits),
    )


def _get_change(db: Session, change_id: int) -> ReviewChange:
    item = db.scalar(_change_query().where(ReviewChange.id == change_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Review change was not found")
    return item


def _existing_matches(db: Session, finding: ResearchFinding) -> list[dict[str, Any]]:
    if finding.competency_id is None:
        return []
    from .research_review_service import _expectation_snapshot, _find_expectations

    return [_expectation_snapshot(item) for item in _find_expectations(db, finding)]


def _finding_response(db: Session, finding: ResearchFinding, change: ReviewChange | None) -> dict[str, Any]:
    result = finding_response(finding, change)
    result["existing_matches"] = _existing_matches(db, finding)
    return result


def _filter_changes(
    db: Session,
    changes: list[ReviewChange],
    domain_id: int | None,
    subdomain_id: int | None,
    career_level_id: int | None,
    category_id: int | None,
    source_id: int | None,
    review_status: str | None,
    change_type: str | None,
) -> list[ReviewChange]:
    descendants: set[int] | None = None
    if subdomain_id is not None:
        children_by_parent: dict[int | None, list[int]] = {}
        for domain in db.scalars(select(SecurityDomain)).all():
            children_by_parent.setdefault(domain.parent_id, []).append(domain.id)
        descendants = set()
        pending = [subdomain_id]
        while pending:
            current = pending.pop()
            if current in descendants:
                continue
            descendants.add(current)
            pending.extend(children_by_parent.get(current, []))
    result = []
    for change in changes:
        proposed = change.proposed_snapshot
        proposed_domains = set(proposed.get("domain_ids", []))
        if domain_id is not None and domain_id not in proposed_domains:
            continue
        if descendants is not None and not proposed_domains.intersection(descendants):
            continue
        if career_level_id is not None and proposed.get("career_level_id") != career_level_id:
            continue
        if category_id is not None and proposed.get("category_id") != category_id:
            continue
        if source_id is not None and change.submission.source_id != source_id:
            continue
        if review_status is not None and change.status != review_status:
            continue
        if change_type is not None and change.change_type != change_type:
            continue
        result.append(change)
    return result


def _change_card(change: ReviewChange) -> dict[str, Any]:
    proposed = change.proposed_snapshot
    return {
        **change_response(change),
        "source_title": change.submission.source.source_title if change.submission and change.submission.source else None,
        "source_id": change.submission.source_id if change.submission else None,
        "competency_name": proposed.get("competency_name"),
        "domains": proposed.get("domains", []),
        "career_level": proposed.get("career_level"),
        "category": proposed.get("category"),
        "evidence_count": len(proposed.get("evidence", [])),
    }


@router.get("/dashboard", response_model=ReviewDashboardResponse, dependencies=[Depends(require_admin)])
def review_dashboard(
    domain_id: int | None = None,
    subdomain_id: int | None = None,
    career_level_id: int | None = None,
    category_id: int | None = None,
    source_id: int | None = None,
    review_status: str | None = None,
    change_type: str | None = None,
    db: Session = Depends(get_db),
) -> ReviewDashboardResponse:
    changes = ensure_all_changes(db)
    changes = list(db.scalars(_change_query().order_by(ReviewChange.id.desc())).unique().all())
    filtered = _filter_changes(db, changes, domain_id, subdomain_id, career_level_id, category_id, source_id, review_status, change_type)
    by_submission: dict[int, list[ReviewChange]] = {}
    for change in filtered:
        by_submission.setdefault(change.submission_id, []).append(change)
    pending = []
    for submission_id, rows in by_submission.items():
        if any(item.status == "pending" for item in rows):
            submission = _get_submission(db, submission_id)
            pending.append(submission_summary(db, submission, rows))
    approved = [_change_card(item) for item in filtered if item.status in {"accepted", "modified", "merged"}]
    rejected = [_change_card(item) for item in filtered if item.status == "rejected"]
    history = [_change_card(item) for item in filtered if item.status == "published"]
    domains = list(db.scalars(select(SecurityDomain).where(SecurityDomain.is_active.is_(True)).order_by(SecurityDomain.display_order, SecurityDomain.name)).all())
    levels = list(db.scalars(select(CareerLevel).where(CareerLevel.is_active.is_(True)).order_by(CareerLevel.display_order)).all())
    categories = list(db.scalars(select(CompetencyCategory).where(CompetencyCategory.is_active.is_(True)).order_by(CompetencyCategory.display_order, CompetencyCategory.name)).all())
    sources = list(db.scalars(select(ResearchSource).order_by(ResearchSource.source_title)).all())
    return ReviewDashboardResponse(
        pending_reviews=pending,
        approved_changes=approved,
        rejected_findings=rejected,
        change_history=history,
        filters={
            "domains": [{"id": item.id, "name": item.name, "slug": item.slug, "parent_id": item.parent_id} for item in domains],
            "career_levels": [{"id": item.id, "name": item.name, "slug": item.slug} for item in levels],
            "categories": [{"id": item.id, "name": item.name, "slug": item.slug} for item in categories],
            "sources": [{"id": item.id, "name": item.source_title} for item in sources],
        },
    )


@router.get("/submissions/{submission_id}", response_model=ReviewSubmissionDetail, dependencies=[Depends(require_admin)])
def review_submission(submission_id: int, db: Session = Depends(get_db)) -> ReviewSubmissionDetail:
    submission = _get_submission(db, submission_id)
    changes = ensure_submission_changes(db, submission_id)
    db.commit()
    changes = list(db.scalars(_change_query().where(ReviewChange.submission_id == submission_id)).unique().all())
    change_by_finding = {item.finding_id: item for item in changes}
    return ReviewSubmissionDetail(
        submission=submission_summary(db, submission, changes),
        source={
            "id": submission.source.id,
            "title": submission.source.source_title,
            "url": submission.source.source_url,
            "type": submission.source.source_type,
            "collected_at": submission.source.collected_at,
            "notes": submission.source.notes,
            "provider": submission.model_provider,
            "model_id": submission.model_id,
            "model_name": submission.model_name,
            "analysis_version": submission.evaluation_version,
            "processing_status": submission.status,
        },
        findings=[ReviewFindingResponse.model_validate(_finding_response(db, item, change_by_finding.get(item.id))) for item in submission.findings],
        domain_impact=domain_impact(db, changes),
    )


@router.get("/submissions/{submission_id}/impact", response_model=list[dict[str, Any]], dependencies=[Depends(require_admin)])
def submission_impact(submission_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _get_submission(db, submission_id)
    changes = ensure_submission_changes(db, submission_id)
    db.commit()
    return domain_impact(db, changes)


@router.get("/changes/{change_id}/comparison", response_model=ReviewComparisonResponse, dependencies=[Depends(require_admin)])
def change_comparison(change_id: int, db: Session = Depends(get_db)) -> ReviewComparisonResponse:
    return ReviewComparisonResponse.model_validate(compare_change(db, _get_change(db, change_id)))


@router.post("/changes/{change_id}/accept", response_model=ReviewMutationResponse, dependencies=[Depends(require_admin)])
def accept_review_change(change_id: int, payload: ReviewActionRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> ReviewMutationResponse:
    try:
        change = accept_change(db, change_id, payload.expected_version, actor, payload.reviewer_note, payload.publish)
    except HTTPException:
        db.rollback()
        raise
    return ReviewMutationResponse(status=change.status, change=change_response(change))


@router.patch("/changes/{change_id}", response_model=ReviewMutationResponse, dependencies=[Depends(require_admin)])
def modify_review_change(change_id: int, payload: ReviewModifyRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> ReviewMutationResponse:
    return ReviewMutationResponse(status="modified", change=change_response(modify_change(db, change_id, payload, actor)))


@router.post("/changes/{change_id}/merge", response_model=ReviewMutationResponse, dependencies=[Depends(require_admin)])
def merge_review_change(change_id: int, payload: ReviewMergeRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> ReviewMutationResponse:
    return ReviewMutationResponse(status="merged", change=change_response(merge_change(db, change_id, payload, actor)))


@router.post("/changes/{change_id}/reject", response_model=ReviewMutationResponse, dependencies=[Depends(require_admin)])
def reject_review_change(change_id: int, payload: ReviewActionRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> ReviewMutationResponse:
    return ReviewMutationResponse(status="rejected", change=change_response(reject_change(db, change_id, payload.expected_version, actor, payload.reviewer_note)))


@router.get("/publication-preview", response_model=PublicationPreviewResponse, dependencies=[Depends(require_admin)])
def get_publication_preview(
    change_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PublicationPreviewResponse:
    return PublicationPreviewResponse.model_validate(publication_preview(db, change_ids))


@router.post("/publish", response_model=PublicationResponse, dependencies=[Depends(require_admin)])
def publish_review_changes(payload: PublicationRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> PublicationResponse:
    try:
        batch, expectation_ids, competency_ids = publish_changes(db, payload.change_ids, payload.expected_versions, actor)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Publication failed and was rolled back") from exc
    published_change_ids = list(db.scalars(select(ReviewChange.id).where(ReviewChange.publication_batch_id == batch.id).order_by(ReviewChange.id)).all())
    return PublicationResponse(status="published", batch_id=batch.id, published_change_ids=published_change_ids, published_expectation_ids=sorted(set(expectation_ids)), published_competency_ids=sorted(set(competency_ids)))


@router.get("/history", response_model=HistoryResponse, dependencies=[Depends(require_admin)])
def review_history(
    submission_id: int | None = None,
    change_id: int | None = None,
    db: Session = Depends(get_db),
) -> HistoryResponse:
    query = select(ReviewAudit).options(selectinload(ReviewAudit.change).selectinload(ReviewChange.finding)).order_by(ReviewAudit.created_at.desc())
    if submission_id is not None:
        query = query.join(ReviewAudit.change).where(ReviewChange.submission_id == submission_id)
    if change_id is not None:
        query = query.where(ReviewAudit.change_id == change_id)
    items = list(db.scalars(query).unique().all())
    return HistoryResponse(items=[{
        "id": item.id,
        "change_id": item.change_id,
        "finding_id": item.change.finding_id,
        "submission_id": item.change.submission_id,
        "action": item.action,
        "actor": item.actor,
        "before": item.before_snapshot,
        "after": item.after_snapshot,
        "note": item.note,
        "created_at": item.created_at,
    } for item in items], total=len(items))


@router.get("/history/expectations/{expectation_id}", response_model=HistoryResponse, dependencies=[Depends(require_admin)])
def expectation_history(expectation_id: int, db: Session = Depends(get_db)) -> HistoryResponse:
    items = list(db.scalars(select(ExpectationRevision).where(ExpectationRevision.expectation_id == expectation_id).order_by(ExpectationRevision.version.desc())).all())
    return HistoryResponse(items=[{
        "id": item.id,
        "expectation_id": item.expectation_id,
        "change_id": item.change_id,
        "version": item.version,
        "snapshot": item.snapshot,
        "created_at": item.created_at,
    } for item in items], total=len(items))
