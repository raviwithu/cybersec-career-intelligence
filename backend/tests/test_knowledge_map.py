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


def _place(db, topic: KnowledgeTopic, domain: SecurityDomain, branch: str | None = "foundations", order: int = 0, *, under: KnowledgeTopic | None = None) -> None:
    # Without under, the topic sits directly under the domain (branch then only marks it as placed; None leaves it unplaced).
    db.add(KnowledgeTopicDomain(topic_id=topic.id, domain_id=domain.id, map_branch=branch, display_order=order, parent_topic_id=under.id if under else None))
    db.flush()


def _children(client, domain_id: int) -> list[dict]:
    response = client.get(f"{MAP}/domains/{domain_id}/children")
    assert response.status_code == 200, response.text
    return response.json()["nodes"]


def _branches(client, domain_id: int, topic_id: int) -> dict[str, list[str]]:
    response = client.get(f"{MAP}/domains/{domain_id}/topics/{topic_id}/children")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(item["branch"], item["label"]) for item in body["branches"]] == [("foundations", "Foundations"), ("security", "Security"), ("vulnerabilities", "Common Vulnerabilities")]
    assert all(item["topic_count"] == len(item["items"]) for item in body["branches"])
    return {item["branch"]: [topic["name"] for topic in item["items"]] for item in body["branches"]}


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


def test_embedded_systems_security_lists_child_domains_then_its_topics(client):
    with SessionLocal() as db:
        embedded = db.scalar(select(SecurityDomain).where(SecurityDomain.slug == "embedded-systems-security"))
        child_names = [item.name for item in sorted(db.scalars(select(SecurityDomain).where(SecurityDomain.parent_id == embedded.id, SecurityDomain.is_active.is_(True))).all(), key=lambda item: (item.display_order, item.name.casefold()))]
        topic = _topic(db, "Embedded Root Topic")
        _place(db, topic, embedded, "security", order=100_000)
        db.commit()
        embedded_id, topic_id = embedded.id, topic.id
    nodes = _children(client, embedded_id)
    domains = [item for item in nodes if item["node_type"] == "domain"]
    assert [item["name"] for item in domains] == child_names and child_names
    # Domains hold sub-domains and topics; Foundations, Security and Common Vulnerabilities belong to topics.
    assert nodes[:len(domains)] == domains and {item["node_type"] for item in nodes} == {"domain", "topic"}
    assert nodes[-1]["id"] == topic_id and nodes[-1]["domain_id"] == embedded_id
    assert _branches(client, embedded_id, topic_id) == {"foundations": [], "security": [], "vulnerabilities": []}
    root_node = next(item for item in client.get(MAP).json()["domains"] if item["id"] == embedded_id)
    assert root_node["child_domain_count"] == len(child_names)


def test_sub_domains_nest_to_any_depth_before_topics_and_their_branches(client):
    # Domain > sub-domain > sub-sub-domain, created through Taxonomy Management, then a topic with its three branches.
    admin = {"X-Admin-API-Key": "test-admin-key"}
    ids = []
    for name in ("Depth Root", "Depth Child", "Depth Grandchild"):
        response = client.post("/api/v1/research/taxonomy/domain", headers=admin, json={"name": _unique(name), "parent_id": ids[-1] if ids else None})
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    root_id, child_id, grandchild_id = ids
    with SessionLocal() as db:
        grandchild = db.get(SecurityDomain, grandchild_id)
        deep = _topic(db, "Deep Topic")
        _place(db, deep, grandchild)
        _place(db, _topic(db, "Deep Foundations"), grandchild, "foundations", under=deep)
        _place(db, _topic(db, "Deep Vulnerability"), grandchild, "vulnerabilities", under=deep)
        db.commit()
        deep_id = deep.id
    assert [(item["node_type"], item["id"]) for item in _children(client, root_id)] == [("domain", child_id)]
    assert [(item["node_type"], item["id"]) for item in _children(client, child_id)] == [("domain", grandchild_id)]
    assert [(item["node_type"], item["name"], item["has_children"]) for item in _children(client, grandchild_id)] == [("topic", "Deep Topic", True)]
    assert _branches(client, grandchild_id, deep_id) == {"foundations": ["Deep Foundations"], "security": [], "vulnerabilities": ["Deep Vulnerability"]}
    root_node = next(item for item in client.get(MAP).json()["domains"] if item["id"] == root_id)
    assert (root_node["child_domain_count"], root_node["placed_topic_count"]) == (1, 3)
    placement = client.get(f"{MAP}/search", params={"q": "Deep Vulnerability"}).json()["items"][0]["placements"][0]
    assert [item["id"] for item in placement["domain_path"]] == ids
    assert (placement["branch"], placement["label"]) == ("vulnerabilities", "Common Vulnerabilities")
    assert [(item["name"], item["branch"]) for item in placement["ancestors"]] == [("Deep Topic", None)]


