from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    CareerLevel,
    Competency,
    CompetencyCategory,
    Industry,
    KnowledgeTopic,
    KnowledgeTopicAudit,
    KnowledgeTopicCompetency,
    KnowledgeTopicDomain,
    KnowledgeTopicEvidence,
    KnowledgeTopicIndustry,
    KnowledgeTopicLevel,
    KnowledgeTopicProposal,
    KnowledgeTopicVersion,
    PublicationBatch,
    ResearchFinding,
    ResearchSource,
    SecurityDomain,
)
from .knowledge_topic_schemas import KnowledgeTopicDraft, KnowledgeTopicUpdate, TopicProposalReview


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")
    return slug or "knowledge-topic"


def topic_query():
    return select(KnowledgeTopic).options(
        selectinload(KnowledgeTopic.category),
        selectinload(KnowledgeTopic.parent),
        selectinload(KnowledgeTopic.domains).selectinload(KnowledgeTopicDomain.domain),
        selectinload(KnowledgeTopic.industries).selectinload(KnowledgeTopicIndustry.industry),
        selectinload(KnowledgeTopic.level_expectations).selectinload(KnowledgeTopicLevel.career_level),
        selectinload(KnowledgeTopic.level_expectations).selectinload(KnowledgeTopicLevel.industry),
        selectinload(KnowledgeTopic.competencies).selectinload(KnowledgeTopicCompetency.competency),
        selectinload(KnowledgeTopic.evidence).selectinload(KnowledgeTopicEvidence.source),
    )


def get_topic(db: Session, topic_id: int) -> KnowledgeTopic:
    topic = db.scalar(topic_query().where(KnowledgeTopic.id == topic_id))
    if topic is None:
        raise HTTPException(status_code=404, detail="Knowledge topic was not found")
    return topic


def _ref(item: Any | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"id": item.id, "name": item.name, "slug": item.slug}


def snapshot(topic: KnowledgeTopic) -> dict[str, Any]:
    return {
        "id": topic.id,
        "name": topic.name,
        "slug": topic.slug,
        "description": topic.description,
        "category_id": topic.category_id,
        "parent_topic_id": topic.parent_topic_id,
        "domain_ids": [link.domain_id for link in topic.domains],
        "industry_ids": [link.industry_id for link in topic.industries],
        "aliases": list(topic.aliases or []),
        "related_competency_ids": [link.competency_id for link in topic.competencies],
        "level_expectations": [
            {
                "career_level_id": item.career_level_id,
                "industry_id": item.industry_id,
                "expectation": item.expectation,
                "practical_capability": item.practical_capability,
                "display_order": item.display_order,
            }
            for item in sorted(topic.level_expectations, key=lambda row: (row.display_order, row.career_level_id, row.industry_id or 0))
        ],
        "display_order": topic.display_order,
        "publication_status": topic.publication_status,
        "is_active": topic.is_active,
        "version": topic.version,
    }


def response(topic: KnowledgeTopic) -> dict[str, Any]:
    return {
        "id": topic.id,
        "name": topic.name,
        "slug": topic.slug,
        "description": topic.description or "",
        "category": _ref(topic.category),
        "parent": _ref(topic.parent),
        "domains": [_ref(link.domain) for link in topic.domains if link.domain is not None],
        "industries": [_ref(link.industry) for link in topic.industries if link.industry is not None],
        "level_expectations": [
            {
                "id": item.id,
                "career_level": _ref(item.career_level),
                "industry": _ref(item.industry),
                "expectation": item.expectation,
                "practical_capability": item.practical_capability,
                "display_order": item.display_order,
            }
            for item in sorted(topic.level_expectations, key=lambda row: (row.display_order, row.career_level_id, row.industry_id or 0))
        ],
        "related_competencies": [_ref(link.competency) for link in topic.competencies if link.competency is not None],
        "aliases": list(topic.aliases or []),
        "publication_status": topic.publication_status,
        "is_active": topic.is_active,
        "version": topic.version,
        "display_order": topic.display_order,
        "evidence_count": len(topic.evidence),
        "supporting_evidence": [{"source_id": item.source_id, "source_title": item.source.source_title if item.source else None, "source_url": item.source.source_url if item.source else None, "excerpt": item.excerpt, "evidence_type": item.evidence_type, "confidence": item.confidence} for item in topic.evidence],
        "created_at": topic.created_at,
        "updated_at": topic.updated_at,
        "published_at": topic.published_at,
    }


