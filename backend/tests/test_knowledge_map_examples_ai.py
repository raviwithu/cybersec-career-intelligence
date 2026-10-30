from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.knowledge_map_examples import run
from app.models import (
    KnowledgeProposalSource,
    KnowledgeTopic,
    KnowledgeTopicDomain,
    KnowledgeTopicLevel,
    KnowledgeTopicProposal,
    KnowledgeTopicRelationship,
    KnowledgeTopicSection,
    ResearchFinding,
    ResearchSource,
    ResearchSubmission,
    ReviewChange,
    SecurityDomain,
)

ADMIN = {"X-Admin-API-Key": "test-admin-key"}


@pytest.fixture(autouse=True)
def _remove_created_rows(client):
    # Shared test database: remove the topics, proposals and findings each test adds (SQLite reuses deleted ids).
    with SessionLocal() as db:
        last_topic = db.scalar(select(func.max(KnowledgeTopic.id))) or 0
        last_proposal = db.scalar(select(func.max(KnowledgeTopicProposal.id))) or 0
        last_submission = db.scalar(select(func.max(ResearchSubmission.id))) or 0
        last_source = db.scalar(select(func.max(ResearchSource.id))) or 0
        seeded_links = set(db.execute(select(KnowledgeTopicDomain.topic_id, KnowledgeTopicDomain.domain_id, KnowledgeTopicDomain.map_branch)).all())
    yield
    with SessionLocal() as db:
        db.execute(delete(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id > last_proposal))
        db.execute(delete(KnowledgeTopic).where(KnowledgeTopic.id > last_topic))
        db.execute(delete(ResearchSubmission).where(ResearchSubmission.id > last_submission))
        db.execute(delete(ResearchSource).where(ResearchSource.id > last_source))
        for link in db.scalars(select(KnowledgeTopicDomain)).all():
            if (link.topic_id, link.domain_id, link.map_branch) not in seeded_links and link.map_branch is not None:
                link.map_branch = None
        db.commit()


def published_state(db) -> dict:
    return {
        "topics": db.scalar(select(func.count()).select_from(KnowledgeTopic)),
        "sections": db.scalar(select(func.count()).select_from(KnowledgeTopicSection)),
        "placements": db.scalar(select(func.count()).select_from(KnowledgeTopicDomain).where(KnowledgeTopicDomain.map_branch.is_not(None))),
        "relationships": db.scalar(select(func.count()).select_from(KnowledgeTopicRelationship)),
        "levels": db.scalar(select(func.count()).select_from(KnowledgeTopicLevel)),
    }


def approve_and_publish(client, proposal_id: int) -> None:
    proposal = client.get(f"/api/v1/knowledge/proposals/{proposal_id}", headers=ADMIN).json()
    reviewed = client.post(f"/api/v1/knowledge/admin/proposals/{proposal_id}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": "approve", "verified_source_ids": [item["id"] for item in proposal["references"]]})
    assert reviewed.status_code == 200, reviewed.text
    published = client.post(f"/api/v1/knowledge/admin/proposals/{proposal_id}/publish", headers=ADMIN, json={"confirm": True, "expected_version": reviewed.json()["version"]})
    assert published.status_code == 200, published.text


def test_example_script_creates_proposals_only_and_is_idempotent(client):
    with SessionLocal() as db:
        before = published_state(db)
        first = run(db)
        assert first.created > 0
        assert not [line for line in first.log if line.startswith("skipped")], first.log
        assert published_state(db) == before
        proposals = db.scalar(select(func.count()).select_from(KnowledgeTopicProposal))
        second = run(db)
        assert second.created == 0 and second.existing == first.created
        assert db.scalar(select(func.count()).select_from(KnowledgeTopicProposal)) == proposals
        assert published_state(db) == before
        sources = {item.source_type for item in db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.idempotency_key.is_not(None))).all()}
        assert "manual" in sources


