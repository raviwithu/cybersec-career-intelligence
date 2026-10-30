from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.orm import Session

from .models import MAP_BRANCHES, KnowledgeTopic, KnowledgeTopicDomain, KnowledgeTopicSection, KnowledgeTopicSectionVersion, SecurityDomain

ROOT_NAME = "CyberSec Career Intelligence"
SHORT_DESCRIPTION_LENGTH = 200


def _published_topic():
    return (KnowledgeTopic.publication_status == "published", KnowledgeTopic.is_active.is_(True))


def _reachable_domains(db: Session) -> dict[int, SecurityDomain]:
    # Active domains whose ancestors are all active: an active child under an inactive parent is not on the map.
    domains = {item.id: item for item in db.scalars(select(SecurityDomain)).all()}
    reachable: dict[int, SecurityDomain] = {}

    def visible(domain: SecurityDomain) -> bool:
        seen = set()
        while domain is not None:
            if not domain.is_active or domain.id in seen:
                return False
            seen.add(domain.id)
            if domain.parent_id is None:
                return True
            domain = domains.get(domain.parent_id)
        return False

    for domain in domains.values():
        if visible(domain):
            reachable[domain.id] = domain
    return reachable


def _ordered(domains: list[SecurityDomain]) -> list[SecurityDomain]:
    return sorted(domains, key=lambda item: (item.display_order, item.name.casefold()))


def _placements_query(domain_ids: set[int]):
    return (
        select(KnowledgeTopicDomain)
        .join(KnowledgeTopic, KnowledgeTopic.id == KnowledgeTopicDomain.topic_id)
        .where(KnowledgeTopicDomain.map_branch.is_not(None), KnowledgeTopicDomain.domain_id.in_(domain_ids), *_published_topic())
    )


def _domain_node(domain: SecurityDomain, reachable: dict[int, SecurityDomain], topics_by_domain: dict[int, set[int]]) -> dict[str, Any]:
    children = [item for item in reachable.values() if item.parent_id == domain.id]
    topics = set(topics_by_domain.get(domain.id, set()))
    stack = list(children)
    while stack:
        child = stack.pop()
        topics |= topics_by_domain.get(child.id, set())
        stack.extend(item for item in reachable.values() if item.parent_id == child.id)
    return {"id": domain.id, "slug": domain.slug, "name": domain.name, "child_domain_count": len(children), "placed_topic_count": len(topics)}


def _topics_by_domain(db: Session, reachable: dict[int, SecurityDomain]) -> dict[int, set[int]]:
    rows = db.execute(_placements_query(set(reachable)).with_only_columns(KnowledgeTopicDomain.domain_id, KnowledgeTopicDomain.topic_id)).all()
    result: dict[int, set[int]] = {}
    for domain_id, topic_id in rows:
        result.setdefault(domain_id, set()).add(topic_id)
    return result


