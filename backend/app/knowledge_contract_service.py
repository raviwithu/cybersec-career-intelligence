from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .knowledge_contract_schemas import SECTION_TYPES, KnowledgeProposalCreate, KnowledgeProposalReview, KnowledgeSourceReference
from .models import (
    KnowledgePublicationRecord,
    KnowledgeProposalSource,
    KnowledgeReviewDecision,
    KnowledgeTopic,
    KnowledgeTopicProposal,
    KnowledgeTopicRelationship,
    KnowledgeTopicSection,
    KnowledgeTopicSectionVersion,
    SecurityDomain,
    Industry,
    CompetencyCategory,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "knowledge-topic"


def _topic_key(topic: KnowledgeTopic) -> str:
    return topic.topic_key or topic.slug


def _section_type(section: str | None) -> str | None:
    return section if section in SECTION_TYPES else None


def _topic_query():
    return select(KnowledgeTopic).options(
        selectinload(KnowledgeTopic.sections).selectinload(KnowledgeTopicSection.versions),
        selectinload(KnowledgeTopic.relationships_from).selectinload(KnowledgeTopicRelationship.target_topic),
        selectinload(KnowledgeTopic.relationships_to).selectinload(KnowledgeTopicRelationship.source_topic),
    )


def resolve_topic(db: Session, topic_id: int | None, topic_key: str | None, *, require_active: bool = True) -> KnowledgeTopic | None:
    query = _topic_query()
    if topic_id is not None:
        topic = db.scalar(query.where(KnowledgeTopic.id == topic_id))
    elif topic_key:
        topic = db.scalar(query.where((KnowledgeTopic.topic_key == topic_key) | (KnowledgeTopic.slug == topic_key)))
    else:
        topic = None
    if topic is not None and require_active and not topic.is_active:
        raise HTTPException(status_code=409, detail="The knowledge topic is inactive")
    return topic


def _section(topic: KnowledgeTopic | None, section_type: str | None) -> KnowledgeTopicSection | None:
    if topic is None or not section_type:
        return None
    return next((item for item in topic.sections if item.section_type == section_type), None)


def _public_content(section_type: str, content: dict[str, Any]) -> dict[str, Any]:
    content = deepcopy(content or {})
    if section_type == "references":
        items = content.get("items", [])
        content["items"] = [item for item in items if not item.get("is_private") and item.get("access_scope", "public") == "public"]
    return content


def _section_response(section: KnowledgeTopicSection, *, include_history: bool) -> dict[str, Any]:
    return {
        "section_type": section.section_type,
        "status": section.status,
        "published_version": section.published_version,
        "content": _public_content(section.section_type, section.published_content) if not include_history else section.published_content,
        "updated_at": section.updated_at,
        "versions": [
            {
                "version": item.version,
                "status": item.status,
                "content": item.content,
                "reason": item.reason,
                "actor": item.actor,
                "created_at": item.created_at,
                "published_at": item.published_at,
            }
            for item in sorted(section.versions, key=lambda row: row.version, reverse=True)
        ] if include_history else [],
    }


def coverage(db: Session, topic: KnowledgeTopic, *, include_pending: bool = False) -> dict[str, Any]:
    pending: dict[str, str] = {}
    if include_pending:
        rows = db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.topic_id == topic.id, KnowledgeTopicProposal.section_type.is_not(None))).all()
        for row in rows:
            if row.section_type and row.status in {"draft", "review", "deferred", "approved"}:
                pending[row.section_type] = "pending_review" if row.status != "draft" else "draft"
    items = []
    for section_type in SECTION_TYPES:
        section = _section(topic, section_type)
        if section is not None and section.status == "published":
            items.append({"section_type": section_type, "status": "published", "published_version": section.published_version})
        else:
            items.append({"section_type": section_type, "status": pending.get(section_type, "missing"), "published_version": 0})
    return {"topic_id": topic.id, "topic_key": _topic_key(topic), "items": items, "complete": all(item["status"] == "published" for item in items)}


