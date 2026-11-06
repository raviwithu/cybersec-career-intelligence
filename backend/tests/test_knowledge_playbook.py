from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.knowledge_content_schemas import validate_section_content
from app.knowledge_contract_schemas import CORE_SECTION_TYPES, PLAYBOOK_SECTION_TYPES, KnowledgeProposalCreate
from app.knowledge_map_example_content import EXAMPLE_TOPICS
from app.models import CareerLevel, KnowledgeTopic, KnowledgeTopicLevel, KnowledgeTopicRelationship, KnowledgeTopicSection
from tests.test_knowledge_content import CODE_EXAMPLE, propose
from tests.test_knowledge_contract import ADMIN, approve_and_publish
from tests.test_knowledge_map import MAP, _domain, _place, _remove_created_rows, _topic  # noqa: F401

SOURCE_REVIEW = {
    "entry_points": ["Query strings and JSON bodies"],
    "dangerous_sinks": ["Queries built by concatenation"],
    "search_patterns": [{"language": "Python", "pattern": 'execute(f"'}],
    "easy_to_miss": ["ORDER BY, which placeholders cannot protect"],
}
DYNAMIC_REVIEW = {"steps": [{"title": "Compare responses", "action": "Change the input in harmless ways.", "look_for": "Differences that track the change."}], "evidence": ["Request and response pairs"]}
INFORMATION_GATHERING = {
    "issue_checks": [{"what": "Entry points", "how": "API spec", "tells": "Which inputs to test."}],
    "mitigation_checks": [{"what": "Prepared statements", "how": "Database log", "tells": "Whether binding happens at runtime."}],
}
AI_CICD_SKILL = {
    "skill_id": "sqli-source-review", "summary": "Scans changed code on every pull request.",
    "inputs": ["The pull request diff"], "outputs": ["SARIF report"], "gate_policy": ["A person confirms each block"],
    "pipelines": [{"system": "GitHub Actions", "file_name": ".github/workflows/scan.yml", "content": "on: pull_request"}],
    "example_finding": {"location": "orders.py:4", "explanation": "Input reaches the query text.", "suggested_fix": "Bind the value."},
}
AI_DYNAMIC_SKILL = {
    "skill_id": "sqli-dynamic-analysis", "summary": "Changes with the access you have.", "guardrails": ["Authorised targets only"],
    "access_levels": [{"access": "remote", "needs": ["Written permission"], "steps": ["Compare responses at a low rate"], "can_prove": ["Behaviour changes"], "cannot_see": ["The cause"]}],
}
CONTENT = {"source_review": SOURCE_REVIEW, "dynamic_review": DYNAMIC_REVIEW, "information_gathering": INFORMATION_GATHERING, "ai_cicd_skill": AI_CICD_SKILL, "ai_dynamic_skill": AI_DYNAMIC_SKILL}


def _map_topic(domain_name: str = "Playbook Domain", *, under: bool = False) -> tuple[int, int, str]:
    """A published topic on the map, directly under a domain or in a parent topic's Common Vulnerabilities branch."""
    with SessionLocal() as db:
        domain = _domain(db, domain_name)
        topic = _topic(db, "Playbook Vulnerability")
        if under:
            parent = _topic(db, "Playbook Parent")
            _place(db, parent, domain)
            _place(db, topic, domain, "vulnerabilities", under=parent)
        else:
            _place(db, topic, domain)
        db.commit()
        return domain.id, topic.id, topic.topic_key


def _publish(client, topic_id: int, section: str, content: dict) -> None:
    response = propose(client, topic_id, content, section=section)
    assert response.status_code == 201, response.text
    approve_and_publish(client, response.json())


def _sections(client, domain_id: int, topic_id: int) -> list[str]:
    response = client.get(f"{MAP}/domains/{domain_id}/topics/{topic_id}/children")
    assert response.status_code == 200, response.text
    return response.json()["sections"]


