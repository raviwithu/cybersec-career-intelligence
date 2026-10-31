from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.models import CareerLevel, KnowledgeTopic, KnowledgeTopicDomain, KnowledgeTopicLevel, KnowledgeTopicProposal, KnowledgeTopicRelationship, SecurityDomain

ADMIN = {"X-Admin-API-Key": "test-admin-key"}
MAP = "/api/v1/knowledge-map"
PROPOSALS = "/api/v1/knowledge/proposals"


@pytest.fixture(autouse=True)
def _remove_created_rows(client):
    # The test database is shared across modules and other tests count domains: remove what each test adds.
    # Proposals go too: SQLite reuses deleted ids, and an open proposal for a reused id would be returned as a duplicate.
    with SessionLocal() as db:
        last_domain = db.scalar(select(func.max(SecurityDomain.id))) or 0
        last_topic = db.scalar(select(func.max(KnowledgeTopic.id))) or 0
        last_proposal = db.scalar(select(func.max(KnowledgeTopicProposal.id))) or 0
    yield
    with SessionLocal() as db:
        db.execute(delete(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id > last_proposal))
        db.execute(delete(KnowledgeTopic).where(KnowledgeTopic.id > last_topic))
        db.execute(delete(SecurityDomain).where(SecurityDomain.id > last_domain))
        db.commit()


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_domain(*, parent_id: int | None = None) -> int:
    with SessionLocal() as db:
        slug = unique("map-domain")
        domain = SecurityDomain(name=slug, slug=slug, parent_id=parent_id, is_active=True, display_order=0)
        db.add(domain)
        db.commit()
        return domain.id


def make_topic(name: str | None = None, *, aliases=(), placements=()) -> dict:
    with SessionLocal() as db:
        key = unique("map-topic")
        topic = KnowledgeTopic(name=name or key, slug=key, topic_key=key, description="", aliases=list(aliases), publication_status="published", is_active=True, version=1, published_at=datetime.now(timezone.utc))
        db.add(topic)
        db.flush()
        for domain_id, branch, *order in placements:
            db.add(KnowledgeTopicDomain(topic_id=topic.id, domain_id=domain_id, map_branch=branch, display_order=order[0] if order else 0))
        db.commit()
        return {"id": topic.id, "topic_key": key, "name": topic.name}


def branch_keys(client, domain_id: int, branch: str) -> list[str]:
    response = client.get(f"{MAP}/domains/{domain_id}/branches/{branch}/topics", params={"limit": 100})
    assert response.status_code in (200, 404), response.text
    return [item["topic_key"] for item in response.json().get("items", [])] if response.status_code == 200 else []


def placement(topic_id: int, domain_id: int):
    with SessionLocal() as db:
        link = db.get(KnowledgeTopicDomain, (topic_id, domain_id))
        return None if link is None else (link.map_branch, link.display_order)


def propose(client, action: str, topic_id: int | None, content: dict, *, reason: str = "Administrator map change.", **extra):
    payload = {"schema_version": "1.0", "source_type": "manual", "action": action, "proposed_content": content, "change_reason": reason, **extra}
    if topic_id is not None:
        payload["topic_id"] = topic_id
    return client.post(PROPOSALS, headers=ADMIN, json=payload)


def review(client, proposal: dict, action: str, **extra) -> dict:
    response = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": action, "reviewer_note": f"{action} in test.", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def publish(client, proposal: dict, *, expected: int = 200):
    response = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/publish", headers=ADMIN, json={"confirm": True, "expected_version": proposal["version"], "change_reason": "Published in test."})
    assert response.status_code == expected, response.text
    return response.json()


def create_and_publish(client, action: str, topic_id: int | None, content: dict, **extra) -> dict:
    created = propose(client, action, topic_id, content, **extra)
    assert created.status_code == 201, created.text
    return publish(client, review(client, created.json(), "approve"))


