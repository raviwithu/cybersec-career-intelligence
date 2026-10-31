import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, func, inspect, select

from app.database import SessionLocal
from app.models import CareerLevel, KnowledgeTopic, KnowledgeTopicDomain, KnowledgeTopicLevel, SecurityDomain

MAP = "/api/v1/knowledge-map"


@pytest.fixture(autouse=True)
def _remove_created_rows(client):
    # The test database is shared across modules, and other tests count every domain: remove what each test adds.
    # Depends on client so the app has created and seeded the tables first.
    with SessionLocal() as db:
        last_domain = db.scalar(select(func.max(SecurityDomain.id))) or 0
        last_topic = db.scalar(select(func.max(KnowledgeTopic.id))) or 0
    yield
    with SessionLocal() as db:
        db.execute(delete(KnowledgeTopic).where(KnowledgeTopic.id > last_topic))
        db.execute(delete(SecurityDomain).where(SecurityDomain.id > last_domain))
        db.commit()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _domain(db, name: str, *, parent: SecurityDomain | None = None, active: bool = True, order: int = 0) -> SecurityDomain:
    slug = _unique(name.lower().replace(" ", "-"))
    domain = SecurityDomain(name=slug, slug=slug, parent_id=parent.id if parent else None, is_active=active, display_order=order)
    db.add(domain)
    db.flush()
    return domain


def _topic(db, name: str, *, status: str = "published", active: bool = True, aliases=(), description: str = "", parent: KnowledgeTopic | None = None) -> KnowledgeTopic:
    key = _unique(name.lower().replace(" ", "-"))
    topic = KnowledgeTopic(name=name, slug=key, topic_key=key, description=description, aliases=list(aliases), publication_status=status, is_active=active, parent_topic_id=parent.id if parent else None, published_at=datetime.now(timezone.utc) if status == "published" else None)
    db.add(topic)
    db.flush()
    return topic


def _place(db, topic: KnowledgeTopic, domain: SecurityDomain, branch: str | None, order: int = 0) -> None:
    db.add(KnowledgeTopicDomain(topic_id=topic.id, domain_id=domain.id, map_branch=branch, display_order=order))
    db.flush()


def _children(client, domain_id: int) -> list[dict]:
    response = client.get(f"{MAP}/domains/{domain_id}/children")
    assert response.status_code == 200, response.text
    return response.json()["nodes"]


def test_root_lists_active_top_level_domains_in_display_order(client):
    with SessionLocal() as db:
        hidden = _domain(db, "Inactive Root", active=False)
        db.commit()
        hidden_id = hidden.id
        expected = [item.id for item in db.scalars(select(SecurityDomain).where(SecurityDomain.parent_id.is_(None), SecurityDomain.is_active.is_(True))).all()]
        orders = {item.id: (item.display_order, item.name.casefold()) for item in db.scalars(select(SecurityDomain)).all()}
    body = client.get(MAP).json()
    assert body["root"] == {"id": "root", "name": "CyberSec Career Intelligence"}
    ids = [item["id"] for item in body["domains"]]
    assert sorted(ids) == sorted(expected) and hidden_id not in ids
    assert ids == sorted(ids, key=orders.get)


def test_embedded_systems_security_lists_child_domains_before_branches(client):
    with SessionLocal() as db:
        embedded = db.scalar(select(SecurityDomain).where(SecurityDomain.slug == "embedded-systems-security"))
        child_names = [item.name for item in sorted(db.scalars(select(SecurityDomain).where(SecurityDomain.parent_id == embedded.id, SecurityDomain.is_active.is_(True))).all(), key=lambda item: (item.display_order, item.name.casefold()))]
        _place(db, _topic(db, "Embedded Foundations Topic"), embedded, "foundations")
        db.commit()
        embedded_id = embedded.id
    nodes = _children(client, embedded_id)
    domains = [item for item in nodes if item["node_type"] == "domain"]
    assert [item["name"] for item in domains] == child_names and child_names
    assert nodes[:len(domains)] == domains
    assert nodes[-1]["node_type"] == "branch" and nodes[-1]["branch"] == "foundations"
    root_node = next(item for item in client.get(MAP).json()["domains"] if item["id"] == embedded_id)
    assert root_node["child_domain_count"] == len(child_names)