def public_topic(db: Session, topic: KnowledgeTopic) -> dict[str, Any]:
    return {
        "id": topic.id,
        "topic_key": _topic_key(topic),
        "name": topic.name,
        "slug": topic.slug,
        "description": topic.description or "",
        "sections": [_section_response(item, include_history=False) for item in sorted(topic.sections, key=lambda row: SECTION_TYPES.index(row.section_type) if row.section_type in SECTION_TYPES else 99) if item.status == "published"],
        "coverage": coverage(db, topic),
        "related_topics": [
            {"id": item.target_topic.id, "topic_key": _topic_key(item.target_topic), "name": item.target_topic.name, "relationship_type": item.relationship_type}
            for item in topic.relationships_from if item.target_topic and item.target_topic.is_active and item.target_topic.publication_status == "published"
        ],
        "last_updated": topic.published_at or topic.updated_at,
    }


def admin_topic(db: Session, topic: KnowledgeTopic) -> dict[str, Any]:
    value = public_topic(db, topic)
    value["sections"] = [_section_response(item, include_history=True) for item in sorted(topic.sections, key=lambda row: SECTION_TYPES.index(row.section_type) if row.section_type in SECTION_TYPES else 99)]
    value["coverage"] = coverage(db, topic, include_pending=True)
    return value


def _validate_topic_metadata(db: Session, content: dict[str, Any]) -> None:
    metadata = content.get("topic", content)
    for model, key, label in ((SecurityDomain, "domain_ids", "domain"), (Industry, "industry_ids", "industry"), (CompetencyCategory, "category_id", "category")):
        values = metadata.get(key, []) if key.endswith("_ids") else ([metadata[key]] if metadata.get(key) else [])
        for identifier in values:
            item = db.get(model, identifier)
            if item is None or (hasattr(item, "is_active") and not item.is_active):
                raise HTTPException(status_code=422, detail=f"A valid active {label} is required")


def _content_for_action(topic: KnowledgeTopic | None, section_type: str | None, action: str, proposed: dict[str, Any]) -> dict[str, Any]:
    current = deepcopy((_section(topic, section_type).published_content if _section(topic, section_type) else {}) or {})
    if action in {"ADD_ATTACK_SURFACE", "ADD_MITIGATION", "ADD_REFERENCE", "ADD_VULNERABILITY_EXAMPLE"}:
        items = list(current.get("items", []))
        item = proposed.get("item", proposed)
        if item not in items:
            items.append(item)
        return {**current, "items": items}
    if action == "ADD_DIAGRAM":
        return {**current, "diagram": proposed.get("diagram", proposed)}
    if action == "UPDATE_CAREER_LEVEL_GUIDANCE":
        levels = {**current.get("levels", {}), **proposed.get("levels", proposed)}
        return {**current, "levels": levels}
    return deepcopy(proposed)


def _fingerprint(payload: KnowledgeProposalCreate, idempotency_key: str | None) -> str:
    raw = idempotency_key or json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return f"knowledge-proposal:{hashlib.sha256(raw.encode()).hexdigest()}"