def validate_ids(db: Session, draft: KnowledgeTopicDraft) -> None:
    if draft.category_id is not None:
        category = db.get(CompetencyCategory, draft.category_id)
        if category is None or not category.is_active:
            raise HTTPException(status_code=422, detail="A valid active competency category is required")
    for model, ids, label in (
        (SecurityDomain, draft.domain_ids, "domain"),
        (Industry, draft.industry_ids, "industry"),
        (Competency, draft.related_competency_ids, "related competency"),
    ):
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=422, detail=f"Duplicate {label} identifiers are not allowed")
        for identifier in ids:
            item = db.get(model, identifier)
            if item is None or (hasattr(item, "is_active") and not item.is_active):
                raise HTTPException(status_code=422, detail=f"A valid active {label} is required")
    for level in draft.level_expectations:
        career_level = db.get(CareerLevel, level.career_level_id)
        if career_level is None or not career_level.is_active:
            raise HTTPException(status_code=422, detail="A valid active career level is required")
        if level.industry_id is not None:
            industry = db.get(Industry, level.industry_id)
            if industry is None or not industry.is_active:
                raise HTTPException(status_code=422, detail="A valid active industry is required for the level expectation")
    if draft.parent_topic_id is not None:
        parent = db.get(KnowledgeTopic, draft.parent_topic_id)
        if parent is None or not parent.is_active:
            raise HTTPException(status_code=422, detail="A valid active parent topic is required")


def _validate_unique_name(db: Session, name: str, slug: str, topic_id: int | None = None) -> None:
    query = select(KnowledgeTopic).where(func.lower(KnowledgeTopic.name) == normalize(name))
    if topic_id is not None:
        query = query.where(KnowledgeTopic.id != topic_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=409, detail="A knowledge topic with this name already exists")
    query = select(KnowledgeTopic).where(KnowledgeTopic.slug == slug)
    if topic_id is not None:
        query = query.where(KnowledgeTopic.id != topic_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=409, detail="A knowledge topic with this slug already exists")


def _validate_parent_cycle(db: Session, topic_id: int, parent_id: int | None) -> None:
    current = parent_id
    seen: set[int] = set()
    while current is not None:
        if current == topic_id or current in seen:
            raise HTTPException(status_code=409, detail="Topic hierarchy cannot contain a cycle")
        seen.add(current)
        current = db.scalar(select(KnowledgeTopic.parent_topic_id).where(KnowledgeTopic.id == current))


def _write_relationships(db: Session, topic: KnowledgeTopic, draft: KnowledgeTopicDraft) -> None:
    topic.domains.clear()
    topic.industries.clear()
    topic.level_expectations.clear()
    topic.competencies.clear()
    db.flush()
    topic.domains.extend(KnowledgeTopicDomain(domain_id=item) for item in draft.domain_ids)
    topic.industries.extend(KnowledgeTopicIndustry(industry_id=item) for item in draft.industry_ids)
    topic.level_expectations.extend(KnowledgeTopicLevel(**item.model_dump()) for item in draft.level_expectations)
    topic.competencies.extend(KnowledgeTopicCompetency(competency_id=item) for item in draft.related_competency_ids)


def draft_from_snapshot(snapshot_data: dict[str, Any]) -> KnowledgeTopicDraft:
    return KnowledgeTopicDraft(
        name=snapshot_data.get("name", ""), slug=snapshot_data.get("slug"), description=snapshot_data.get("description", ""),
        category_id=snapshot_data.get("category_id"), parent_topic_id=snapshot_data.get("parent_topic_id"),
        domain_ids=snapshot_data.get("domain_ids", []), industry_ids=snapshot_data.get("industry_ids", []),
        aliases=snapshot_data.get("aliases", []), related_competency_ids=snapshot_data.get("related_competency_ids", []),
        level_expectations=snapshot_data.get("level_expectations", []), display_order=snapshot_data.get("display_order", 0),
    )