def test_topics_sit_in_the_branches_of_their_parent_topic(client):
    with SessionLocal() as db:
        domain = _domain(db, "Nesting Domain")
        overview, standalone = _topic(db, "IAM Overview Nest"), _topic(db, "Standalone Nest")
        components, hierarchy, users = _topic(db, "Components Nest"), _topic(db, "Hierarchy Nest"), _topic(db, "Users Nest")
        policies, draft, unplaced_parent, orphan = _topic(db, "Policies Nest"), _topic(db, "Draft Child Nest", status="draft"), _topic(db, "Elsewhere Nest"), _topic(db, "Orphan Nest")
        _place(db, overview, domain, order=0)
        _place(db, standalone, domain, order=1)
        _place(db, components, domain, "foundations", 0, under=overview)
        _place(db, hierarchy, domain, "foundations", 1, under=overview)
        _place(db, users, domain, "foundations", under=components)
        _place(db, policies, domain, "security", under=overview)
        _place(db, draft, domain, "security", under=overview)
        # Its parent is not on the map in this domain, so it sits directly under the domain.
        _place(db, orphan, domain, "vulnerabilities", 2, under=unplaced_parent)
        db.commit()
        d, ids = domain.id, {t.name: (t.id, t.topic_key) for t in (overview, components, users, policies, standalone)}
    assert [(item["name"], item["has_children"]) for item in _children(client, d)] == [("IAM Overview Nest", True), ("Standalone Nest", False), ("Orphan Nest", False)]
    assert _branches(client, d, ids["IAM Overview Nest"][0]) == {"foundations": ["Components Nest", "Hierarchy Nest"], "security": ["Policies Nest"], "vulnerabilities": []}
    # Components Nest is itself in a branch, so it shows only the branch that already holds a topic.
    nested = client.get(f"{MAP}/domains/{d}/topics/{ids['Components Nest'][0]}/children").json()["branches"]
    assert [(item["branch"], [topic["name"] for topic in item["items"]]) for item in nested] == [("foundations", ["Users Nest"])]
    placements = client.get(f"{MAP}/topics/{ids['Users Nest'][1]}/placements").json()
    assert [(item["name"], item["branch"]) for item in placements[0]["ancestors"]] == [("IAM Overview Nest", None), ("Components Nest", "foundations")]
    assert placements[0]["branch"] == "foundations"
    root = client.get(f"{MAP}/topics/{ids['Standalone Nest'][1]}/placements").json()[0]
    assert (root["branch"], root["label"], root["ancestors"]) == (None, None, [])
    assert client.get(f"{MAP}/domains/{d}/topics/999999/children").status_code == 404


@pytest.mark.parametrize("branch", ["foundations", "security", "vulnerabilities"])
def test_a_topic_inside_any_branch_has_no_branches_of_its_own(client, branch):
    with SessionLocal() as db:
        domain = _domain(db, "Branch Item Domain")
        parent = _topic(db, "Branch Item Parent")
        item = _topic(db, "Branch Item")
        _place(db, parent, domain)
        _place(db, item, domain, branch, under=parent)
        db.commit()
        domain_id, parent_id, item_id = domain.id, parent.id, item.id
    body = client.get(f"{MAP}/domains/{domain_id}/topics/{item_id}/children").json()
    assert body["branches"] == []
    assert body["sections"] == []
    assert len(client.get(f"{MAP}/domains/{domain_id}/topics/{parent_id}/children").json()["branches"]) == 3


def test_a_topic_directly_under_a_domain_keeps_its_branches_whatever_its_stored_branch(client):
    # Directly under a domain, map_branch only marks the topic as placed.
    with SessionLocal() as db:
        domain = _domain(db, "Direct Weakness Domain")
        topic = _topic(db, "Direct Weakness Topic")
        _place(db, topic, domain, "vulnerabilities")
        db.commit()
        domain_id, topic_id = domain.id, topic.id
    assert len(client.get(f"{MAP}/domains/{domain_id}/topics/{topic_id}/children").json()["branches"]) == 3