def _require_domain(reachable: dict[int, SecurityDomain], domain_id: int) -> SecurityDomain:
    domain = reachable.get(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Active security domain was not found")
    return domain


def map_root(db: Session) -> dict[str, Any]:
    reachable = _reachable_domains(db)
    topics_by_domain = _topics_by_domain(db, reachable)
    top_level = _ordered([item for item in reachable.values() if item.parent_id is None])
    return {"root": {"id": "root", "name": ROOT_NAME}, "domains": [_domain_node(item, reachable, topics_by_domain) for item in top_level]}


def domain_children(db: Session, domain_id: int) -> dict[str, Any]:
    reachable = _reachable_domains(db)
    domain = _require_domain(reachable, domain_id)
    topics_by_domain = _topics_by_domain(db, reachable)
    nodes: list[dict[str, Any]] = [{"node_type": "domain", **_domain_node(item, reachable, topics_by_domain)} for item in _ordered([item for item in reachable.values() if item.parent_id == domain.id])]
    counts = dict(db.execute(
        _placements_query({domain.id}).with_only_columns(KnowledgeTopicDomain.map_branch, func.count(KnowledgeTopicDomain.topic_id)).group_by(KnowledgeTopicDomain.map_branch)
    ).all())
    nodes.extend({"node_type": "branch", "domain_id": domain.id, "branch": branch, "label": label, "topic_count": counts[branch]} for branch, label in MAP_BRANCHES.items() if counts.get(branch))
    return {"domain": _domain_node(domain, reachable, topics_by_domain), "nodes": nodes}


def _short_descriptions(db: Session, topics: list[KnowledgeTopic]) -> dict[int, str]:
    overviews = dict(db.execute(select(KnowledgeTopicSection.topic_id, KnowledgeTopicSection.published_content).where(
        KnowledgeTopicSection.topic_id.in_([item.id for item in topics]), KnowledgeTopicSection.section_type == "overview", KnowledgeTopicSection.status == "published",
    )).all())
    result = {}
    for topic in topics:
        overview = overviews.get(topic.id) or {}
        value = overview.get("short_description") if isinstance(overview, dict) else None
        text = value.strip() if isinstance(value, str) and value.strip() else (topic.description or "").strip()
        result[topic.id] = text if len(text) <= SHORT_DESCRIPTION_LENGTH else text[:SHORT_DESCRIPTION_LENGTH - 1].rstrip() + "…"
    return result


def _placement_counts(db: Session, reachable: dict[int, SecurityDomain], topic_ids: list[int]) -> dict[int, int]:
    return dict(db.execute(
        _placements_query(set(reachable)).where(KnowledgeTopicDomain.topic_id.in_(topic_ids))
        .with_only_columns(KnowledgeTopicDomain.topic_id, func.count(KnowledgeTopicDomain.domain_id)).group_by(KnowledgeTopicDomain.topic_id)
    ).all())


def branch_topics(db: Session, domain_id: int, branch: str, offset: int, limit: int) -> dict[str, Any]:
    reachable = _reachable_domains(db)
    _require_domain(reachable, domain_id)
    query = _placements_query({domain_id}).where(KnowledgeTopicDomain.map_branch == branch)
    total = db.scalar(query.with_only_columns(func.count())) or 0
    topics = list(db.scalars(query.with_only_columns(KnowledgeTopic).order_by(KnowledgeTopicDomain.display_order, KnowledgeTopic.name, KnowledgeTopic.id).offset(offset).limit(limit)).all())
    ids = [item.id for item in topics]
    placement_counts = _placement_counts(db, reachable, ids)
    with_children = set(db.scalars(select(KnowledgeTopic.parent_topic_id).where(KnowledgeTopic.parent_topic_id.in_(ids), *_published_topic()).distinct()).all())
    descriptions = _short_descriptions(db, topics)
    items = [{
        "id": topic.id, "topic_key": topic.topic_key or topic.slug, "name": topic.name, "short_description": descriptions[topic.id],
        "placement_count": placement_counts.get(topic.id, 0), "has_children": topic.id in with_children,
    } for topic in topics]
    return {"domain_id": domain_id, "branch": branch, "label": MAP_BRANCHES[branch], "items": items, "total": total, "offset": offset, "limit": limit}


def _domain_path(domain: SecurityDomain, reachable: dict[int, SecurityDomain]) -> list[dict[str, Any]]:
    path = []
    current: SecurityDomain | None = domain
    while current is not None:
        path.append({"id": current.id, "name": current.name})
        current = reachable.get(current.parent_id) if current.parent_id else None
    return list(reversed(path))


def _placements_by_topic(db: Session, reachable: dict[int, SecurityDomain], topic_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    rows = db.scalars(_placements_query(set(reachable)).where(KnowledgeTopicDomain.topic_id.in_(topic_ids))).all()
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row.topic_id, []).append({"domain_path": _domain_path(reachable[row.domain_id], reachable), "branch": row.map_branch, "label": MAP_BRANCHES[row.map_branch]})
    for placements in result.values():
        placements.sort(key=lambda item: ([part["name"].casefold() for part in item["domain_path"]], list(MAP_BRANCHES).index(item["branch"])))
    return result


def topic_placements(db: Session, topic_identifier: str) -> list[dict[str, Any]]:
    match = KnowledgeTopic.id == int(topic_identifier) if topic_identifier.isdigit() else (KnowledgeTopic.topic_key == topic_identifier) | (KnowledgeTopic.slug == topic_identifier)
    topic = db.scalar(select(KnowledgeTopic).where(match, *_published_topic()))
    if topic is None:
        raise HTTPException(status_code=404, detail="Published knowledge topic was not found")
    reachable = _reachable_domains(db)
    return _placements_by_topic(db, reachable, [topic.id]).get(topic.id, [])


def search_topics(db: Session, query: str, limit: int) -> dict[str, Any]:
    # /api/v1/search does not cover knowledge topics, so the map has its own matching over name, aliases and topic_key.
    term = query.strip().casefold()
    if len(term) < 2:
        raise HTTPException(status_code=422, detail="Search needs at least 2 characters")
    reachable = _reachable_domains(db)
    placed = _placements_query(set(reachable)).with_only_columns(KnowledgeTopicDomain.topic_id)
    matches = (
        func.lower(KnowledgeTopic.name).contains(term, autoescape=True)
        | func.lower(func.coalesce(KnowledgeTopic.topic_key, "")).contains(term, autoescape=True)
        | func.lower(cast(KnowledgeTopic.aliases, String)).contains(term, autoescape=True)
    )
    prefix_first = case((func.lower(KnowledgeTopic.name).startswith(term, autoescape=True), 0), else_=1)
    # Only topics that are on the map: a result the UI cannot reveal is not useful here.
    topics = list(db.scalars(select(KnowledgeTopic).where(matches, KnowledgeTopic.id.in_(placed), *_published_topic()).order_by(prefix_first, KnowledgeTopic.name, KnowledgeTopic.id).limit(limit)).all())
    descriptions = _short_descriptions(db, topics)
    placements = _placements_by_topic(db, reachable, [item.id for item in topics])
    return {"query": query.strip(), "items": [{
        "id": topic.id, "topic_key": topic.topic_key or topic.slug, "name": topic.name,
        "short_description": descriptions[topic.id], "placements": placements.get(topic.id, []),
    } for topic in topics]}


def map_etag(db: Session) -> str:
    # Changes after any publish, unpublish, placement change or domain edit, so cached map responses are revalidated.
    topic_published, topic_updated, topic_count = db.execute(select(func.max(KnowledgeTopic.published_at), func.max(KnowledgeTopic.updated_at), func.count(KnowledgeTopic.id))).one()
    section_published = db.scalar(select(func.max(KnowledgeTopicSectionVersion.published_at)))
    section_updated = db.scalar(select(func.max(KnowledgeTopicSection.updated_at)))
    domain_updated, domain_count = db.execute(select(func.max(SecurityDomain.updated_at), func.count(SecurityDomain.id))).one()
    digest = hashlib.blake2b(digest_size=12)
    digest.update(repr((topic_published, topic_updated, topic_count, section_published, section_updated, domain_updated, domain_count)).encode())
    for row in db.execute(select(KnowledgeTopicDomain.topic_id, KnowledgeTopicDomain.domain_id, KnowledgeTopicDomain.map_branch, KnowledgeTopicDomain.display_order).where(KnowledgeTopicDomain.map_branch.is_not(None)).order_by(KnowledgeTopicDomain.topic_id, KnowledgeTopicDomain.domain_id)):
        digest.update(repr(tuple(row)).encode())
    return f'"{digest.hexdigest()}"'