def _apply_draft(db: Session, topic: KnowledgeTopic, draft: KnowledgeTopicDraft) -> None:
    validate_ids(db, draft)
    if topic.id:
        _validate_parent_cycle(db, topic.id, draft.parent_topic_id)
    slug = slugify(draft.slug or draft.name)
    _validate_unique_name(db, draft.name, slug, topic.id)
    topic.name = draft.name.strip()
    topic.slug = slug
    topic.description = draft.description.strip()
    topic.category_id = draft.category_id
    topic.parent_topic_id = draft.parent_topic_id
    topic.aliases = sorted({alias.strip() for alias in draft.aliases if alias.strip()}, key=str.casefold)
    topic.display_order = draft.display_order
    _write_relationships(db, topic, draft)


def create_topic(db: Session, draft: KnowledgeTopicDraft, actor: str) -> KnowledgeTopic:
    _validate_unique_name(db, draft.name, slugify(draft.slug or draft.name))
    topic = KnowledgeTopic(name=draft.name.strip(), slug=slugify(draft.slug or draft.name), description=draft.description.strip(), category_id=draft.category_id, parent_topic_id=draft.parent_topic_id, aliases=list(draft.aliases), publication_status="draft", is_active=True, version=1, display_order=draft.display_order, created_at=now(), updated_at=now())
    db.add(topic)
    db.flush()
    _apply_draft(db, topic, draft)
    db.add(KnowledgeTopicAudit(topic_id=topic.id, action="created", actor=actor, after_snapshot=snapshot(topic), reason="Draft topic created by administrator."))
    db.commit()
    return get_topic(db, topic.id)


def update_topic(db: Session, topic_id: int, payload: KnowledgeTopicUpdate, actor: str) -> KnowledgeTopic:
    topic = get_topic(db, topic_id)
    if payload.expected_version != topic.version:
        raise HTTPException(status_code=409, detail="Topic changed; reload it before editing")
    data = snapshot(topic)
    updates = payload.model_dump(exclude_unset=True, exclude={"expected_version", "change_reason"})
    data.update({key: value for key, value in updates.items() if value is not None})
    draft = draft_from_snapshot(data)
    before = snapshot(topic)
    _apply_draft(db, topic, draft)
    if topic.publication_status == "published":
        topic.publication_status = "review"
    topic.version += 1
    topic.updated_at = now()
    db.add(KnowledgeTopicAudit(topic_id=topic.id, action="edited", actor=actor, before_snapshot=before, after_snapshot=snapshot(topic), reason=payload.change_reason))
    db.commit()
    return get_topic(db, topic.id)


def _source_references(db: Session, proposal: KnowledgeTopicProposal) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(KnowledgeTopicEvidence).where(KnowledgeTopicEvidence.proposal_id == proposal.id).options(selectinload(KnowledgeTopicEvidence.source))).all())
    return [{"source_id": row.source_id, "source_title": row.source.source_title if row.source else None, "source_url": row.source.source_url if row.source else None, "excerpt": row.excerpt, "evidence_type": row.evidence_type, "confidence": row.confidence} for row in rows]


def _potential_duplicates(db: Session, proposal: KnowledgeTopicProposal) -> list[dict[str, Any]]:
    name = normalize(proposal.proposed_snapshot.get("name", ""))
    if not name:
        return []
    topics = db.scalars(topic_query().where(KnowledgeTopic.is_active.is_(True), KnowledgeTopic.publication_status == "published")).unique().all()
    ranked = []
    for topic in topics:
        candidates = [topic.name, *(topic.aliases or [])]
        score = max(SequenceMatcher(None, name, normalize(candidate)).ratio() for candidate in candidates)
        if score >= 0.55 and (proposal.topic_id is None or topic.id != proposal.topic_id):
            ranked.append((score, response(topic)))
    return [item for _, item in sorted(ranked, key=lambda row: row[0], reverse=True)[:5]]


