from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import KnowledgeTopicSection
from tests.test_knowledge_contract import ADMIN, approve_and_publish, proposal_payload

VERIFIED_SOURCE = [{"source_type": "technical_article", "title": "Secure coding guidance", "url": "https://example.com/guide", "verification_status": "verified"}]

CODE_EXAMPLE = {
    "title": "Order lookup",
    "language": "python",
    "vulnerable": "return db.get(Order, order_id)",
    "secure": "return db.get(Order, order_id, owner=current_user)",
    "explanation": "The secure version scopes the lookup to the caller.",
    "security_control": "Object-level authorization",
}

DIAGRAM = {
    "kind": "sequence",
    "title": "Order lookup",
    "variant": "vulnerable",
    "nodes": [{"id": "user", "label": "User", "type": "actor", "boundary": "internet"}, {"id": "api", "label": "API", "type": "service"}],
    "edges": [{"from": "user", "to": "api", "label": "GET /orders/1002", "order": 1}],
    "boundaries": [{"id": "internet", "label": "Internet"}],
}


def topic_by_key(client, key: str) -> dict:
    response = client.get(f"/api/v1/knowledge/topics/{key}")
    assert response.status_code == 200, response.text
    return response.json()


def propose(client, topic_id: int, content: dict, *, section: str, action: str = "ADD_SECTION"):
    return client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(topic_id, content, action=action, section=section, references=VERIFIED_SOURCE))


def test_code_examples_and_architecture_publish_and_render(client):
    topic = topic_by_key(client, "api-authorization")
    code = propose(client, topic["id"], {"items": [CODE_EXAMPLE]}, section="code_examples")
    assert code.status_code == 201, code.text
    approve_and_publish(client, code.json())
    architecture = propose(client, topic["id"], {"diagrams": [DIAGRAM]}, section="architecture")
    assert architecture.status_code == 201, architecture.text
    approve_and_publish(client, architecture.json())
    added = propose(client, topic["id"], {"diagram": {**DIAGRAM, "variant": "secure"}}, section="architecture", action="ADD_DIAGRAM")
    assert added.status_code == 201, added.text
    approve_and_publish(client, added.json())

    body = topic_by_key(client, "api-authorization")
    sections = {item["section_type"]: item["content"] for item in body["sections"]}
    assert sections["code_examples"]["items"][0]["security_control"] == "Object-level authorization"
    assert [diagram["variant"] for diagram in sections["architecture"]["diagrams"]] == ["vulnerable", "secure"]
    assert sections["architecture"]["diagrams"][0]["edges"][0] == {"from": "user", "to": "api", "label": "GET /orders/1002", "order": 1}
    # Optional sections do not count against coverage.
    assert {item["section_type"] for item in body["coverage"]["items"]} == {"overview", "how_it_works", "attack_surfaces", "mitigations", "real_world_examples", "references", "career_level_guidance"}


@pytest.mark.parametrize(("section", "content"), [
    ("code_examples", {"items": [{**CODE_EXAMPLE, "colour": "red"}]}),
    ("code_examples", {"items": [{**CODE_EXAMPLE, "vulnerable": "x" * 8001}]}),
    ("code_examples", {"items": [{**CODE_EXAMPLE, "language": "brainfuck"}]}),
    ("code_examples", {"items": [CODE_EXAMPLE] * 7}),
    ("code_examples", {"items": [{**CODE_EXAMPLE, "secure": "<script>alert(1)</script>"}]}),
    ("code_examples", {"items": [{**CODE_EXAMPLE, "reference": "javascript:alert(1)"}]}),
    ("architecture", {"diagrams": [{**DIAGRAM, "edges": [{"from": "user", "to": "database"}]}]}),
    ("architecture", {"diagrams": [{**DIAGRAM, "style": "fill:red"}]}),
    ("architecture", {"diagrams": [{**DIAGRAM, "nodes": [{"id": "user", "label": "User", "url": "https://example.com"}]}]}),
    ("architecture", {"diagrams": [{**DIAGRAM, "nodes": [{"id": "User Node", "label": "User"}], "edges": []}]}),
    ("architecture", {"diagrams": [{**DIAGRAM, "title": "<b>bold</b>"}]}),
    ("architecture", {"diagrams": [{**DIAGRAM, "nodes": [{"id": f"n{index}", "label": "N"} for index in range(41)], "edges": []}]}),
    ("how_it_works", {"workflow": "Flow", "diagram": {"nodes": [{"id": "a", "label": "A"}], "edges": [{"from": "a", "to": "b"}]}}),
])
def test_invalid_structured_content_is_rejected(client, section, content):
    topic = topic_by_key(client, "api-authorization")
    response = propose(client, topic["id"], content, section=section)
    assert response.status_code == 422, response.text