@pytest.mark.parametrize("section", list(CONTENT))
def test_playbook_sections_publish_through_the_existing_workflow(client, section):
    _, topic_id, key = _map_topic()
    _publish(client, topic_id, section, CONTENT[section])
    published = {item["section_type"]: item["content"] for item in client.get(f"/api/v1/knowledge/topics/{key}").json()["sections"]}
    assert published[section] == CONTENT[section]


@pytest.mark.parametrize(("section", "content"), [
    ("source_review", {**SOURCE_REVIEW, "colour": "red"}),
    ("source_review", {**SOURCE_REVIEW, "search_patterns": [{"language": "Python"}]}),
    ("dynamic_review", {"steps": [], "evidence": []}),
    ("dynamic_review", {"steps": [{"title": "No action"}]}),
    ("information_gathering", {"issue_checks": [{"what": "Only what"}]}),
    ("ai_cicd_skill", {**AI_CICD_SKILL, "skill_id": "Not A Slug"}),
    ("ai_cicd_skill", {**AI_CICD_SKILL, "pipelines": []}),
    ("ai_dynamic_skill", {**AI_DYNAMIC_SKILL, "guardrails": []}),
    ("ai_dynamic_skill", {**AI_DYNAMIC_SKILL, "access_levels": [{"access": "physical", "steps": ["Step"]}]}),
    ("ai_dynamic_skill", {**AI_DYNAMIC_SKILL, "access_levels": AI_DYNAMIC_SKILL["access_levels"] * 2}),
    ("source_review", {**SOURCE_REVIEW, "easy_to_miss": ["<script>alert(1)</script>"]}),
])
def test_invalid_playbook_content_is_rejected(client, section, content):
    _, topic_id, _ = _map_topic()
    assert propose(client, topic_id, content, section=section).status_code == 422


def test_reviewer_changes_to_a_playbook_section_are_revalidated(client):
    _, topic_id, _ = _map_topic()
    proposal = propose(client, topic_id, SOURCE_REVIEW, section="source_review").json()
    modified = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": "modify", "proposed_content": {"unknown": True}})
    assert modified.status_code == 422


def test_playbook_section_that_no_longer_validates_is_hidden_on_read(client):
    _, topic_id, key = _map_topic()
    _publish(client, topic_id, "dynamic_review", DYNAMIC_REVIEW)
    with SessionLocal() as db:
        section = db.query(KnowledgeTopicSection).filter_by(topic_id=topic_id, section_type="dynamic_review").one()
        section.published_content = {"steps": "not a list"}
        db.commit()
    published = {item["section_type"]: item["content"] for item in client.get(f"/api/v1/knowledge/topics/{key}").json()["sections"]}
    assert published["dynamic_review"] == {"content_hidden": True}


@pytest.mark.parametrize("under", [False, True])
def test_map_sections_list_published_content_in_order_wherever_the_topic_sits(client, under):
    domain_id, topic_id, _ = _map_topic(under=under)
    assert _sections(client, domain_id, topic_id) == []
    _publish(client, topic_id, "ai_dynamic_skill", AI_DYNAMIC_SKILL)
    _publish(client, topic_id, "mitigations", {"items": [{"control": "Bind values", "description": "Keep values out of the SQL text."}]})
    _publish(client, topic_id, "overview", {"short_description": "Input becomes SQL."})
    _publish(client, topic_id, "references", {"items": [{"title": "CWE-89", "url": "https://cwe.mitre.org/data/definitions/89.html"}]})
    assert _sections(client, domain_id, topic_id) == ["overview", "mitigations", "ai_dynamic_skill", "references"]


def test_map_sections_exclude_unpublished_sections(client):
    domain_id, topic_id, _ = _map_topic()
    assert propose(client, topic_id, SOURCE_REVIEW, section="source_review").status_code == 201
    assert _sections(client, domain_id, topic_id) == []


