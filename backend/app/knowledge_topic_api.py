from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .admin_auth import require_admin
from .database import get_db
from .knowledge_topic_schemas import KnowledgeTopicCreate, KnowledgeTopicDraft, KnowledgeTopicResponse, KnowledgeTopicUpdate, TopicHistoryResponse, TopicImpactResponse, TopicProposalPage, TopicProposalResponse, TopicProposalReview, TopicPublishRequest, TopicPublishResponse
from .knowledge_topic_service import create_topic, ensure_all_topic_proposals, get_topic, history, merge_topic, publish_topics, proposal_response, response, review_proposal, set_topic_active, topic_query, update_topic
from .models import CareerLevel, CompetencyCategory, Industry, KnowledgeTopic, KnowledgeTopicDomain, KnowledgeTopicIndustry, KnowledgeTopicLevel, KnowledgeTopicProposal, SecurityDomain

public_router = APIRouter(tags=["career-readiness"])
admin_router = APIRouter(prefix="/research/career-readiness", tags=["career-readiness-admin"])


def _published_query():
    return topic_query().where(KnowledgeTopic.is_active.is_(True), KnowledgeTopic.publication_status == "published")


def _domain_scope_ids(db: Session, domain_id: int) -> set[int]:
    domains = db.scalars(select(SecurityDomain).where(SecurityDomain.is_active.is_(True))).all()
    children: dict[int | None, list[int]] = {}
    for item in domains:
        children.setdefault(item.parent_id, []).append(item.id)
    result: set[int] = set()
    pending = [domain_id]
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(children.get(current, []))
    return result


def _topic_response(topic: KnowledgeTopic) -> KnowledgeTopicResponse:
    return KnowledgeTopicResponse.model_validate(response(topic))


@public_router.get("/knowledge-topics", response_model=list[KnowledgeTopicResponse])
def list_public_topics(
    domain_id: int | None = Query(default=None, ge=1),
    subdomain_id: int | None = Query(default=None, ge=1),
    industry_id: int | None = Query(default=None, ge=1),
    career_level_id: int | None = Query(default=None, ge=1),
    category_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
) -> list[KnowledgeTopicResponse]:
    query = _published_query()
    selected_domain = subdomain_id or domain_id
    if selected_domain is not None:
        query = query.where(KnowledgeTopic.domains.any(KnowledgeTopicDomain.domain_id.in_(_domain_scope_ids(db, selected_domain))))
    if industry_id is not None:
        query = query.where(KnowledgeTopic.industries.any(KnowledgeTopicIndustry.industry_id == industry_id))
    if career_level_id is not None:
        query = query.where(KnowledgeTopic.level_expectations.any(KnowledgeTopicLevel.career_level_id == career_level_id))
    if category_id is not None:
        query = query.where(KnowledgeTopic.category_id == category_id)
    if search:
        query = query.where(KnowledgeTopic.name.ilike(f"%{search.strip()}%"))
    topics = db.scalars(query.order_by(KnowledgeTopic.display_order, KnowledgeTopic.name)).unique().all()
    return [_topic_response(topic) for topic in topics]