def test_place_unplace_and_reorder_publish_only_after_explicit_publication(client):
    domain = make_domain()
    first = make_topic(placements=[(domain, "foundations", 0)])
    second = make_topic(placements=[(domain, "foundations", 1)])
    newcomer = make_topic()

    created = propose(client, "PLACE_TOPIC", newcomer["id"], {"domain_id": domain, "map_branch": "foundations"})
    assert created.status_code == 201, created.text
    assert created.json()["original_content"] == {"placement": None}
    approved = review(client, created.json(), "approve")
    assert branch_keys(client, domain, "foundations") == [first["topic_key"], second["topic_key"]]
    publish(client, approved)
    assert branch_keys(client, domain, "foundations") == [first["topic_key"], second["topic_key"], newcomer["topic_key"]]

    create_and_publish(client, "REORDER_TOPICS", first["id"], {"domain_id": domain, "map_branch": "foundations", "ordered_topic_ids": [newcomer["id"], first["id"], second["id"]]})
    assert branch_keys(client, domain, "foundations") == [newcomer["topic_key"], first["topic_key"], second["topic_key"]]

    create_and_publish(client, "UNPLACE_TOPIC", second["id"], {"domain_id": domain})
    assert branch_keys(client, domain, "foundations") == [newcomer["topic_key"], first["topic_key"]]
    with SessionLocal() as db:
        link = db.get(KnowledgeTopicDomain, (second["id"], domain))
        assert link is not None and link.map_branch is None  # the domain link stays


def test_reorder_must_list_the_current_branch_exactly(client):
    domain = make_domain()
    first = make_topic(placements=[(domain, "security")])
    make_topic(placements=[(domain, "security")])
    response = propose(client, "REORDER_TOPICS", first["id"], {"domain_id": domain, "map_branch": "security", "ordered_topic_ids": [first["id"]]})
    assert response.status_code == 409


def test_move_topic_and_cross_domain_placement_keep_one_topic_row(client):
    source, target, other = make_domain(), make_domain(), make_domain()
    topic = make_topic(placements=[(source, "security")])
    create_and_publish(client, "PLACE_TOPIC", topic["id"], {"domain_id": other, "map_branch": "vulnerabilities"})
    create_and_publish(client, "MOVE_TOPIC", topic["id"], {"from": {"domain_id": source}, "to": {"domain_id": target, "map_branch": "foundations"}})
    assert topic["topic_key"] not in branch_keys(client, source, "security")
    assert branch_keys(client, target, "foundations") == [topic["topic_key"]]
    assert branch_keys(client, other, "vulnerabilities") == [topic["topic_key"]]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeTopic).where(KnowledgeTopic.topic_key == topic["topic_key"])) == 1
    placements = client.get(f"{MAP}/topics/{topic['topic_key']}/placements").json()
    assert {item["domain_path"][-1]["id"] for item in placements} == {target, other}


def test_move_is_atomic_when_publication_fails_part_way(client, monkeypatch):
    source, target = make_domain(), make_domain()
    topic = make_topic(placements=[(source, "security")])
    approved = review(client, propose(client, "MOVE_TOPIC", topic["id"], {"from": {"domain_id": source}, "to": {"domain_id": target, "map_branch": "foundations"}}).json(), "approve")

    import app.knowledge_map_proposals as map_proposals

    def failing_place(*args, **kwargs):
        raise RuntimeError("simulated failure after the unplace step")

    monkeypatch.setattr(map_proposals, "place", failing_place)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/knowledge/admin/proposals/{approved['id']}/publish", headers=ADMIN, json={"confirm": True, "expected_version": approved["version"]})
    assert placement(topic["id"], source) == ("security", 0)
    assert placement(topic["id"], target) is None
    proposal = client.get(f"{PROPOSALS}/{approved['id']}", headers=ADMIN).json()
    assert proposal["status"] == "approved"


def test_reject_and_defer_leave_live_data_unchanged(client):
    domain = make_domain()
    topic = make_topic()
    rejected = propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}).json()
    review(client, rejected, "reject")
    deferred = propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "foundations"}).json()
    review(client, deferred, "defer")
    assert placement(topic["id"], domain) is None
    assert branch_keys(client, domain, "security") == [] and branch_keys(client, domain, "foundations") == []


def test_modify_bumps_version_and_stale_review_or_publish_is_refused(client):
    domain, other = make_domain(), make_domain()
    topic = make_topic()
    created = propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}).json()
    modified = review(client, created, "modify", proposed_content={"domain_id": other, "map_branch": "foundations"})
    assert modified["version"] == created["version"] + 1
    assert modified["proposed_content"] == {"domain_id": other, "map_branch": "foundations", "display_order": None}
    stale_review = client.post(f"/api/v1/knowledge/admin/proposals/{created['id']}/review", headers=ADMIN, json={"expected_version": created["version"], "action": "approve"})
    assert stale_review.status_code == 409
    approved = review(client, modified, "approve")
    publish(client, {**approved, "version": modified["version"]}, expected=409)
    publish(client, approved)
    assert branch_keys(client, other, "foundations") == [topic["topic_key"]]


