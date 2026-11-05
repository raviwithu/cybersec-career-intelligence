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


def domain_layout(db: Session, domain_id: int, *, include_topic_id: int | None = None) -> dict[int, dict[str, Any]]:
    """Every topic the map shows in one domain, keyed by topic id: its parent topic (None: directly under the domain), the
    parent's branch it sits in, its order and its note. A topic whose parent is not shown in this domain sits directly
    under the domain. include_topic_id also counts a topic that publishing would publish (previews)."""
    visible = (KnowledgeTopic.publication_status == "published") if include_topic_id is None else ((KnowledgeTopic.publication_status == "published") | (KnowledgeTopic.id == include_topic_id))
    rows = db.execute(
        select(KnowledgeTopic, KnowledgeTopicDomain)
        .join(KnowledgeTopicDomain, KnowledgeTopicDomain.topic_id == KnowledgeTopic.id)
        .where(KnowledgeTopicDomain.domain_id == domain_id, KnowledgeTopicDomain.map_branch.is_not(None), KnowledgeTopic.is_active.is_(True), visible)
    ).all()
    layout = {topic.id: {"topic": topic, "parent_id": link.parent_topic_id, "branch": link.map_branch, "display_order": link.display_order, "context_note": link.context_note} for topic, link in rows}
    for item in layout.values():
        if item["parent_id"] not in layout:
            item["parent_id"] = None
    # Defensive: a parent cycle (validation prevents one) would hide its topics, so cut it and show them under the domain.
    for topic_id, item in layout.items():
        seen, current = {topic_id}, item["parent_id"]
        while current is not None and current not in seen:
            seen.add(current)
            current = layout[current]["parent_id"]
        if current is not None:
            item["parent_id"] = None
    for item in layout.values():
        if item["parent_id"] is None:
            item["branch"] = None
    return layout


def slot_members(layout: dict[int, dict[str, Any]], parent_id: int | None, branch: str | None) -> list[dict[str, Any]]:
    """Topics in one place on the map, in order: directly under the domain (parent_id None) or in one branch of a parent topic."""
    items = [item for item in layout.values() if item["parent_id"] == parent_id and (parent_id is None or item["branch"] == branch)]
    return sorted(items, key=lambda item: (item["display_order"], item["topic"].name.casefold(), item["topic"].id))


def domain_children(db: Session, domain_id: int) -> dict[str, Any]:
    """Sub-domains first, then the topics placed directly in this domain. Branches belong to topics (topic_children)."""
    reachable = _reachable_domains(db)
    domain = _require_domain(reachable, domain_id)
    topics_by_domain = _topics_by_domain(db, reachable)
    nodes: list[dict[str, Any]] = [{"node_type": "domain", **_domain_node(item, reachable, topics_by_domain)} for item in _ordered([item for item in reachable.values() if item.parent_id == domain.id])]
    layout = domain_layout(db, domain.id)
    nodes.extend({"node_type": "topic", "domain_id": domain.id, **item} for item in _topic_items(db, reachable, layout, slot_members(layout, None, None)))
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


def _topic_items(db: Session, reachable: dict[int, SecurityDomain], layout: dict[int, dict[str, Any]], members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topics = [item["topic"] for item in members]
    placement_counts = _placement_counts(db, reachable, [item.id for item in topics])
    with_children = {item["parent_id"] for item in layout.values()}
    descriptions = _short_descriptions(db, topics)
    return [{
        "id": topic.id, "topic_key": topic.topic_key or topic.slug, "name": topic.name, "short_description": descriptions[topic.id],
        "placement_count": placement_counts.get(topic.id, 0), "has_children": topic.id in with_children, "context_note": item["context_note"],
    } for topic, item in zip(topics, members)]


def topic_children(db: Session, domain_id: int, topic_id: int) -> dict[str, Any]:
    """A topic's Foundations, Security and Common Vulnerabilities branches in one domain, each with the topics placed in it.
    Every topic on the map shows all three branches, even before a topic is placed in one."""
    reachable = _reachable_domains(db)
    _require_domain(reachable, domain_id)
    layout = domain_layout(db, domain_id)
    if topic_id not in layout:
        raise HTTPException(status_code=404, detail="The topic is not on the published map in this domain")
    branches = []
    for branch, label in MAP_BRANCHES.items():
        members = slot_members(layout, topic_id, branch)
        branches.append({"branch": branch, "label": label, "topic_count": len(members), "items": _topic_items(db, reachable, layout, members)})
    return {"topic_id": topic_id, "domain_id": domain_id, "branches": branches}


def _domain_path(domain: SecurityDomain, reachable: dict[int, SecurityDomain]) -> list[dict[str, Any]]:
    path = []
    current: SecurityDomain | None = domain
    while current is not None:
        path.append({"id": current.id, "name": current.name})
        current = reachable.get(current.parent_id) if current.parent_id else None
    return list(reversed(path))


def _placements_by_topic(db: Session, reachable: dict[int, SecurityDomain], topic_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    rows = db.scalars(_placements_query(set(reachable)).where(KnowledgeTopicDomain.topic_id.in_(topic_ids))).all()
    layouts: dict[int, dict[int, dict[str, Any]]] = {}
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        layout = layouts.setdefault(row.domain_id, domain_layout(db, row.domain_id))
        item = layout[row.topic_id]
        result.setdefault(row.topic_id, []).append({
            "domain_path": _domain_path(reachable[row.domain_id], reachable), "branch": item["branch"], "label": MAP_BRANCHES.get(item["branch"]),
            "context_note": row.context_note, "ancestors": _ancestors(layout, row.topic_id),
        })
    for placements in result.values():
        placements.sort(key=lambda item: ([part["name"].casefold() for part in item["domain_path"]], len(item["ancestors"])))
    return result


def _ancestors(layout: dict[int, dict[str, Any]], topic_id: int) -> list[dict[str, Any]]:
    # The parent topics this topic sits under in one domain, outermost first, each with the branch it sits in under its own parent.
    chain: list[dict[str, Any]] = []
    parent_id = layout[topic_id]["parent_id"]
    while parent_id is not None:
        item = layout[parent_id]
        topic = item["topic"]
        chain.append({"id": topic.id, "topic_key": topic.topic_key or topic.slug, "name": topic.name, "branch": item["branch"]})
        parent_id = item["parent_id"]
    return list(reversed(chain))


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
    for row in db.execute(select(KnowledgeTopicDomain.topic_id, KnowledgeTopicDomain.domain_id, KnowledgeTopicDomain.parent_topic_id, KnowledgeTopicDomain.map_branch, KnowledgeTopicDomain.display_order).where(KnowledgeTopicDomain.map_branch.is_not(None)).order_by(KnowledgeTopicDomain.topic_id, KnowledgeTopicDomain.domain_id)):
        digest.update(repr(tuple(row)).encode())
    return f'"{digest.hexdigest()}"'