def test_example_script_reuses_existing_topics_and_completes_after_publication(client):
    with SessionLocal() as db:
        # An existing topic under one of the example's aliases is reused instead of duplicated.
        ssrf = KnowledgeTopic(name="Server-Side Request Forgery", slug=f"ssrf-existing-{uuid.uuid4().hex[:6]}", topic_key=f"ssrf-existing-{uuid.uuid4().hex[:6]}", publication_status="published", is_active=True, version=1, published_at=datetime.now(timezone.utc))
        db.add(ssrf)
        db.commit()
        ssrf_id = ssrf.id
        start = db.scalar(select(func.max(KnowledgeTopicProposal.id))) or 0
        first = run(db)
        actions = {(item.action, item.topic_id) for item in db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id > start)).all()}
        secure_boot = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.topic_key == "secure-boot"))
        assert ("PLACE_TOPIC", secure_boot.id) in actions
        assert ("PLACE_TOPIC", ssrf_id) in actions
        assert db.scalar(select(func.count()).select_from(KnowledgeTopic).where(func.lower(KnowledgeTopic.name).like("%request forgery%"))) == 1
        creates = db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.action == "CREATE_TOPIC", KnowledgeTopicProposal.id > start)).all()
        names = {item.proposed_content["topic"]["name"] for item in creates}
        assert names == {"IDOR / BOLA", "OAuth 2.0", "Firmware Signature Verification"}
        create_ids = [item.id for item in creates]
        assert any("reuse" in line for line in first.log)

    for proposal_id in create_ids:
        approve_and_publish(client, proposal_id)
    placements = client.get("/api/v1/knowledge-map/topics/idor-bola/placements").json()
    assert {item["branch"] for item in placements} == {"vulnerabilities"} and len(placements) == 2

    with SessionLocal() as db:
        second = run(db)
        assert not [line for line in second.log if line.startswith("skipped")], second.log
        idor = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.topic_key == "idor-bola"))
        idor_actions = {(item.action, item.section_type) for item in db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.topic_id == idor.id)).all()}
        assert {("ADD_SECTION", "code_examples"), ("ADD_SECTION", "architecture"), ("UPDATE_CAREER_LEVELS", None), ("ADD_TOPIC_RELATIONSHIP", None)} <= idor_actions
        code = db.scalar(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.topic_id == idor.id, KnowledgeTopicProposal.section_type == "code_examples"))
        code_id = code.id
        idor_key = idor.topic_key
        assert idor.aliases == ["IDOR", "BOLA", "Insecure Direct Object Reference", "Broken Object Level Authorization"]
        assert run(db).created == 0
    approve_and_publish(client, code_id)
    body = client.get(f"/api/v1/knowledge/topics/{idor_key}").json()
    assert next(item for item in body["sections"] if item["section_type"] == "code_examples")["content"]["items"][0]["security_control"] == "Object-level authorization"


def make_finding(*, status: str = "accepted", domain_slug: str = "cloud-api-security") -> int:
    with SessionLocal() as db:
        domain = db.scalar(select(SecurityDomain).where(SecurityDomain.slug == domain_slug))
        source = ResearchSource(source_type="jsearch", source_url="https://jobs.example/cloud-native-api", source_title="Cloud API engineer", collected_at=datetime.now(timezone.utc))
        submission = ResearchSubmission(source=source, source_type="jsearch", content_sha256=uuid.uuid4().hex + uuid.uuid4().hex, content_size=80, status="draft_ready")
        finding = ResearchFinding(submission=submission, domain_id=domain.id, candidate_name="Experience securing cloud-native APIs", normalized_name="Experience securing cloud-native APIs", finding_type="practical-capability", technical_knowledge="OAuth, API gateways and authorization.", practical_capability="Secure cloud-native APIs.", evidence_excerpt="Experience securing cloud-native APIs and API authorization.", confidence=0.8, status="normalized")
        db.add(finding)
        db.flush()
        db.add(ReviewChange(submission_id=submission.id, finding_id=finding.id, change_type="create", status=status, original_snapshot={}, proposed_snapshot={}))
        db.commit()
        return finding.id


@pytest.fixture
def model(monkeypatch):
    import app.knowledge_map_suggestions as suggestions

    state = {"output": "[]", "calls": []}

    def complete(provider, model_id, system, prompt, timeout=None):
        state["calls"].append({"provider": provider, "model_id": model_id, "system": system, "prompt": prompt})
        return state["output"]

    monkeypatch.setattr(suggestions.providers, "complete_selected", complete)
    monkeypatch.setattr(suggestions.model_selection, "active_selection", lambda db: ("ollama", "test-model", "test-model"))
    return state


def ids():
    with SessionLocal() as db:
        cloud = db.scalar(select(SecurityDomain.id).where(SecurityDomain.slug == "cloud-api-security"))
        embedded = db.scalar(select(SecurityDomain.id).where(SecurityDomain.slug == "boot-security"))
        authz = db.scalar(select(KnowledgeTopic.id).where(KnowledgeTopic.topic_key == "api-authorization"))
        testing = db.scalar(select(KnowledgeTopic.id).where(KnowledgeTopic.topic_key == "penetration-testing"))
    return cloud, embedded, authz, testing