def test_publish_refuses_a_proposal_whose_placement_changed_since_creation(client):
    domain = make_domain()
    topic = make_topic()
    first = review(client, propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}).json(), "approve")
    second = review(client, propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "foundations"}).json(), "approve")
    publish(client, first)
    publish(client, second, expected=409)
    assert placement(topic["id"], domain)[0] == "security"


def test_set_parent_prevents_cycles_at_create_and_at_publish(client):
    parent, child = make_topic(), make_topic()
    create_and_publish(client, "SET_PARENT_TOPIC", child["id"], {"parent_topic_id": parent["id"]})
    assert propose(client, "SET_PARENT_TOPIC", parent["id"], {"parent_topic_id": child["id"]}).status_code == 409
    assert propose(client, "SET_PARENT_TOPIC", parent["id"], {"parent_topic_id": parent["id"]}).status_code == 422

    a, b = make_topic(), make_topic()
    a_under_b = review(client, propose(client, "SET_PARENT_TOPIC", a["id"], {"parent_topic_id": b["id"]}).json(), "approve")
    b_under_a = review(client, propose(client, "SET_PARENT_TOPIC", b["id"], {"parent_topic_id": a["id"]}).json(), "approve")
    publish(client, b_under_a)
    publish(client, a_under_b, expected=409)
    with SessionLocal() as db:
        assert db.get(KnowledgeTopic, a["id"]).parent_topic_id is None


def test_remove_relationship_deactivate_and_career_levels(client):
    domain = make_domain()
    topic = make_topic(placements=[(domain, "security")])
    other = make_topic()
    with SessionLocal() as db:
        db.add(KnowledgeTopicRelationship(source_topic_id=topic["id"], target_topic_id=other["id"], relationship_type="tested_by"))
        level = db.scalar(select(CareerLevel).where(CareerLevel.is_active.is_(True)).order_by(CareerLevel.display_order))
        level_id = level.id
        db.commit()

    assert propose(client, "REMOVE_TOPIC_RELATIONSHIP", topic["id"], {"target_topic_id": other["id"], "relationship_type": "related"}).status_code == 409
    create_and_publish(client, "REMOVE_TOPIC_RELATIONSHIP", topic["id"], {"target_topic_id": other["id"], "relationship_type": "tested_by"})
    with SessionLocal() as db:
        assert db.scalar(select(KnowledgeTopicRelationship).where(KnowledgeTopicRelationship.source_topic_id == topic["id"])) is None

    create_and_publish(client, "UPDATE_CAREER_LEVELS", topic["id"], {"levels": [{"career_level_id": level_id, "expectation": "Explain the control.", "practical_capability": "Configure it."}]})
    body = client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}").json()
    assert body["level_expectations"][0]["expectation"] == "Explain the control."
    create_and_publish(client, "UPDATE_CAREER_LEVELS", topic["id"], {"levels": [{"career_level_id": level_id, "expectation": "Design the control.", "practical_capability": "Review it."}]})
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeTopicLevel).where(KnowledgeTopicLevel.topic_id == topic["id"])) == 1

    assert propose(client, "DEACTIVATE_TOPIC", topic["id"], {"reason": ""}).status_code == 422
    create_and_publish(client, "DEACTIVATE_TOPIC", topic["id"], {"reason": "Superseded by a broader topic."})
    assert branch_keys(client, domain, "security") == []
    assert client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}").status_code == 404
    assert propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "foundations"}).status_code == 409


def test_map_actions_require_a_change_reason_and_valid_payloads(client):
    domain = make_domain()
    topic = make_topic()
    assert propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}, reason="").status_code == 422
    assert propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "elsewhere"}).status_code == 422
    assert propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security", "colour": "red"}).status_code == 422
    with SessionLocal() as db:
        db.get(SecurityDomain, domain).is_active = False
        db.commit()
    assert propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}).status_code == 409


def test_create_topic_detects_duplicates_by_name_slug_and_alias(client):
    existing = make_topic("Session Fixation Defence", aliases=["Session Fixation"])
    for name, key in (("session fixation defence", None), ("Something Else", existing["topic_key"]), ("Session-Fixation", None)):
        response = propose(client, "CREATE_TOPIC", None, {"topic": {"name": name}}, topic_name=name, **({"topic_key": key} if key else {}))
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["existing_topic_id"] == existing["id"]