def proposal_response(db: Session, proposal: KnowledgeTopicProposal) -> dict[str, Any]:
    return {
        "id": proposal.id, "finding_id": proposal.finding_id, "topic_id": proposal.topic_id, "proposal_type": proposal.proposal_type,
        "status": proposal.status, "version": proposal.version, "original": proposal.original_snapshot, "proposed": proposal.proposed_snapshot,
        "ai_interpretation": proposal.ai_interpretation, "confidence": proposal.confidence, "evidence_status": proposal.evidence_status,
        "review_note": proposal.review_note, "reviewed_by": proposal.reviewed_by, "reviewed_at": proposal.reviewed_at,
        "published_at": proposal.published_at, "created_at": proposal.created_at, "updated_at": proposal.updated_at,
        "source_references": _source_references(db, proposal), "potential_duplicates": _potential_duplicates(db, proposal),
    }


def _proposal_query():
    return select(KnowledgeTopicProposal).options(selectinload(KnowledgeTopicProposal.topic))


def ensure_topic_proposal(db: Session, finding: ResearchFinding) -> KnowledgeTopicProposal | None:
    existing = db.scalar(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.finding_id == finding.id))
    if existing is not None:
        return existing
    candidate_name = (finding.normalized_name or finding.candidate_name or "").strip()
    if not candidate_name:
        return None
    topics = db.scalars(topic_query().where(KnowledgeTopic.publication_status == "published", KnowledgeTopic.is_active.is_(True))).unique().all()
    matching = next((topic for topic in topics if normalize(topic.name) == normalize(candidate_name) or any(normalize(alias) == normalize(candidate_name) for alias in (topic.aliases or []))), None)
    domain_ids = [link.domain_id for link in finding.domains] or ([finding.domain_id] if finding.domain_id else [])
    industry_ids = [link.industry_id for link in finding.industries] or ([finding.primary_industry_id] if finding.primary_industry_id else [])
    level_expectations = []
    if finding.career_level_id:
        level_expectations.append({"career_level_id": finding.career_level_id, "industry_id": finding.primary_industry_id, "expectation": finding.practical_capability or finding.responsibilities or finding.technical_knowledge, "practical_capability": finding.practical_capability or finding.responsibilities, "display_order": 0})
    if matching:
        before = snapshot(matching)
        proposed = deepcopy(before)
        proposed["domain_ids"] = sorted(set(proposed.get("domain_ids", []) + domain_ids))
        proposed["industry_ids"] = sorted(set(proposed.get("industry_ids", []) + industry_ids))
        if level_expectations:
            existing_levels = {(item["career_level_id"], item.get("industry_id")) for item in proposed.get("level_expectations", [])}
            for item in level_expectations:
                if (item["career_level_id"], item.get("industry_id")) not in existing_levels:
                    proposed.setdefault("level_expectations", []).append(item)
        proposal_type = "evidence_update" if proposed == before else "topic_update"
        original_snapshot = before
        topic_id = matching.id
    else:
        proposed = {"name": candidate_name, "slug": slugify(candidate_name), "description": finding.technical_knowledge or finding.practical_capability or f"Understand {candidate_name}.", "category_id": finding.category_id, "parent_topic_id": None, "domain_ids": domain_ids, "industry_ids": industry_ids, "aliases": [], "related_competency_ids": [finding.competency_id] if finding.competency_id else [], "level_expectations": level_expectations, "display_order": 0}
        proposal_type = "new_topic"
        original_snapshot = None
        topic_id = None
    source_id = finding.submission.source_id if finding.submission else None
    fingerprint = hashlib.sha256(f"{finding.id}:{proposal_type}:{source_id}:{candidate_name.casefold()}".encode()).hexdigest()
    proposal = KnowledgeTopicProposal(
        finding_id=finding.id, topic_id=topic_id, proposal_type=proposal_type, status="review", fingerprint=fingerprint,
        original_snapshot=original_snapshot, proposed_snapshot=proposed,
        ai_interpretation="Mapped from analyzed research; the administrator must confirm whether the evidence is explicit or AI-derived.",
        confidence=finding.confidence, evidence_status="explicitly_supported" if finding.evidence_excerpt and finding.confidence and finding.confidence >= 0.8 else "ai-derived",
        version=1, created_at=now(), updated_at=now(),
    )
    db.add(proposal)
    db.flush()
    if source_id and finding.evidence_excerpt:
        db.add(KnowledgeTopicEvidence(topic_id=topic_id, source_id=source_id, proposal_id=proposal.id, excerpt=finding.evidence_excerpt, evidence_type="supporting", confidence=finding.confidence))
    db.add(KnowledgeTopicAudit(topic_id=topic_id, proposal_id=proposal.id, action="proposal_created", actor="system", before_snapshot=original_snapshot, after_snapshot=proposed, reason="Generated from analyzed research finding."))
    return proposal