def create_proposal(db: Session, payload: KnowledgeProposalCreate, actor: str, idempotency_key: str | None = None) -> KnowledgeTopicProposal:
    fingerprint = _fingerprint(payload, idempotency_key)
    existing = db.scalar(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.idempotency_key == fingerprint))
    if existing:
        return existing
    topic = resolve_topic(db, payload.topic_id, payload.topic_key)
    section_type = _section_type(payload.section)
    if payload.action != "CREATE_TOPIC" and topic is None:
        raise HTTPException(status_code=404, detail="Knowledge topic was not found")
    if payload.action != "ADD_TOPIC_RELATIONSHIP" and payload.action != "CREATE_TOPIC" and section_type is None:
        raise HTTPException(status_code=422, detail="A valid section is required for this action")
    if payload.action == "CREATE_TOPIC":
        name = payload.topic_name or payload.proposed_content.get("topic", {}).get("name") or payload.proposed_content.get("name")
        if not name:
            raise HTTPException(status_code=422, detail="topic_name or proposed_content.topic.name is required for CREATE_TOPIC")
        topic_key = payload.topic_key or slugify(name)
        if db.scalar(select(KnowledgeTopic).where((KnowledgeTopic.topic_key == topic_key) | (KnowledgeTopic.slug == topic_key))):
            raise HTTPException(status_code=409, detail="A knowledge topic with this stable key already exists")
        original = None
        base_version = 0
    elif payload.action == "ADD_TOPIC_RELATIONSHIP":
        original = None
        base_version = topic.version
        section_type = None
    else:
        current_section = _section(topic, section_type)
        original = deepcopy(current_section.published_content) if current_section else None
        base_version = current_section.published_version if current_section else 0
    if payload.action in {"ADD_SECTION", "UPDATE_SECTION", "ADD_ATTACK_SURFACE", "ADD_MITIGATION", "ADD_DIAGRAM", "ADD_REFERENCE", "ADD_VULNERABILITY_EXAMPLE", "UPDATE_CAREER_LEVEL_GUIDANCE"}:
        proposed_content = deepcopy(payload.proposed_content)
    else:
        proposed_content = deepcopy(payload.proposed_content)
    if payload.action == "CREATE_TOPIC":
        proposed_content = {**proposed_content, "topic": {**proposed_content.get("topic", {}), "name": name, "topic_key": topic_key}}
    if payload.action in {"ADD_TOPIC_RELATIONSHIP"}:
        target_id = proposed_content.get("target_topic_id")
        target = resolve_topic(db, int(target_id) if target_id else None, None)
        if target is None:
            raise HTTPException(status_code=404, detail="Relationship target topic was not found")
        if target.id == topic.id:
            raise HTTPException(status_code=422, detail="A topic cannot relate to itself")
    _validate_topic_metadata(db, proposed_content) if payload.action == "CREATE_TOPIC" else None
    proposal = KnowledgeTopicProposal(
        finding_id=None,
        topic_id=topic.id if topic else None,
        proposal_type=payload.action.lower(),
        status="review" if payload.submit_for_review else "draft",
        fingerprint=fingerprint,
        original_snapshot=original,
        proposed_snapshot=proposed_content,
        schema_version=payload.schema_version,
        action=payload.action,
        section_type=section_type,
        source_type=payload.source_type,
        idempotency_key=fingerprint,
        base_section_version=base_version,
        original_content=original,
        proposed_content=proposed_content,
        change_reason=payload.change_reason,
        version=1,
        created_at=now(),
        updated_at=now(),
    )
    db.add(proposal)
    db.flush()
    for reference in payload.references:
        db.add(KnowledgeProposalSource(proposal_id=proposal.id, **_source_values(reference)))
    db.add(KnowledgeReviewDecision(proposal_id=proposal.id, action="submitted", actor=actor, note=payload.change_reason, before_content=original, after_content=proposed_content, created_at=now()))
    db.commit()
    return get_proposal(db, proposal.id)


def _source_values(reference: KnowledgeSourceReference) -> dict[str, Any]:
    data = reference.model_dump()
    data["source_title"] = data.pop("title")
    data["source_url"] = data.pop("url")
    data["metadata_payload"] = data.pop("metadata")
    return data


def get_proposal(db: Session, proposal_id: int) -> KnowledgeTopicProposal:
    proposal = db.scalar(select(KnowledgeTopicProposal).options(selectinload(KnowledgeTopicProposal.sources), selectinload(KnowledgeTopicProposal.decisions)).where(KnowledgeTopicProposal.id == proposal_id))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Knowledge proposal was not found")
    return proposal


def proposal_response(proposal: KnowledgeTopicProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "schema_version": proposal.schema_version,
        "source_type": proposal.source_type,
        "topic_id": proposal.topic_id,
        "topic_key": _topic_key(proposal.topic) if proposal.topic else proposal.proposed_content.get("topic", {}).get("topic_key"),
        "action": proposal.action,
        "section": proposal.section_type,
        "status": proposal.status,
        "version": proposal.version,
        "base_section_version": proposal.base_section_version,
        "original_content": proposal.original_content,
        "proposed_content": proposal.proposed_content or proposal.proposed_snapshot,
        "change_reason": proposal.change_reason,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at,
        "published_at": proposal.published_at,
        "references": [_reference_response(item) for item in proposal.sources],
        "review_decisions": [{"id": item.id, "action": item.action, "actor": item.actor, "note": item.note, "before_content": item.before_content, "after_content": item.after_content, "created_at": item.created_at} for item in proposal.decisions],
    }


def _reference_response(item: KnowledgeProposalSource) -> dict[str, Any]:
    return {
        "id": item.id, "source_type": item.source_type, "document_identifier": item.document_identifier,
        "title": item.source_title, "author": item.author, "publisher": item.publisher, "url": item.source_url,
        "document_version": item.document_version, "publication_date": item.publication_date, "retrieved_at": item.retrieved_at,
        "locator": item.locator, "excerpt": item.excerpt, "content_hash": item.content_hash,
        "verification_status": item.verification_status, "access_scope": item.access_scope, "is_private": item.is_private,
    }