def test_sub_domains_nest_to_any_depth_before_the_branches(client):
    # Domain > sub-domain > sub-sub-domain, created through Taxonomy Management, then Foundations/Security/Vulnerabilities.
    admin = {"X-Admin-API-Key": "test-admin-key"}
    ids = []
    for name in ("Depth Root", "Depth Child", "Depth Grandchild"):
        response = client.post("/api/v1/research/taxonomy/domain", headers=admin, json={"name": _unique(name), "parent_id": ids[-1] if ids else None})
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    root_id, child_id, grandchild_id = ids
    with SessionLocal() as db:
        grandchild = db.get(SecurityDomain, grandchild_id)
        _place(db, _topic(db, "Deep Foundations"), grandchild, "foundations")
        _place(db, _topic(db, "Deep Vulnerability"), grandchild, "vulnerabilities")
        db.commit()
    assert [(item["node_type"], item["id"]) for item in _children(client, root_id)] == [("domain", child_id)]
    assert [(item["node_type"], item["id"]) for item in _children(client, child_id)] == [("domain", grandchild_id)]
    assert [item["branch"] for item in _children(client, grandchild_id)] == ["foundations", "vulnerabilities"]
    root_node = next(item for item in client.get(MAP).json()["domains"] if item["id"] == root_id)
    assert (root_node["child_domain_count"], root_node["placed_topic_count"]) == (1, 2)
    placement = client.get(f"{MAP}/search", params={"q": "Deep Vulnerability"}).json()["items"][0]["placements"][0]
    assert [item["id"] for item in placement["domain_path"]] == ids


def test_branches_appear_only_with_a_published_placement_and_stay_in_their_domain(client):
    with SessionLocal() as db:
        domain_a, domain_b = _domain(db, "Domain A"), _domain(db, "Domain B")
        _place(db, _topic(db, "Draft Only", status="draft"), domain_a, "security")
        _place(db, _topic(db, "Unplaced Link"), domain_a, None)
        _place(db, _topic(db, "Published Vuln"), domain_a, "vulnerabilities")
        db.commit()
        a_id, b_id = domain_a.id, domain_b.id
    assert [(item["branch"], item["label"], item["topic_count"]) for item in _children(client, a_id)] == [("vulnerabilities", "Common Vulnerabilities", 1)]
    assert _children(client, b_id) == []
    assert client.get(f"{MAP}/domains/{b_id}/branches/vulnerabilities/topics").json()["items"] == []


def test_draft_review_and_inactive_topics_are_excluded_everywhere(client):
    with SessionLocal() as db:
        domain = _domain(db, "Exclusion Domain")
        visible = _topic(db, "Zephyr Visible")
        hidden = [_topic(db, "Zephyr Draft", status="draft"), _topic(db, "Zephyr Review", status="review"), _topic(db, "Zephyr Inactive", active=False)]
        for topic in (visible, *hidden):
            _place(db, topic, domain, "security")
        db.commit()
        domain_id, hidden_keys = domain.id, [item.topic_key for item in hidden]
    root_node = next(item for item in client.get(MAP).json()["domains"] if item["id"] == domain_id)
    assert root_node["placed_topic_count"] == 1
    assert _children(client, domain_id)[0]["topic_count"] == 1
    page = client.get(f"{MAP}/domains/{domain_id}/branches/security/topics").json()
    assert [item["name"] for item in page["items"]] == ["Zephyr Visible"] and page["total"] == 1
    assert [item["name"] for item in client.get(f"{MAP}/search", params={"q": "zephyr"}).json()["items"]] == ["Zephyr Visible"]
    for key in hidden_keys:
        assert client.get(f"{MAP}/topics/{key}/placements").status_code == 404