def ensure_all_topic_proposals(db: Session, *, commit: bool = True) -> list[KnowledgeTopicProposal]:
    findings = list(db.scalars(select(ResearchFinding).options(selectinload(ResearchFinding.domains), selectinload(ResearchFinding.industries), selectinload(ResearchFinding.submission))).all())
    proposals = [proposal for finding in findings if (proposal := ensure_topic_proposal(db, finding)) is not None]
    if commit:
        db.commit()
    return proposals


def review_proposal(db: Session, proposal_id: int, payload: TopicProposalReview, actor: str) -> KnowledgeTopicProposal:
    proposal = db.scalar(_proposal_query().where(KnowledgeTopicProposal.id == proposal_id))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Knowledge topic proposal was not found")
    if payload.expected_version != proposal.version:
        raise HTTPException(status_code=409, detail="Proposal changed; reload it before reviewing")
    before = deepcopy(proposal.proposed_snapshot)
    if payload.action == "modify":
        proposal.proposed_snapshot = payload.proposal.model_dump(exclude_none=True)
        proposal.status = "approved"
    elif payload.action == "merge":
        target = get_topic(db, payload.target_topic_id)
        if target.publication_status != "published" or not target.is_active:
            raise HTTPException(status_code=409, detail="Merge target must be an active published topic")
        proposal.proposed_snapshot = {**proposal.proposed_snapshot, "target_topic_id": target.id, "name": target.name, "slug": target.slug, "category_id": target.category_id}
        proposal.status = "approved"
    elif payload.action == "accept":
        proposal.status = "approved"
    elif payload.action == "reject":
        proposal.status = "rejected"
    else:
        proposal.status = "deferred"
    proposal.version += 1
    proposal.review_note = payload.reviewer_note
    proposal.reviewed_by = actor
    proposal.reviewed_at = now()
    proposal.updated_at = now()
    db.add(KnowledgeTopicAudit(topic_id=proposal.topic_id, proposal_id=proposal.id, action=f"proposal_{payload.action}", actor=actor, before_snapshot=before, after_snapshot=proposal.proposed_snapshot, reason=payload.reviewer_note or ""))
    db.commit()
    return db.scalar(_proposal_query().where(KnowledgeTopicProposal.id == proposal_id))


def _replace_evidence(db: Session, topic: KnowledgeTopic, proposal: KnowledgeTopicProposal) -> None:
    for item in _source_references(db, proposal):
        if not item["source_id"] or not item["excerpt"]:
            continue
        duplicate = db.scalar(select(KnowledgeTopicEvidence).where(KnowledgeTopicEvidence.topic_id == topic.id, KnowledgeTopicEvidence.source_id == item["source_id"], KnowledgeTopicEvidence.excerpt == item["excerpt"]))
        if duplicate is None:
            db.add(KnowledgeTopicEvidence(topic_id=topic.id, source_id=item["source_id"], proposal_id=proposal.id, excerpt=item["excerpt"], evidence_type=item["evidence_type"], confidence=item["confidence"]))