def test_a_topic_already_under_a_branch_item_stays_visible(client):
    with SessionLocal() as db:
        domain = _domain(db, "Legacy Weakness Domain")
        parent = _topic(db, "Legacy Parent")
        weakness = _topic(db, "Legacy Weakness")
        child = _topic(db, "Legacy Child")
        _place(db, parent, domain)
        _place(db, weakness, domain, "vulnerabilities", under=parent)
        _place(db, child, domain, "foundations", under=weakness)
        db.commit()
        domain_id, weakness_id = domain.id, weakness.id
    branches = client.get(f"{MAP}/domains/{domain_id}/topics/{weakness_id}/children").json()["branches"]
    assert [(item["branch"], [topic["name"] for topic in item["items"]]) for item in branches] == [("foundations", ["Legacy Child"])]


@pytest.mark.parametrize("branch", ["foundations", "security", "vulnerabilities"])
def test_no_new_topic_can_be_placed_under_a_branch_item(client, branch):
    with SessionLocal() as db:
        domain = _domain(db, "Refused Item Domain")
        parent = _topic(db, "Refused Parent")
        item = _topic(db, "Refused Item")
        _place(db, parent, domain)
        _place(db, item, domain, branch, under=parent)
        db.commit()
        domain_id, item_id = domain.id, item.id
    response = client.post("/api/v1/knowledge/proposals", headers={"X-Admin-API-Key": "test-admin-key"}, json={"schema_version": "1.0", "source_type": "manual", "action": "CREATE_TOPIC", "topic_name": "Refused Child", "change_reason": "Test", "proposed_content": {"topic": {"name": "Refused Child", "description": ""}, "placements": [{"domain_id": domain_id, "parent_topic_id": item_id, "map_branch": "foundations"}]}})
    assert response.status_code == 409
    assert "inside a branch" in response.text


def test_every_topic_lists_all_three_branches_counting_only_published_placements(client):
    with SessionLocal() as db:
        domain_a, domain_b = _domain(db, "Domain A"), _domain(db, "Domain B")
        parent = _topic(db, "Branch Parent")
        _place(db, parent, domain_a)
        _place(db, _topic(db, "Draft Only", status="draft"), domain_a, "security", under=parent)
        _place(db, _topic(db, "Unplaced Link"), domain_a, None, under=parent)
        _place(db, _topic(db, "Published Vuln"), domain_a, "vulnerabilities", under=parent)
        db.commit()
        a_id, b_id, parent_id = domain_a.id, domain_b.id, parent.id
    body = client.get(f"{MAP}/domains/{a_id}/topics/{parent_id}/children").json()
    assert [(item["branch"], item["topic_count"]) for item in body["branches"]] == [("foundations", 0), ("security", 0), ("vulnerabilities", 1)]
    assert _children(client, b_id) == []
    # The parent is not placed in Domain B.
    assert client.get(f"{MAP}/domains/{b_id}/topics/{parent_id}/children").status_code == 404


def test_draft_review_and_inactive_topics_are_excluded_everywhere(client):
    with SessionLocal() as db:
        domain = _domain(db, "Exclusion Domain")
        visible = _topic(db, "Zephyr Visible")
        hidden = [_topic(db, "Zephyr Draft", status="draft"), _topic(db, "Zephyr Review", status="review"), _topic(db, "Zephyr Inactive", active=False)]
        for topic in (visible, *hidden):
            _place(db, topic, domain, "security")
        db.commit()
        domain_id, hidden_keys, hidden_ids = domain.id, [item.topic_key for item in hidden], [item.id for item in hidden]
    root_node = next(item for item in client.get(MAP).json()["domains"] if item["id"] == domain_id)
    assert root_node["placed_topic_count"] == 1
    assert [item["name"] for item in _children(client, domain_id)] == ["Zephyr Visible"]
    assert [item["name"] for item in client.get(f"{MAP}/search", params={"q": "zephyr"}).json()["items"]] == ["Zephyr Visible"]
    for key, topic_id in zip(hidden_keys, hidden_ids):
        assert client.get(f"{MAP}/topics/{key}/placements").status_code == 404
        assert client.get(f"{MAP}/domains/{domain_id}/topics/{topic_id}/children").status_code == 404