def test_one_topic_in_two_domains_is_one_row_with_two_placements(client):
    with SessionLocal() as db:
        domain_a, domain_b = _domain(db, "Cross A"), _domain(db, "Cross B")
        topic = _topic(db, "Cross Domain Topic")
        _place(db, topic, domain_a, "foundations")
        _place(db, topic, domain_b, "security")
        db.commit()
        a_id, b_id, topic_id, key = domain_a.id, domain_b.id, topic.id, topic.topic_key
        assert db.query(KnowledgeTopic).filter(KnowledgeTopic.topic_key == key).count() == 1
    for domain_id, branch in ((a_id, "foundations"), (b_id, "security")):
        item = client.get(f"{MAP}/domains/{domain_id}/branches/{branch}/topics").json()["items"][0]
        assert (item["id"], item["placement_count"]) == (topic_id, 2)
    placements = client.get(f"{MAP}/topics/{topic_id}/placements").json()
    assert sorted((item["domain_path"][-1]["id"], item["branch"]) for item in placements) == sorted([(a_id, "foundations"), (b_id, "security")])


def test_topics_are_paginated_and_ordered_with_a_limit_ceiling(client):
    with SessionLocal() as db:
        domain = _domain(db, "Paging Domain")
        parent = None
        for index, name in enumerate(["Echo", "Delta", "Charlie", "Bravo", "Alpha"]):
            topic = _topic(db, name, description="x" * 300 if name == "Alpha" else f"{name} description")
            _place(db, topic, domain, "foundations", order=0 if name in {"Echo", "Delta"} else 1)
            parent = parent or topic
        _topic(db, "Echo Child", parent=parent)
        db.commit()
        domain_id = domain.id
    url = f"{MAP}/domains/{domain_id}/branches/foundations/topics"
    full = client.get(url).json()
    assert [item["name"] for item in full["items"]] == ["Delta", "Echo", "Alpha", "Bravo", "Charlie"]
    assert (full["total"], full["offset"], full["limit"]) == (5, 0, 50)
    assert next(item for item in full["items"] if item["name"] == "Echo")["has_children"] is True
    assert len(next(item for item in full["items"] if item["name"] == "Alpha")["short_description"]) == 200
    page = client.get(url, params={"offset": 2, "limit": 2}).json()
    assert [item["name"] for item in page["items"]] == ["Alpha", "Bravo"] and page["total"] == 5
    assert client.get(url, params={"limit": 101}).status_code == 422


def test_search_matches_aliases_and_returns_placement_paths(client):
    with SessionLocal() as db:
        parent = _domain(db, "Search Parent")
        child = _domain(db, "Search Child", parent=parent)
        topic = _topic(db, "Return Oriented Programming", aliases=["Quokkachain"])
        _place(db, topic, child, "vulnerabilities")
        _topic(db, "Quokkachain Unplaced")
        db.commit()
        parent_id, child_id = parent.id, child.id
    body = client.get(f"{MAP}/search", params={"q": "quokkachain"}).json()
    assert [item["name"] for item in body["items"]] == ["Return Oriented Programming"]
    assert body["items"][0]["placements"] == [{"domain_path": [{"id": parent_id, "name": body["items"][0]["placements"][0]["domain_path"][0]["name"]}, {"id": child_id, "name": body["items"][0]["placements"][0]["domain_path"][1]["name"]}], "branch": "vulnerabilities", "label": "Common Vulnerabilities"}]
    assert client.get(f"{MAP}/search", params={"q": "q"}).status_code == 422
    assert client.get(f"{MAP}/search", params={"q": " q "}).status_code == 422
    assert client.get(f"{MAP}/search", params={"q": "x" * 101}).status_code == 422


