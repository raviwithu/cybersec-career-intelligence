from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .admin_auth import require_admin
from .database import get_db
from .knowledge_auth import enforce_proposal_rate_limit, require_proposal_submitter
from .knowledge_contract_schemas import KnowledgeCoverageResponse, KnowledgeProposalCreate, KnowledgeProposalPage, KnowledgeProposalPublish, KnowledgeProposalResponse, KnowledgeProposalReview, KnowledgePublicTopicResponse
from .knowledge_contract_service import admin_topic, coverage, get_proposal, list_proposals, list_public_topics, proposal_response, public_topic, publish_proposal, resolve_topic, create_proposal, review_proposal
from .models import KnowledgeTopic, KnowledgeTopicProposal

router = APIRouter(prefix="/knowledge", tags=["knowledge-contract"])


def _topic_identifier(value: str) -> tuple[int | None, str | None]:
    try:
        return int(value), None
    except ValueError:
        return None, value


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/topics", response_model=list[KnowledgePublicTopicResponse])
def get_topics(search: str | None = Query(default=None, max_length=120), db: Session = Depends(get_db)) -> list[KnowledgePublicTopicResponse]:
    return [KnowledgePublicTopicResponse.model_validate(public_topic(db, topic)) for topic in list_public_topics(db, search)]


@router.get("/topics/{topic_identifier}", response_model=KnowledgePublicTopicResponse)
def get_topic(topic_identifier: str, db: Session = Depends(get_db)) -> KnowledgePublicTopicResponse:
    topic_id, topic_key = _topic_identifier(topic_identifier)
    topic = resolve_topic(db, topic_id, topic_key, require_active=False)
    if topic is None or not topic.is_active or topic.publication_status != "published":
        raise HTTPException(status_code=404, detail="Published knowledge topic was not found")
    return KnowledgePublicTopicResponse.model_validate(public_topic(db, topic))


@router.get("/topics/{topic_identifier}/coverage", response_model=KnowledgeCoverageResponse)
def get_topic_coverage(topic_identifier: str, db: Session = Depends(get_db)) -> KnowledgeCoverageResponse:
    topic_id, topic_key = _topic_identifier(topic_identifier)
    topic = resolve_topic(db, topic_id, topic_key, require_active=False)
    if topic is None or not topic.is_active or topic.publication_status != "published":
        raise HTTPException(status_code=404, detail="Published knowledge topic was not found")
    return KnowledgeCoverageResponse.model_validate(coverage(db, topic))


@router.get("/admin/topics/{topic_id}", response_model=KnowledgePublicTopicResponse, dependencies=[Depends(require_admin)])
def get_admin_topic(topic_id: int, db: Session = Depends(get_db)) -> KnowledgePublicTopicResponse:
    topic = resolve_topic(db, topic_id, None, require_active=False)
    if topic is None:
        raise HTTPException(status_code=404, detail="Knowledge topic was not found")
    return KnowledgePublicTopicResponse.model_validate(admin_topic(db, topic))


@router.get("/admin/topics", response_model=list[KnowledgePublicTopicResponse], dependencies=[Depends(require_admin)])
def get_admin_topics(db: Session = Depends(get_db)) -> list[KnowledgePublicTopicResponse]:
    topics = list(db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.display_order, KnowledgeTopic.name)).all())
    return [KnowledgePublicTopicResponse.model_validate(admin_topic(db, topic)) for topic in topics]


@router.post("/proposals", response_model=KnowledgeProposalResponse, status_code=status.HTTP_201_CREATED)
def submit_proposal(
    payload: KnowledgeProposalCreate,
    actor: str = Depends(require_proposal_submitter),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> KnowledgeProposalResponse:
    enforce_proposal_rate_limit(actor)
    proposal = create_proposal(db, payload, actor, idempotency_key)
    return KnowledgeProposalResponse.model_validate(proposal_response(proposal, include_private=actor == "administrator"))


@router.get("/proposals/{proposal_id}", response_model=KnowledgeProposalResponse)
def get_proposal_status(proposal_id: int, actor: str = Depends(require_proposal_submitter), db: Session = Depends(get_db)) -> KnowledgeProposalResponse:
    proposal = get_proposal(db, proposal_id)
    if actor != "administrator" and proposal.submitted_by != actor:
        raise HTTPException(status_code=404, detail="Knowledge proposal was not found")
    return KnowledgeProposalResponse.model_validate(proposal_response(proposal, include_private=actor == "administrator"))


@router.get("/admin/proposals", response_model=KnowledgeProposalPage, dependencies=[Depends(require_admin)])
def get_review_queue(
    source_type: str | None = None,
    domain_id: int | None = Query(default=None, ge=1),
    topic_id: int | None = Query(default=None, ge=1),
    action: str | None = None,
    review_status: str | None = Query(default=None, alias="status"),
    submitted_after: datetime | None = None,
    submitted_before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> KnowledgeProposalPage:
    filters = {"source_type": source_type, "topic_id": topic_id, "action": action, "status": review_status, "submitted_after": _utc(submitted_after), "submitted_before": _utc(submitted_before)}
    all_items = list_proposals(db, filters)
    if domain_id:
        all_items = [item for item in all_items if domain_id in (item.proposed_content or {}).get("domain_ids", []) or domain_id in ((item.proposed_content or {}).get("topic") or {}).get("domain_ids", [])]
    counts = dict(db.execute(select(KnowledgeTopicProposal.status, func.count(KnowledgeTopicProposal.id)).where(KnowledgeTopicProposal.contract == "section_v1").group_by(KnowledgeTopicProposal.status)).all())
    total = len(all_items)
    items = all_items[offset:offset + limit]
    return KnowledgeProposalPage(items=[KnowledgeProposalResponse.model_validate(proposal_response(item)) for item in items], total=total, counts=counts)


@router.post("/admin/proposals/{proposal_id}/review", response_model=KnowledgeProposalResponse, dependencies=[Depends(require_admin)])
def review_knowledge_proposal(proposal_id: int, payload: KnowledgeProposalReview, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeProposalResponse:
    return KnowledgeProposalResponse.model_validate(proposal_response(review_proposal(db, proposal_id, payload, actor)))


@router.post("/admin/proposals/{proposal_id}/publish", response_model=KnowledgeProposalResponse, dependencies=[Depends(require_admin)])
def publish_knowledge_proposal(proposal_id: int, payload: KnowledgeProposalPublish, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeProposalResponse:
    return KnowledgeProposalResponse.model_validate(proposal_response(publish_proposal(db, proposal_id, payload.expected_version, actor, payload.change_reason)))


@router.get("/admin/topics/{topic_id}/coverage", response_model=KnowledgeCoverageResponse, dependencies=[Depends(require_admin)])
def get_admin_topic_coverage(topic_id: int, db: Session = Depends(get_db)) -> KnowledgeCoverageResponse:
    topic = resolve_topic(db, topic_id, None, require_active=False)
    if topic is None:
        raise HTTPException(status_code=404, detail="Knowledge topic was not found")
    return KnowledgeCoverageResponse.model_validate(coverage(db, topic, include_pending=True))