def test_create_topic_with_placements_publishes_together(client):
    domain = make_domain()
    name = unique("Placed New Topic")
    created = propose(client, "CREATE_TOPIC", None, {"topic": {"name": name, "description": "New."}, "placements": [{"domain_id": domain, "map_branch": "foundations"}]}, topic_name=name)
    assert created.status_code == 201, created.text
    assert branch_keys(client, domain, "foundations") == []
    published = publish(client, review(client, created.json(), "approve"))
    with SessionLocal() as db:
        key = db.get(KnowledgeTopic, published["topic_id"]).topic_key
    assert branch_keys(client, domain, "foundations") == [key]


def test_restore_section_version_publishes_old_content_as_a_new_version(client):
    topic = make_topic()
    for text in ("First overview.", "Second overview."):
        create_and_publish(client, "ADD_SECTION" if text.startswith("First") else "UPDATE_SECTION", topic["id"], {"short_description": text}, section="overview")
    restored = create_and_publish(client, "RESTORE_VERSION", topic["id"], {"target": "section", "section_type": "overview", "version": 1})
    assert restored["section"] == "overview"
    section = next(item for item in client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}").json()["sections"] if item["section_type"] == "overview")
    assert section["published_version"] == 3 and section["content"]["short_description"] == "First overview."
    history = client.get(f"/api/v1/knowledge/admin/topics/{topic['id']}/history", headers=ADMIN).json()["items"]
    assert sorted(item["version"] for item in history if item["kind"] == "section_version") == [1, 2, 3]
    assert all({"actor", "reason", "created_at"} <= item.keys() for item in history)


def test_restore_topic_version_brings_back_placements_and_history_lists_changes(client):
    domain = make_domain()
    topic = make_topic()
    create_and_publish(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"})
    history = client.get(f"/api/v1/knowledge/admin/topics/{topic['id']}/history", headers=ADMIN).json()["items"]
    placed_version = next(item["version"] for item in history if item["kind"] == "version" and item["snapshot"]["placements"])
    create_and_publish(client, "UNPLACE_TOPIC", topic["id"], {"domain_id": domain})
    assert branch_keys(client, domain, "security") == []
    create_and_publish(client, "RESTORE_VERSION", topic["id"], {"target": "topic", "version": placed_version})
    assert branch_keys(client, domain, "security") == [topic["topic_key"]]
    history = client.get(f"/api/v1/knowledge/admin/topics/{topic['id']}/history", headers=ADMIN).json()["items"]
    assert len([item for item in history if item["kind"] == "version"]) == 3
    assert {"map_place_topic", "map_unplace_topic", "map_restore_version"} <= {item["action"] for item in history if item["kind"] == "audit"}


def test_preview_shows_branches_before_and_after_without_writing(client):
    domain = make_domain()
    resident = make_topic(placements=[(domain, "security")])
    topic = make_topic()
    created = propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}).json()
    preview = client.get(f"/api/v1/knowledge/admin/proposals/{created['id']}/map-preview", headers=ADMIN)
    assert preview.status_code == 200, preview.text
    branch = preview.json()["branches"][0]
    assert branch["domain_id"] == domain and branch["label"] == "Security"
    assert [item["topic_id"] for item in branch["before"]] == [resident["id"]]
    assert [item["topic_id"] for item in branch["after"]] == [resident["id"], topic["id"]]
    assert placement(topic["id"], domain) is None
    assert client.get(f"/api/v1/knowledge/admin/proposals/{created['id']}/map-preview").status_code in (401, 403)


def test_map_group_filter_and_admin_only_publication(client):
    domain = make_domain()
    topic = make_topic()
    created = propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "security"}).json()
    queue = client.get("/api/v1/knowledge/admin/proposals", headers=ADMIN, params={"group": "map", "limit": 500}).json()
    assert created["id"] in {item["id"] for item in queue["items"]}
    assert all(item["action"] not in {"UPDATE_SECTION", "ADD_SECTION"} for item in queue["items"])
    approved = review(client, created, "approve")
    unauthorised = client.post(f"/api/v1/knowledge/admin/proposals/{approved['id']}/publish", json={"confirm": True, "expected_version": approved["version"]})
    assert unauthorised.status_code in (401, 403)
    assert branch_keys(client, domain, "security") == []