def _publish_topic(db: Session, topic: KnowledgeTopic, data: dict[str, Any], actor: str, reason: str, source_id: int | None = None) -> None:
    before = snapshot(topic)
    draft = draft_from_snapshot(data)
    _apply_draft(db, topic, draft)
    topic.publication_status = "published"
    topic.is_active = True
    topic.version += 1
    topic.published_at = now()
    topic.updated_at = now()
    db.add(KnowledgeTopicVersion(topic_id=topic.id, version=topic.version, snapshot=snapshot(topic), reason=reason, source_id=source_id, actor=actor, published_at=now()))
    db.add(KnowledgeTopicAudit(topic_id=topic.id, action="published", actor=actor, before_snapshot=before, after_snapshot=snapshot(topic), reason=reason))


def publish_topics(db: Session, proposal_ids: list[int] | None, topic_ids: list[int] | None, expected_versions: dict[int, int], actor: str, reason: str) -> tuple[list[int], list[int], dict[int, int]]:
    proposals = list(db.scalars(_proposal_query().where(KnowledgeTopicProposal.id.in_(proposal_ids))).all()) if proposal_ids else []
    topics = [get_topic(db, item) for item in (topic_ids or [])]
    if not proposals and not topics:
        raise HTTPException(status_code=409, detail="No topic changes were selected")
    for proposal in proposals:
        if proposal.status != "approved":
            raise HTTPException(status_code=409, detail=f"Proposal {proposal.id} is not approved")
        if expected_versions.get(proposal.id) != proposal.version:
            raise HTTPException(status_code=409, detail=f"Proposal {proposal.id} changed; refresh before publishing")
    for topic in topics:
        if expected_versions.get(topic.id) != topic.version:
            raise HTTPException(status_code=409, detail=f"Topic {topic.id} changed; refresh before publishing")
    batch = PublicationBatch(status="pending", created_by=actor, created_at=now())
    db.add(batch)
    db.flush()
    published_topics: list[int] = []
    versions: dict[int, int] = {}
    for topic in topics:
        _publish_topic(db, topic, snapshot(topic), actor, reason or "Administrator published topic draft.")
        published_topics.append(topic.id)
        versions[topic.id] = topic.version
    for proposal in proposals:
        data = proposal.proposed_snapshot
        if proposal.proposal_type == "new_topic" and proposal.topic_id is None:
            draft = draft_from_snapshot(data)
            topic = KnowledgeTopic(name=draft.name.strip(), slug=slugify(draft.slug or draft.name), description=draft.description.strip(), category_id=draft.category_id, parent_topic_id=draft.parent_topic_id, aliases=list(draft.aliases), publication_status="draft", is_active=True, version=1, display_order=draft.display_order, created_at=now(), updated_at=now())
            db.add(topic)
            db.flush()
            _apply_draft(db, topic, draft)
            proposal.topic_id = topic.id
        topic = get_topic(db, proposal.topic_id)
        target_id = data.get("target_topic_id")
        if target_id:
            target = get_topic(db, target_id)
            merged_before = snapshot(target)
            merged_data = snapshot(target)
            merged_data["domain_ids"] = sorted(set(merged_data.get("domain_ids", []) + data.get("domain_ids", [])))
            merged_data["industry_ids"] = sorted(set(merged_data.get("industry_ids", []) + data.get("industry_ids", [])))
            merged_data["aliases"] = sorted(set(merged_data.get("aliases", []) + [data.get("name", "")] + data.get("aliases", [])), key=str.casefold)
            merged_data["related_competency_ids"] = sorted(set(merged_data.get("related_competency_ids", []) + data.get("related_competency_ids", [])))
            existing_levels = {(item.get("career_level_id"), item.get("industry_id")) for item in merged_data.get("level_expectations", [])}
            merged_data["level_expectations"] = list(merged_data.get("level_expectations", [])) + [item for item in data.get("level_expectations", []) if (item.get("career_level_id"), item.get("industry_id")) not in existing_levels]
            _publish_topic(db, target, merged_data, actor, reason or "Approved topic merge.")
            for evidence in list(topic.evidence):
                evidence.topic_id = target.id
            topic.is_active = False
            topic.publication_status = "published"
            db.add(KnowledgeTopicAudit(topic_id=target.id, proposal_id=proposal.id, action="merged", actor=actor, before_snapshot=merged_before, after_snapshot=snapshot(target), reason=reason))
            published_topics.append(target.id)
            versions[target.id] = target.version
        else:
            _publish_topic(db, topic, data, actor, reason or "Approved research topic update.", next((item["source_id"] for item in _source_references(db, proposal) if item.get("source_id")), None))
            published_topics.append(topic.id)
            versions[topic.id] = topic.version
        _replace_evidence(db, get_topic(db, target_id) if target_id else topic, proposal)
        proposal.status = "published"
        proposal.published_at = now()
        proposal.updated_at = now()
        db.add(KnowledgeTopicAudit(topic_id=proposal.topic_id, proposal_id=proposal.id, action="proposal_published", actor=actor, before_snapshot=proposal.original_snapshot, after_snapshot=proposal.proposed_snapshot, reason=reason))
    batch.status = "published"
    batch.published_at = now()
    db.commit()
    return sorted(set(published_topics)), [proposal.id for proposal in proposals], versions