def test_map_suggestions_validate_model_output_and_write_nothing(client, model):
    finding_id = make_finding()
    cloud, embedded, authz, testing = ids()
    model["output"] = "```json\n" + json.dumps([
        {"action": "PLACE_TOPIC", "existing_topic_id": authz, "name": None, "domain_id": cloud, "map_branch": "security", "rationale": "Employers expect API authorization skills."},
        {"action": "CREATE_TOPIC", "existing_topic_id": None, "name": "API Gateway Security", "domain_id": cloud, "map_branch": "security", "rationale": "Gateways appear in the finding."},
        {"action": "CREATE_TOPIC", "name": "api authorization", "domain_id": cloud, "map_branch": "security", "rationale": "Duplicate of an existing topic."},
        {"action": "ADD_TOPIC_RELATIONSHIP", "existing_topic_id": authz, "related_topic_id": testing, "relationship_type": "tested_by", "domain_id": cloud, "map_branch": "security", "rationale": "Testing validates authorization."},
        {"action": "PLACE_TOPIC", "existing_topic_id": authz, "domain_id": cloud, "map_branch": "security", "rationale": "Extra key.", "colour": "red"},
        {"action": "PLACE_TOPIC", "existing_topic_id": 999999, "domain_id": cloud, "map_branch": "security", "rationale": "Unknown topic."},
        {"action": "PLACE_TOPIC", "existing_topic_id": authz, "domain_id": embedded, "map_branch": "security", "rationale": "Out-of-scope domain."},
        {"action": "CREATE_TOPIC", "name": "Unsafe <script>alert(1)</script>", "domain_id": cloud, "map_branch": "security", "rationale": "Markup."},
    ]) + "\n```"
    with SessionLocal() as db:
        before = (db.scalar(select(func.count()).select_from(KnowledgeTopicProposal)), published_state(db))
    response = client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions", headers=ADMIN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["action"] for item in body["suggestions"]] == ["PLACE_TOPIC", "CREATE_TOPIC", "PLACE_TOPIC", "ADD_TOPIC_RELATIONSHIP"]
    assert body["suggestions"][2]["existing_topic_id"] == authz and "existing topic" in body["suggestions"][2]["note"]
    assert body["suggestions"][3]["related_topic_name"] == "Penetration Testing"
    assert len(body["warnings"]) == 4
    prompt = model["calls"][0]["prompt"]
    assert "API Authorization" in prompt and "Experience securing cloud-native APIs" in prompt
    with SessionLocal() as db:
        assert (db.scalar(select(func.count()).select_from(KnowledgeTopicProposal)), published_state(db)) == before

    model["output"] = "Sure! Here are some ideas: place API Authorization."
    invalid = client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions", headers=ADMIN)
    assert invalid.status_code == 502
    model["output"] = json.dumps({"action": "PLACE_TOPIC"})
    assert client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions", headers=ADMIN).status_code == 502
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeTopicProposal)) == before[0]


def test_suggestions_need_an_approved_finding(client, model):
    pending = make_finding(status="pending")
    assert client.post(f"/api/v1/knowledge/admin/findings/{pending}/map-suggestions", headers=ADMIN).status_code == 409
    assert client.post("/api/v1/knowledge/admin/findings/999999/map-suggestions", headers=ADMIN).status_code == 404
    assert model["calls"] == []
    listed = client.get("/api/v1/knowledge/admin/findings", headers=ADMIN).json()
    assert pending not in {item["id"] for item in listed}


def test_submitting_selected_suggestions_creates_ai_proposals_linked_to_the_finding(client, model):
    finding_id = make_finding()
    cloud, _, authz, testing = ids()
    selected = [
        {"action": "PLACE_TOPIC", "existing_topic_id": authz, "domain_id": cloud, "map_branch": "security", "rationale": "Employers expect API authorization skills."},
        {"action": "CREATE_TOPIC", "name": "API Gateway Security", "domain_id": cloud, "map_branch": "security", "rationale": "Gateways appear in the finding."},
        {"action": "ADD_TOPIC_RELATIONSHIP", "existing_topic_id": authz, "related_topic_id": testing, "relationship_type": "tested_by", "domain_id": cloud, "map_branch": "security", "rationale": "Testing validates authorization."},
    ]
    response = client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions/submit", headers=ADMIN, json={"suggestions": selected})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == []
    assert [item["action"] for item in body["created"]] == ["PLACE_TOPIC", "CREATE_TOPIC", "ADD_TOPIC_RELATIONSHIP"]
    assert all(item["source_type"] == "ai" and item["status"] == "review" for item in body["created"])
    create = body["created"][1]
    assert create["proposed_content"]["topic"] == {"name": "API Gateway Security", "description": "", "topic_key": "api-gateway-security"}
    assert create["proposed_content"]["placements"] == [{"domain_id": cloud, "map_branch": "security", "display_order": None}]
    with SessionLocal() as db:
        rows = db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.id.in_([item["id"] for item in body["created"]]))).all()
        assert {row.finding_id for row in rows} == {finding_id}
        sources = db.scalars(select(KnowledgeProposalSource).where(KnowledgeProposalSource.proposal_id == rows[0].id)).all()
        assert sources[0].excerpt.startswith("Experience securing cloud-native APIs") and sources[0].verification_status == "unverified"
    again = client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions/submit", headers=ADMIN, json={"suggestions": selected})
    assert [item["id"] for item in again.json()["created"]] == [item["id"] for item in body["created"]]
    assert model["calls"] == []


def test_suggestion_endpoints_require_the_admin_key(client, model):
    finding_id = make_finding()
    assert client.get("/api/v1/knowledge/admin/findings").status_code in (401, 403)
    assert client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions").status_code in (401, 403)
    assert client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions/submit", json={"suggestions": []}).status_code in (401, 403, 422)
    assert client.post(f"/api/v1/knowledge/admin/findings/{finding_id}/map-suggestions/submit", headers={"X-Admin-API-Key": "wrong"}, json={"suggestions": [{"action": "PLACE_TOPIC", "existing_topic_id": 1, "domain_id": 1, "map_branch": "security", "rationale": "x"}]}).status_code in (401, 403)
    assert model["calls"] == []