@public_router.get("/knowledge-topics/{topic_id}", response_model=KnowledgeTopicResponse)
def get_public_topic(topic_id: int, db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    topic = db.scalar(_published_query().where(KnowledgeTopic.id == topic_id))
    if topic is None:
        raise HTTPException(status_code=404, detail="Published knowledge topic was not found")
    return _topic_response(topic)


@admin_router.get("/topics", response_model=list[KnowledgeTopicResponse], dependencies=[Depends(require_admin)])
def list_admin_topics(include_inactive: bool = True, status_filter: str | None = None, search: str | None = Query(default=None, max_length=120), db: Session = Depends(get_db)) -> list[KnowledgeTopicResponse]:
    query = topic_query()
    if not include_inactive:
        query = query.where(KnowledgeTopic.is_active.is_(True))
    if status_filter:
        query = query.where(KnowledgeTopic.publication_status == status_filter)
    if search:
        query = query.where(KnowledgeTopic.name.ilike(f"%{search.strip()}%"))
    return [_topic_response(topic) for topic in db.scalars(query.order_by(KnowledgeTopic.display_order, KnowledgeTopic.name)).unique().all()]


@admin_router.get("/topics/{topic_id}", response_model=KnowledgeTopicResponse, dependencies=[Depends(require_admin)])
def get_admin_topic(topic_id: int, db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    return _topic_response(get_topic(db, topic_id))


@admin_router.post("/topics", response_model=KnowledgeTopicResponse, status_code=status.HTTP_201_CREATED)
def create_admin_topic(payload: KnowledgeTopicCreate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    topic = create_topic(db, payload, actor)
    if payload.publication_status == "published":
        published, _, _ = publish_topics(db, None, [topic.id], {topic.id: topic.version}, actor, "Initial administrator publication.")
        topic = get_topic(db, topic.id)
    return _topic_response(topic)


@admin_router.patch("/topics/{topic_id}", response_model=KnowledgeTopicResponse)
def update_admin_topic(topic_id: int, payload: KnowledgeTopicUpdate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    return _topic_response(update_topic(db, topic_id, payload, actor))


@admin_router.post("/topics/{topic_id}/publish", response_model=TopicPublishResponse)
def publish_admin_topic(topic_id: int, payload: TopicPublishRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TopicPublishResponse:
    topic = get_topic(db, topic_id)
    published, proposals, versions = publish_topics(db, None, [topic_id], {topic_id: payload.expected_versions.get(topic_id, topic.version)}, actor, payload.change_reason)
    return TopicPublishResponse(status="published", published_topic_ids=published, published_proposal_ids=proposals, versions=versions)


@admin_router.post("/topics/{topic_id}/deactivate", response_model=KnowledgeTopicResponse)
def deactivate_topic(topic_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    return _topic_response(set_topic_active(db, topic_id, False, actor))


@admin_router.post("/topics/{topic_id}/reactivate", response_model=KnowledgeTopicResponse)
def reactivate_topic(topic_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    topic = set_topic_active(db, topic_id, True, actor)
    if topic.publication_status != "published":
        raise HTTPException(status_code=409, detail="Only published topics can be reactivated for public consumers")
    return _topic_response(topic)


@admin_router.post("/topics/{topic_id}/merge", response_model=KnowledgeTopicResponse)
def merge_admin_topic(topic_id: int, target_topic_id: int = Query(ge=1), reason: str = Query(default="", max_length=500), actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> KnowledgeTopicResponse:
    return _topic_response(merge_topic(db, topic_id, target_topic_id, actor, reason))


@admin_router.get("/topics/{topic_id}/history", response_model=TopicHistoryResponse, dependencies=[Depends(require_admin)])
def topic_history(topic_id: int, db: Session = Depends(get_db)) -> TopicHistoryResponse:
    get_topic(db, topic_id)
    items = history(db, topic_id)
    return TopicHistoryResponse(items=items, total=len(items))


@admin_router.get("/proposals", response_model=TopicProposalPage, dependencies=[Depends(require_admin)])
def list_topic_proposals(
    status_filter: str | None = None,
    proposal_type: str | None = None,
    domain_id: int | None = Query(default=None, ge=1),
    subdomain_id: int | None = Query(default=None, ge=1),
    industry_id: int | None = Query(default=None, ge=1),
    career_level_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> TopicProposalPage:
    proposals = list(db.scalars(select(KnowledgeTopicProposal).order_by(KnowledgeTopicProposal.created_at.desc())).all())
    if not proposals:
        proposals = ensure_all_topic_proposals(db)
    else:
        ensure_all_topic_proposals(db)
        proposals = list(db.scalars(select(KnowledgeTopicProposal).order_by(KnowledgeTopicProposal.created_at.desc())).all())
    selected_domain = subdomain_id or domain_id
    filtered = []
    for proposal in proposals:
        proposed = proposal.proposed_snapshot or {}
        if status_filter and proposal.status != status_filter:
            continue
        if proposal_type and proposal.proposal_type != proposal_type:
            continue
        if selected_domain is not None and selected_domain not in proposed.get("domain_ids", []):
            continue
        if industry_id is not None and industry_id not in proposed.get("industry_ids", []):
            continue
        if career_level_id is not None and career_level_id not in [item.get("career_level_id") for item in proposed.get("level_expectations", [])]:
            continue
        filtered.append(proposal)
    counts: dict[str, int] = {}
    for proposal in proposals:
        counts[proposal.status] = counts.get(proposal.status, 0) + 1
    domains = db.scalars(select(SecurityDomain).where(SecurityDomain.is_active.is_(True)).order_by(SecurityDomain.display_order, SecurityDomain.name)).all()
    industries = db.scalars(select(Industry).where(Industry.is_active.is_(True)).order_by(Industry.display_order, Industry.name)).all()
    levels = db.scalars(select(CareerLevel).where(CareerLevel.is_active.is_(True)).order_by(CareerLevel.display_order)).all()
    categories = db.scalars(select(CompetencyCategory).where(CompetencyCategory.is_active.is_(True)).order_by(CompetencyCategory.display_order, CompetencyCategory.name)).all()
    return TopicProposalPage(items=[TopicProposalResponse.model_validate(proposal_response(db, item)) for item in filtered], total=len(filtered), counts=counts, filters={"domains": [{"id": item.id, "name": item.name, "slug": item.slug, "parent_id": item.parent_id} for item in domains], "industries": [{"id": item.id, "name": item.name, "slug": item.slug} for item in industries], "career_levels": [{"id": item.id, "name": item.name, "slug": item.slug} for item in levels], "categories": [{"id": item.id, "name": item.name, "slug": item.slug} for item in categories]})


@admin_router.get("/proposals/{proposal_id}", response_model=TopicProposalResponse, dependencies=[Depends(require_admin)])
def get_topic_proposal(proposal_id: int, db: Session = Depends(get_db)) -> TopicProposalResponse:
    proposal = db.scalar(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id == proposal_id))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Knowledge topic proposal was not found")
    return TopicProposalResponse.model_validate(proposal_response(db, proposal))


@admin_router.post("/proposals/{proposal_id}/review", response_model=TopicProposalResponse)
def review_topic_proposal(proposal_id: int, payload: TopicProposalReview, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TopicProposalResponse:
    return TopicProposalResponse.model_validate(proposal_response(db, review_proposal(db, proposal_id, payload, actor)))


@admin_router.post("/proposals/publish", response_model=TopicPublishResponse)
def publish_topic_proposals(payload: TopicPublishRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TopicPublishResponse:
    published_topics, proposals, versions = publish_topics(db, payload.proposal_ids, None, payload.expected_versions, actor, payload.change_reason)
    return TopicPublishResponse(status="published", published_topic_ids=published_topics, published_proposal_ids=proposals, versions=versions)


@admin_router.get("/proposals/{proposal_id}/evidence", response_model=list[dict[str, Any]], dependencies=[Depends(require_admin)])
def proposal_evidence(proposal_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    proposal = db.scalar(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id == proposal_id))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Knowledge topic proposal was not found")
    return proposal_response(db, proposal)["source_references"]