def test_one_topic_in_two_domains_is_one_row_with_two_placements(client):
    with SessionLocal() as db:
        domain_a, domain_b = _domain(db, "Cross A"), _domain(db, "Cross B")
        topic, parent = _topic(db, "Cross Domain Topic"), _topic(db, "Cross Parent")
        _place(db, topic, domain_a)
        _place(db, parent, domain_b)
        _place(db, topic, domain_b, "security", under=parent)
        db.commit()
        a_id, b_id, topic_id, parent_id, key = domain_a.id, domain_b.id, topic.id, parent.id, topic.topic_key
        assert db.query(KnowledgeTopic).filter(KnowledgeTopic.topic_key == key).count() == 1
    item = _children(client, a_id)[0]
    assert (item["id"], item["placement_count"]) == (topic_id, 2)
    nested = client.get(f"{MAP}/domains/{b_id}/topics/{parent_id}/children").json()["branches"][1]["items"][0]
    assert (nested["id"], nested["placement_count"]) == (topic_id, 2)
    placements = client.get(f"{MAP}/topics/{topic_id}/placements").json()
    assert sorted((item["domain_path"][-1]["id"], item["branch"]) for item in placements) == sorted([(a_id, None), (b_id, "security")])


def test_topics_are_ordered_and_descriptions_shortened(client):
    with SessionLocal() as db:
        domain = _domain(db, "Ordering Domain")
        topics = {}
        for name in ["Echo", "Delta", "Charlie", "Bravo", "Alpha"]:
            topics[name] = _topic(db, name, description="x" * 300 if name == "Alpha" else f"{name} description")
            _place(db, topics[name], domain, order=0 if name in {"Echo", "Delta"} else 1)
        _place(db, _topic(db, "Echo Child"), domain, "security", under=topics["Echo"])
        db.commit()
        domain_id = domain.id
    items = _children(client, domain_id)
    assert [item["name"] for item in items] == ["Delta", "Echo", "Alpha", "Bravo", "Charlie"]
    assert next(item for item in items if item["name"] == "Echo")["has_children"] is True
    assert len(next(item for item in items if item["name"] == "Alpha")["short_description"]) == 200


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
    assert body["items"][0]["placements"] == [{"domain_path": [{"id": parent_id, "name": body["items"][0]["placements"][0]["domain_path"][0]["name"]}, {"id": child_id, "name": body["items"][0]["placements"][0]["domain_path"][1]["name"]}], "branch": None, "label": None, "context_note": None, "ancestors": []}]
    assert client.get(f"{MAP}/search", params={"q": "q"}).status_code == 422
    assert client.get(f"{MAP}/search", params={"q": " q "}).status_code == 422
    assert client.get(f"{MAP}/search", params={"q": "x" * 101}).status_code == 422


def test_unknown_or_inactive_domains_and_topics_404(client):
    with SessionLocal() as db:
        inactive = _domain(db, "Inactive Domain", active=False)
        orphan = _domain(db, "Child Of Inactive", parent=inactive)
        topic = _topic(db, "Unplaced Published")
        _place(db, topic, orphan)
        db.commit()
        inactive_id, orphan_id, topic_id = inactive.id, orphan.id, topic.id
    for domain_id in (999999, inactive_id, orphan_id):
        assert client.get(f"{MAP}/domains/{domain_id}/children").status_code == 404
        assert client.get(f"{MAP}/domains/{domain_id}/topics/{topic_id}/children").status_code == 404
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
        assert {"map_branch", "display_order", "context_note", "parent_topic_id"} <= names and "ix_knowledge_topic_domains_map_placement" in indexes
        alembic("downgrade", "ph14placementcontext")
        assert "parent_topic_id" not in columns()[0] and "context_note" in columns()[0]
        alembic("downgrade", "ph13mapplacement")
        assert "context_note" not in columns()[0]
        alembic("downgrade", "ph12dunblockresolved")
        names, indexes = columns()
        assert {"map_branch", "display_order"}.isdisjoint(names) and "ix_knowledge_topic_domains_map_placement" not in indexes
        assert {"topic_id", "domain_id"} <= names
        alembic("upgrade", "head")
    finally:
        temp_database.unlink(missing_ok=True)