def set_topic_active(db: Session, topic_id: int, active: bool, actor: str) -> KnowledgeTopic:
    topic = get_topic(db, topic_id)
    before = snapshot(topic)
    topic.is_active = active
    topic.updated_at = now()
    db.add(KnowledgeTopicAudit(topic_id=topic.id, action="reactivated" if active else "deactivated", actor=actor, before_snapshot=before, after_snapshot=snapshot(topic), reason="Administrator lifecycle change."))
    db.commit()
    return get_topic(db, topic.id)


def merge_topic(db: Session, topic_id: int, target_id: int, actor: str, reason: str) -> KnowledgeTopic:
    source = get_topic(db, topic_id)
    target = get_topic(db, target_id)
    if source.id == target.id or not source.is_active or not target.is_active:
        raise HTTPException(status_code=409, detail="Merge requires two different active topics")
    before = snapshot(target)
    data = snapshot(target)
    source_data = snapshot(source)
    data["domain_ids"] = sorted(set(data["domain_ids"] + source_data["domain_ids"]))
    data["industry_ids"] = sorted(set(data["industry_ids"] + source_data["industry_ids"]))
    data["aliases"] = sorted(set(data["aliases"] + [source.name] + source_data["aliases"]), key=str.casefold)
    data["related_competency_ids"] = sorted(set(data["related_competency_ids"] + source_data["related_competency_ids"]))
    existing_levels = {(item.get("career_level_id"), item.get("industry_id")) for item in data["level_expectations"]}
    data["level_expectations"] += [item for item in source_data["level_expectations"] if (item.get("career_level_id"), item.get("industry_id")) not in existing_levels]
    for evidence in list(source.evidence):
        evidence.topic_id = target.id
    _publish_topic(db, target, data, actor, reason or "Administrator merged duplicate topic.")
    source.is_active = False
    db.add(KnowledgeTopicAudit(topic_id=source.id, action="merged", actor=actor, before_snapshot=snapshot(source), after_snapshot=snapshot(source), reason=reason))
    db.add(KnowledgeTopicAudit(topic_id=target.id, action="merge_target", actor=actor, before_snapshot=before, after_snapshot=snapshot(target), reason=reason))
    db.commit()
    return get_topic(db, target.id)


def history(db: Session, topic_id: int) -> list[dict[str, Any]]:
    audits = list(db.scalars(select(KnowledgeTopicAudit).where(KnowledgeTopicAudit.topic_id == topic_id).order_by(KnowledgeTopicAudit.created_at.desc())).all())
    versions = list(db.scalars(select(KnowledgeTopicVersion).where(KnowledgeTopicVersion.topic_id == topic_id).order_by(KnowledgeTopicVersion.version.desc())).all())
    return [{"kind": "audit", "id": item.id, "action": item.action, "actor": item.actor, "before": item.before_snapshot, "after": item.after_snapshot, "reason": item.reason, "created_at": item.created_at} for item in audits] + [{"kind": "version", "id": item.id, "version": item.version, "snapshot": item.snapshot, "actor": item.actor, "reason": item.reason, "created_at": item.published_at} for item in versions]