def test_unknown_or_inactive_domains_404_and_invalid_branches_422(client):
    with SessionLocal() as db:
        inactive = _domain(db, "Inactive Domain", active=False)
        orphan = _domain(db, "Child Of Inactive", parent=inactive)
        topic = _topic(db, "Unplaced Published")
        db.commit()
        inactive_id, orphan_id, topic_id = inactive.id, orphan.id, topic.id
    for domain_id in (999999, inactive_id, orphan_id):
        assert client.get(f"{MAP}/domains/{domain_id}/children").status_code == 404
        assert client.get(f"{MAP}/domains/{domain_id}/branches/security/topics").status_code == 404
    assert client.get(f"{MAP}/domains/{orphan_id}/branches/tools/topics").status_code == 422
    assert client.get(f"{MAP}/topics/{topic_id}/placements").json() == []
    assert client.get(f"{MAP}/topics/no-such-topic/placements").status_code == 404


def test_etag_changes_after_a_topic_is_published_and_supports_revalidation(client):
    with SessionLocal() as db:
        domain = _domain(db, "Etag Domain")
        topic = _topic(db, "Etag Topic", status="draft")
        _place(db, topic, domain, "security")
        db.commit()
        topic_id = topic.id
    first = client.get(MAP)
    assert first.headers["cache-control"] == "public, max-age=60"
    etag = first.headers["etag"]
    assert client.get(MAP, headers={"If-None-Match": etag}).status_code == 304
    with SessionLocal() as db:
        topic = db.get(KnowledgeTopic, topic_id)
        topic.publication_status = "published"
        topic.published_at = datetime.now(timezone.utc)
        db.commit()
    second = client.get(MAP, headers={"If-None-Match": etag})
    assert second.status_code == 200 and second.headers["etag"] != etag


def test_topic_detail_includes_active_level_expectations(client):
    with SessionLocal() as db:
        topic = _topic(db, "Level Detail Topic")
        levels = list(db.scalars(select(CareerLevel).where(CareerLevel.is_active.is_(True)).order_by(CareerLevel.display_order).limit(2)).all())
        for level in reversed(levels):
            db.add(KnowledgeTopicLevel(topic_id=topic.id, career_level_id=level.id, expectation=f"Know {level.name}", practical_capability=f"Do {level.name}"))
        db.commit()
        key, names = topic.topic_key, [level.name for level in levels]
    body = client.get(f"/api/v1/knowledge/topics/{key}").json()
    assert [item["career_level"]["name"] for item in body["level_expectations"]] == names
    assert body["level_expectations"][0]["expectation"] == f"Know {names[0]}"
    assert {"career_track", "slug"} <= set(body["level_expectations"][0]["career_level"])


def test_placement_migration_upgrades_and_downgrades_on_sqlite():
    backend = Path(__file__).parents[1]
    temp_database = backend / "migration_map_test.sqlite3"
    temp_database.unlink(missing_ok=True)
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{temp_database}"}

    def alembic(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), *args], cwd=backend, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def columns():
        engine = create_engine(f"sqlite:///{temp_database}")
        try:
            inspector = inspect(engine)
            return {item["name"] for item in inspector.get_columns("knowledge_topic_domains")}, {item["name"] for item in inspector.get_indexes("knowledge_topic_domains")}
        finally:
            engine.dispose()

    try:
        alembic("upgrade", "head")
        names, indexes = columns()
        assert {"map_branch", "display_order"} <= names and "ix_knowledge_topic_domains_map_placement" in indexes
        alembic("downgrade", "ph12dunblockresolved")
        names, indexes = columns()
        assert {"map_branch", "display_order"}.isdisjoint(names) and "ix_knowledge_topic_domains_map_placement" not in indexes
        assert {"topic_id", "domain_id"} <= names
        alembic("upgrade", "head")
    finally:
        temp_database.unlink(missing_ok=True)