def review_proposal(db: Session, proposal_id: int, payload: KnowledgeProposalReview, actor: str) -> KnowledgeTopicProposal:
    proposal = get_proposal(db, proposal_id)
    if proposal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Proposal changed; reload it before reviewing")
    if proposal.status not in {"review", "deferred", "draft"}:
        raise HTTPException(status_code=409, detail="Only reviewable proposals can be acted on")
    before = deepcopy(proposal.proposed_content or proposal.proposed_snapshot)
    if payload.verified_source_ids:
        source_ids = set(payload.verified_source_ids)
        proposal_sources = {source.id: source for source in proposal.sources}
        if not source_ids.issubset(proposal_sources):
            raise HTTPException(status_code=422, detail="A source verification request referenced another proposal")
        for source_id in source_ids:
            proposal_sources[source_id].verification_status = "verified"
    if payload.action == "modify":
        proposal.proposed_content = payload.proposed_content
        proposal.proposed_snapshot = payload.proposed_content
        proposal.status = "review"
    elif payload.action == "approve":
        proposal.status = "approved"
    elif payload.action == "merge":
        target = resolve_topic(db, payload.merge_target_topic_id, None)
        if target is None or not target.is_active or target.publication_status != "published":
            raise HTTPException(status_code=409, detail="Merge target must be an active published topic")
        proposal.proposed_content = {**(proposal.proposed_content or {}), "merge_target_topic_id": target.id}
        proposal.proposed_snapshot = proposal.proposed_content
        proposal.status = "approved"
    elif payload.action == "reject":
        proposal.status = "rejected"
    else:
        proposal.status = "deferred"
    proposal.version += 1
    proposal.reviewed_by = actor
    proposal.reviewed_at = now()
    proposal.updated_at = now()
    proposal.change_reason = payload.reviewer_note or proposal.change_reason
    db.add(KnowledgeReviewDecision(proposal_id=proposal.id, action=payload.action, actor=actor, note=payload.reviewer_note, before_content=before, after_content=proposal.proposed_content, created_at=now()))
    db.commit()
    return get_proposal(db, proposal.id)