def test_end_to_end_propose_modify_approve_publish_and_reject(client):
    domain = make_domain()
    topic = make_topic()
    created = propose(client, "PLACE_TOPIC", topic["id"], {"domain_id": domain, "map_branch": "vulnerabilities"}).json()
    modified = review(client, created, "modify", proposed_content={"domain_id": domain, "map_branch": "security"})
    publish(client, review(client, modified, "approve"))
    assert branch_keys(client, domain, "security") == [topic["topic_key"]]
    children = client.get(f"{MAP}/domains/{domain}/children").json()["nodes"]
    assert [item["branch"] for item in children if item["node_type"] == "branch"] == ["security"]

    rejected = propose(client, "UNPLACE_TOPIC", topic["id"], {"domain_id": domain}).json()
    review(client, rejected, "reject")
    assert branch_keys(client, domain, "security") == [topic["topic_key"]]


def test_one_shared_topic_reused_across_domains_with_a_context_note_per_domain(client):
    # One SSRF topic, placed under two domains' Common Vulnerabilities, each with its own "how it applies here" note.
    lambda_domain, web_domain = make_domain(), make_domain()
    ssrf = make_topic("Shared SSRF")
    for domain, note in ((lambda_domain, "Reads local files and environment through file:// in Lambda."), (web_domain, "Reaches internal services from the web server.")):
        create_and_publish(client, "PLACE_TOPIC", ssrf["id"], {"domain_id": domain, "map_branch": "vulnerabilities", "context_note": f"  {note}  "})
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeTopic).where(KnowledgeTopic.name == "Shared SSRF")) == 1
    placements = client.get(f"{MAP}/topics/{ssrf['topic_key']}/placements").json()
    assert sorted((item["domain_path"][-1]["id"], item["context_note"]) for item in placements) == sorted([(lambda_domain, "Reads local files and environment through file:// in Lambda."), (web_domain, "Reaches internal services from the web server.")])
    item = client.get(f"{MAP}/domains/{web_domain}/branches/vulnerabilities/topics").json()["items"][0]
    assert (item["topic_key"], item["placement_count"], item["context_note"]) == (ssrf["topic_key"], 2, "Reaches internal services from the web server.")

    # Re-placing without a note keeps it; a new note replaces it; "" clears it. Other domains are untouched.
    created = propose(client, "PLACE_TOPIC", ssrf["id"], {"domain_id": web_domain, "map_branch": "vulnerabilities"})
    assert "context_note" not in created.json()["proposed_content"]
    publish(client, review(client, created.json(), "approve"))
    notes = lambda: {item["domain_path"][-1]["id"]: item["context_note"] for item in client.get(f"{MAP}/topics/{ssrf['topic_key']}/placements").json()}
    assert notes()[web_domain] == "Reaches internal services from the web server."
    create_and_publish(client, "PLACE_TOPIC", ssrf["id"], {"domain_id": web_domain, "map_branch": "vulnerabilities", "context_note": "Server-side URL fetchers."})
    assert notes() == {lambda_domain: "Reads local files and environment through file:// in Lambda.", web_domain: "Server-side URL fetchers."}
    create_and_publish(client, "PLACE_TOPIC", ssrf["id"], {"domain_id": web_domain, "map_branch": "vulnerabilities", "context_note": ""})
    assert notes()[web_domain] is None and notes()[lambda_domain]

    assert propose(client, "PLACE_TOPIC", ssrf["id"], {"domain_id": web_domain, "map_branch": "vulnerabilities", "context_note": "x" * 2001}).status_code == 422
    assert propose(client, "PLACE_TOPIC", ssrf["id"], {"domain_id": web_domain, "map_branch": "vulnerabilities", "context_note": "<script>alert(1)</script>"}).status_code == 422


def test_create_topic_can_place_a_shared_topic_in_several_domains_with_notes(client):
    first, second = make_domain(), make_domain()
    name = unique("Shared XXE")
    created = propose(client, "CREATE_TOPIC", None, {"topic": {"name": name, "description": "XML external entities."}, "placements": [
        {"domain_id": first, "map_branch": "vulnerabilities", "context_note": "Python runtime XML parsers."},
        {"domain_id": second, "map_branch": "vulnerabilities"},
    ]}, topic_name=name)
    assert created.status_code == 201, created.text
    assert created.json()["proposed_content"]["placements"][1] == {"domain_id": second, "map_branch": "vulnerabilities", "display_order": None}
    publish(client, review(client, created.json(), "approve"))
    with SessionLocal() as db:
        topic = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.name == name))
        assert {(link.domain_id, link.context_note) for link in db.scalars(select(KnowledgeTopicDomain).where(KnowledgeTopicDomain.topic_id == topic.id))} == {(first, "Python runtime XML parsers."), (second, None)}