def test_new_sections_reject_item_append_actions(client):
    topic = topic_by_key(client, "api-authorization")
    response = propose(client, topic["id"], {"item": CODE_EXAMPLE}, section="code_examples", action="ADD_MITIGATION")
    assert response.status_code == 422


def test_reviewer_modification_is_validated(client):
    topic = topic_by_key(client, "api-authorization")
    proposal = propose(client, topic["id"], {"items": [CODE_EXAMPLE]}, section="code_examples").json()
    response = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": "modify", "proposed_content": {"items": [{**CODE_EXAMPLE, "language": "cobol"}]}})
    assert response.status_code == 422


def test_legacy_topic_without_new_sections_and_invalid_legacy_diagram_still_render(client):
    topic = topic_by_key(client, "chain-of-trust")
    assert all(item["section_type"] not in {"code_examples", "architecture"} for item in topic["sections"])
    with SessionLocal() as db:
        db.add(KnowledgeTopicSection(topic_id=topic["id"], section_type="how_it_works", published_content={"workflow": "Legacy flow", "diagram": {"nodes": ["a", "b"], "edges": [["a", "b"]]}}, published_version=1, status="published"))
        db.add(KnowledgeTopicSection(topic_id=topic["id"], section_type="architecture", published_content={"diagrams": [DIAGRAM, {"nodes": [{"id": "a"}], "script": "x"}]}, published_version=1, status="published"))
        db.commit()
    body = topic_by_key(client, "chain-of-trust")
    sections = {item["section_type"]: item["content"] for item in body["sections"]}
    assert sections["how_it_works"]["workflow"] == "Legacy flow"
    assert sections["how_it_works"]["diagram"] is None and sections["how_it_works"]["diagram_hidden"] is True
    assert len(sections["architecture"]["diagrams"]) == 1 and sections["architecture"]["hidden_diagram_count"] == 1


def relationship(client, source: dict, target: dict, relationship_type: str):
    return client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(source["id"], {"target_topic_id": target["id"], "relationship_type": relationship_type}, action="ADD_TOPIC_RELATIONSHIP", section=None))


def test_relationship_types_and_inverse_labels(client):
    authorization = topic_by_key(client, "api-authorization")
    testing = topic_by_key(client, "penetration-testing")
    containers = topic_by_key(client, "container-security")
    for source, target, kind in ((authorization, testing, "tested_by"), (containers, authorization, "mitigated_by"), (containers, testing, "dependency")):
        response = relationship(client, source, target, kind)
        assert response.status_code == 201, response.text
        approve_and_publish(client, response.json())

    related = {(item["topic_key"], item["direction"]): item["label"] for item in topic_by_key(client, "api-authorization")["related_topics"]}
    assert related[("penetration-testing", "outgoing")] == "Tested by"
    assert related[("container-security", "incoming")] == "Protects against"
    testing_related = {(item["topic_key"], item["direction"]): item["label"] for item in topic_by_key(client, "penetration-testing")["related_topics"]}
    assert testing_related[("api-authorization", "incoming")] == "Tests"
    assert testing_related[("container-security", "incoming")] == "Used by"


def test_relationship_rejects_unknown_types_and_self_links(client):
    topic = topic_by_key(client, "api-authorization")
    other = topic_by_key(client, "secure-boot")
    assert relationship(client, topic, other, "blocks").status_code == 422
    assert relationship(client, topic, topic, "related").status_code == 422