def _contains_cve(value: Any) -> bool:
    if isinstance(value, dict):
        return any(("cve" in str(key).casefold() and bool(child)) or _contains_cve(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_cve(child) for child in value)
    return False


def _ensure_sources_publishable(proposal: KnowledgeTopicProposal) -> None:
    if any(item.is_private or item.access_scope != "public" for item in proposal.sources):
        # Private sources can support a proposal, but their content cannot be
        # copied into a public section; the reviewer must remove those claims.
        if _contains_cve(proposal.proposed_content):
            raise HTTPException(status_code=409, detail="Private or restricted sources cannot verify a public CVE claim")
    if (proposal.action == "ADD_VULNERABILITY_EXAMPLE" or _contains_cve(proposal.proposed_content)) and not any(item.verification_status in {"verified", "authoritative"} for item in proposal.sources):
        raise HTTPException(status_code=409, detail="Vulnerability examples and CVE identifiers require a verified or authoritative supporting source")


def _create_topic(db: Session, proposal: KnowledgeTopicProposal, actor: str) -> KnowledgeTopic:
    data = proposal.proposed_content or {}
    metadata = data.get("topic", {})
    name = metadata.get("name") or data.get("name")
    key = metadata.get("topic_key") or slugify(name or "knowledge-topic")
    if not name:
        raise HTTPException(status_code=422, detail="CREATE_TOPIC is missing a topic name")
    if db.scalar(select(KnowledgeTopic).where((KnowledgeTopic.topic_key == key) | (KnowledgeTopic.slug == key))):
        raise HTTPException(status_code=409, detail="A knowledge topic with this stable key already exists")
    topic = KnowledgeTopic(name=name, slug=slugify(metadata.get("slug") or key), topic_key=key, description=metadata.get("description", ""), category_id=metadata.get("category_id"), publication_status="draft", is_active=True, version=1, display_order=metadata.get("display_order", 0), created_at=now(), updated_at=now())
    db.add(topic)
    db.flush()
    return topic


def publish_proposal(db: Session, proposal_id: int, expected_version: int, actor: str, change_reason: str) -> KnowledgeTopicProposal:
    proposal = get_proposal(db, proposal_id)
    if proposal.version != expected_version:
        raise HTTPException(status_code=409, detail="Proposal changed; reload it before publishing")
    if proposal.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved proposals can be published")
    _ensure_sources_publishable(proposal)
    topic = resolve_topic(db, proposal.topic_id, None) if proposal.topic_id else None
    if proposal.action == "CREATE_TOPIC":
        topic = _create_topic(db, proposal, actor)
        proposal.topic_id = topic.id
    if topic is None:
        raise HTTPException(status_code=404, detail="Knowledge topic was not found")
    if proposal.section_type:
        section = _section(topic, proposal.section_type)
        current_version = section.published_version if section else 0
        if current_version != proposal.base_section_version:
            raise HTTPException(status_code=409, detail="Section changed; reload and create a new proposal")
        content = _content_for_action(topic, proposal.section_type, proposal.action, proposal.proposed_content or proposal.proposed_snapshot)
        if section is None:
            section = KnowledgeTopicSection(topic_id=topic.id, section_type=proposal.section_type, published_content=content, published_version=1, status="published", updated_at=now())
            db.add(section)
            db.flush()
            version = 1
        else:
            version = current_version + 1
            section.published_content = content
            section.published_version = version
            section.status = "published"
            section.updated_at = now()
        db.add(KnowledgeTopicSectionVersion(section_id=section.id, version=version, content=content, status="published", proposal_id=proposal.id, reason=change_reason or proposal.change_reason, actor=actor, created_at=now(), published_at=now()))
        db.add(KnowledgePublicationRecord(proposal_id=proposal.id, topic_id=topic.id, section_id=section.id, published_version=version, previous_version=current_version, actor=actor, transaction_id=str(uuid.uuid4()), published_at=now()))
    elif proposal.action == "ADD_TOPIC_RELATIONSHIP":
        target_id = proposal.proposed_content.get("target_topic_id")
        target = resolve_topic(db, int(target_id), None)
        if db.scalar(select(KnowledgeTopicRelationship).where(KnowledgeTopicRelationship.source_topic_id == topic.id, KnowledgeTopicRelationship.target_topic_id == target.id, KnowledgeTopicRelationship.relationship_type == proposal.proposed_content.get("relationship_type", "related"))) is None:
            db.add(KnowledgeTopicRelationship(source_topic_id=topic.id, target_topic_id=target.id, relationship_type=proposal.proposed_content.get("relationship_type", "related"), created_at=now()))
    elif proposal.action == "UPDATE_TOPIC":
        metadata = proposal.proposed_content
        for key in ("name", "description", "category_id", "display_order"):
            if key in metadata:
                setattr(topic, key, metadata[key])
        if "slug" in metadata:
            topic.slug = slugify(metadata["slug"])
    topic.publication_status = "published"
    topic.is_active = True
    topic.version += 1
    topic.published_at = now()
    topic.updated_at = now()
    proposal.status = "published"
    proposal.published_at = now()
    proposal.updated_at = now()
    db.add(KnowledgeReviewDecision(proposal_id=proposal.id, action="publish", actor=actor, note=change_reason, before_content=proposal.original_content, after_content=proposal.proposed_content, created_at=now()))
    db.commit()
    return get_proposal(db, proposal.id)


def list_public_topics(db: Session, search: str | None = None) -> list[KnowledgeTopic]:
    query = _topic_query().where(KnowledgeTopic.publication_status == "published", KnowledgeTopic.is_active.is_(True))
    if search:
        query = query.where(KnowledgeTopic.name.ilike(f"%{search.strip()}%"))
    return list(db.scalars(query.order_by(KnowledgeTopic.display_order, KnowledgeTopic.name)).unique().all())


def list_proposals(db: Session, filters: dict[str, Any]) -> list[KnowledgeTopicProposal]:
    query = select(KnowledgeTopicProposal).options(selectinload(KnowledgeTopicProposal.topic), selectinload(KnowledgeTopicProposal.sources), selectinload(KnowledgeTopicProposal.decisions)).order_by(KnowledgeTopicProposal.created_at.desc())
    for key, column in (("source_type", KnowledgeTopicProposal.source_type), ("action", KnowledgeTopicProposal.action), ("status", KnowledgeTopicProposal.status), ("topic_id", KnowledgeTopicProposal.topic_id)):
        value = filters.get(key)
        if value:
            query = query.where(column == value)
    return list(db.scalars(query).unique().all())