def test_map_sections_skip_an_architecture_section_without_diagrams(client):
    domain_id, topic_id, _ = _map_topic()
    _publish(client, topic_id, "architecture", {"diagrams": []})
    assert _sections(client, domain_id, topic_id) == []


def test_map_sections_include_career_levels_only_for_active_levels(client):
    domain_id, topic_id, _ = _map_topic()
    with SessionLocal() as db:
        level = CareerLevel(name=f"Retired {topic_id}", slug=f"retired-{topic_id}", display_order=99, is_active=False)
        db.add(level)
        db.flush()
        row = KnowledgeTopicLevel(topic_id=topic_id, career_level_id=level.id, expectation="Know it.")
        db.add(row)
        db.commit()
        level_id, row_id = level.id, row.id
    try:
        assert _sections(client, domain_id, topic_id) == []
        with SessionLocal() as db:
            db.get(CareerLevel, level_id).is_active = True
            db.commit()
        assert _sections(client, domain_id, topic_id) == ["career_levels"]
    finally:
        with SessionLocal() as db:
            db.delete(db.get(KnowledgeTopicLevel, row_id))
            db.delete(db.get(CareerLevel, level_id))
            db.commit()


@pytest.mark.parametrize("incoming", [False, True])
def test_map_sections_include_related_topics_in_either_direction_when_published(client, incoming):
    domain_id, topic_id, _ = _map_topic()
    with SessionLocal() as db:
        draft = _topic(db, "Unpublished Neighbour", status="draft")
        source, target = (draft.id, topic_id) if incoming else (topic_id, draft.id)
        db.add(KnowledgeTopicRelationship(source_topic_id=source, target_topic_id=target, relationship_type="related"))
        db.commit()
        draft_id = draft.id
    assert _sections(client, domain_id, topic_id) == []
    with SessionLocal() as db:
        db.get(KnowledgeTopic, draft_id).publication_status = "published"
        db.commit()
    assert _sections(client, domain_id, topic_id) == ["related"]


def test_coverage_reports_the_playbook_without_changing_completeness(client):
    _, topic_id, key = _map_topic()
    _publish(client, topic_id, "source_review", SOURCE_REVIEW)
    assert propose(client, topic_id, DYNAMIC_REVIEW, section="dynamic_review").status_code == 201
    public = client.get(f"/api/v1/knowledge/topics/{key}/coverage").json()
    assert [item["section_type"] for item in public["items"]] == list(CORE_SECTION_TYPES)
    assert public["complete"] is False
    assert [item["section_type"] for item in public["playbook_items"]] == list(PLAYBOOK_SECTION_TYPES)
    admin = client.get(f"/api/v1/knowledge/admin/topics/{topic_id}/coverage", headers=ADMIN).json()
    statuses = {item["section_type"]: item["status"] for item in admin["playbook_items"]}
    assert statuses["source_review"] == "published" and statuses["dynamic_review"] == "pending_review" and statuses["ai_cicd_skill"] == "missing"


def test_publishing_a_playbook_section_changes_the_map_etag(client):
    _, topic_id, _ = _map_topic()
    before = client.get(MAP).headers["etag"]
    _publish(client, topic_id, "source_review", SOURCE_REVIEW)
    assert client.get(MAP).headers["etag"] != before


def test_sql_injection_example_has_a_valid_section_for_every_playbook_entry():
    sections = next(item for item in EXAMPLE_TOPICS if item["topic_key"] == "sql-injection")["sections"]
    assert set(PLAYBOOK_SECTION_TYPES) <= set(sections)
    for section_type, content in sections.items():
        validate_section_content(section_type, "ADD_SECTION", content)
        KnowledgeProposalCreate(source_type="manual", topic_id=1, action="ADD_SECTION", section=section_type, proposed_content=content)
    assert {item["language"] for item in sections["code_examples"]["items"]} == {"python", "java", "javascript", "php"}
    assert {item["access"] for item in sections["ai_dynamic_skill"]["access_levels"]} == {"binary", "system", "remote"}
