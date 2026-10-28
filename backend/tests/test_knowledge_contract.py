from __future__ import annotations

from app.database import SessionLocal
from app.models import KnowledgeTopicProposal

ADMIN = {"X-Admin-API-Key": "test-admin-key"}


def existing_topic(client):
    topics = client.get("/api/v1/knowledge/topics", params={"search": "API Authorization"}).json()
    assert topics
    return topics[0]


def proposal_payload(topic_id: int, content: dict, *, action: str = "UPDATE_SECTION", section: str = "attack_surfaces", references=None):
    return {
        "schema_version": "1.0",
        "source_type": "manual",
        "topic_id": topic_id,
        "action": action,
        "section": section,
        "proposed_content": content,
        "change_reason": "Administrator clarified the reviewable technical guidance.",
        "references": references or [{"source_type": "technical_article", "title": "OAuth Security Guidance", "url": "https://example.com/oauth", "locator": "Section 3", "excerpt": "Use sender-constrained authorization flows."}],
    }


def approve_and_publish(client, proposal):
    approved = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/review", headers=ADMIN, json={"expected_version": proposal["version"], "action": "approve", "reviewer_note": "Reviewed against the supplied evidence."})
    assert approved.status_code == 200, approved.text
    published = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/publish", headers=ADMIN, json={"confirm": True, "expected_version": approved.json()["version"], "change_reason": "Published after administrator review."})
    assert published.status_code == 200, published.text
    return published.json()


def test_contract_requires_authentication_and_supports_idempotency(client):
    topic = existing_topic(client)
    payload = proposal_payload(topic["id"], {"items": [{"name": "Code interception", "weakness_description": "An authorization code may be intercepted.", "impact": "Unauthorized access."}]})
    assert client.post("/api/v1/knowledge/proposals", json=payload).status_code == 401
    first = client.post("/api/v1/knowledge/proposals", headers={**ADMIN, "Idempotency-Key": "oauth-attack-1"}, json=payload)
    second = client.post("/api/v1/knowledge/proposals", headers={**ADMIN, "Idempotency-Key": "oauth-attack-1"}, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["references"][0]["locator"] == "Section 3"
    with SessionLocal() as db:
        assert len(db.get(KnowledgeTopicProposal, first.json()["id"]).fingerprint) == 64



def test_scoped_integration_key_can_submit_and_read_status_but_not_review(client):
    from app.config import get_settings

    settings = get_settings()
    previous = settings.knowledge_integration_keys
    settings.knowledge_integration_keys = "integration-test-key"
    try:
        topic = existing_topic(client)
        payload = proposal_payload(topic["id"], {"items": [{"name": "Scoped integration surface"}]}, section="attack_surfaces")
        created = client.post("/api/v1/knowledge/proposals", headers={"X-Knowledge-Integration-Key": "integration-test-key"}, json=payload)
        assert created.status_code == 201, created.text
        proposal = created.json()
        status_response = client.get(f"/api/v1/knowledge/proposals/{proposal['id']}", headers={"X-Knowledge-Integration-Key": "integration-test-key"})
        assert status_response.status_code == 200
        review_response = client.post(f"/api/v1/knowledge/admin/proposals/{proposal['id']}/review", headers={"X-Knowledge-Integration-Key": "integration-test-key"}, json={"expected_version": proposal["version"], "action": "approve"})
        assert review_response.status_code == 401
    finally:
        settings.knowledge_integration_keys = previous


def test_section_publish_isolated_and_versioned(client):
    topic = existing_topic(client)
    original = client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}").json()
    payload = proposal_payload(topic["id"], {"items": [{"name": "Authorization code interception", "weakness_description": "An attacker intercepts a code.", "attack_scenario": "A redirect is observed.", "potential_impact": "Unauthorized access.", "related_vulnerability_classes": ["CWE-294"]}]})
    created = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=payload).json()
    published = approve_and_publish(client, created)
    assert published["status"] == "published"

    public = client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}")
    assert public.status_code == 200
    body = public.json()
    section = next(item for item in body["sections"] if item["section_type"] == "attack_surfaces")
    assert section["published_version"] == 1
    assert section["content"]["items"][0]["name"] == "Authorization code interception"
    assert body["description"] == original["description"]
    assert next(item for item in body["coverage"]["items"] if item["section_type"] == "attack_surfaces")["status"] == "published"

    changed = proposal_payload(topic["id"], {"items": [{"name": "Authorization code interception", "weakness_description": "Updated weakness explanation.", "attack_scenario": "A redirect is observed.", "potential_impact": "Unauthorized access.", "related_vulnerability_classes": ["CWE-294"]}]})
    second = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=changed).json()
    assert second["base_section_version"] == 1
    approve_and_publish(client, second)
    admin_topic = client.get(f"/api/v1/knowledge/admin/topics/{topic['id']}", headers=ADMIN).json()
    history = next(item for item in admin_topic["sections"] if item["section_type"] == "attack_surfaces")["versions"]
    assert {item["version"] for item in history} == {1, 2}
    assert history[0]["content"]["items"][0]["weakness_description"] == "Updated weakness explanation."


def test_unpublished_rejected_and_unverified_cve_content_never_reaches_public(client):
    topic = existing_topic(client)
    rejected = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(topic["id"], {"items": [{"name": "Rejected surface"}]})).json()
    response = client.post(f"/api/v1/knowledge/admin/proposals/{rejected['id']}/review", headers=ADMIN, json={"expected_version": rejected["version"], "action": "reject", "reviewer_note": "Unsupported claim."})
    assert response.status_code == 200
    assert client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}").status_code == 200
    assert all("Rejected surface" not in str(item) for item in client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}").json()["sections"])

    cve = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(topic["id"], {"items": [{"cve_identifier": "CVE-2099-0001", "title": "Unverified example"}],}, section="real_world_examples", references=[{"source_type": "cve", "title": "Unverified CVE feed", "url": "https://example.com/cve", "verification_status": "unverified"}])).json()
    approved = client.post(f"/api/v1/knowledge/admin/proposals/{cve['id']}/review", headers=ADMIN, json={"expected_version": cve["version"], "action": "approve"}).json()
    blocked = client.post(f"/api/v1/knowledge/admin/proposals/{cve['id']}/publish", headers=ADMIN, json={"confirm": True, "expected_version": approved["version"]})
    assert blocked.status_code == 409


def test_concurrent_section_publications_are_rejected(client):
    topic = existing_topic(client)
    first = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(topic["id"], {"short_description": "first"}, section="overview")).json()
    second = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(topic["id"], {"short_description": "second"}, section="overview")).json()
    assert first["base_section_version"] == second["base_section_version"]
    first_published = approve_and_publish(client, first)
    assert first_published["status"] == "published"
    approved_second = client.post(f"/api/v1/knowledge/admin/proposals/{second['id']}/review", headers=ADMIN, json={"expected_version": second["version"], "action": "approve"}).json()
    conflict = client.post(f"/api/v1/knowledge/admin/proposals/{second['id']}/publish", headers=ADMIN, json={"confirm": True, "expected_version": approved_second["version"]})
    assert conflict.status_code == 409


def test_coverage_reports_missing_sections_and_admin_pending_state(client):
    topic = existing_topic(client)
    public = client.get(f"/api/v1/knowledge/topics/{topic['topic_key']}/coverage")
    assert public.status_code == 200
    statuses = {item["section_type"]: item["status"] for item in public.json()["items"]}
    assert statuses["mitigations"] == "missing"
    proposal = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=proposal_payload(topic["id"], {"items": [{"control": "PKCE"}]}, section="mitigations")).json()
    admin = client.get(f"/api/v1/knowledge/admin/topics/{topic['id']}/coverage", headers=ADMIN)
    assert admin.status_code == 200
    assert next(item for item in admin.json()["items"] if item["section_type"] == "mitigations")["status"] == "pending_review"
    assert proposal["status"] == "review"


def test_create_topic_proposal_enters_review_before_publication(client):
    payload = {
        "schema_version": "1.0",
        "source_type": "rag",
        "topic_name": "OAuth 2.0 Review Contract Topic",
        "topic_key": "oauth-2-review-contract-topic",
        "action": "CREATE_TOPIC",
        "proposed_content": {"topic": {"name": "OAuth 2.0 Review Contract Topic", "description": "A reviewed topic."}, "short_description": "A reviewed topic."},
        "references": [{"source_type": "technical_article", "title": "OAuth reference", "url": "https://example.com/oauth"}],
    }
    created = client.post("/api/v1/knowledge/proposals", headers={**ADMIN, "Idempotency-Key": "create-oauth-contract-topic"}, json=payload)
    assert created.status_code == 201
    assert client.get("/api/v1/knowledge/topics/oauth-2-review-contract-topic").status_code == 404
    published = approve_and_publish(client, created.json())
    assert published["status"] == "published"
    assert client.get("/api/v1/knowledge/topics/oauth-2-review-contract-topic").status_code == 200


def test_integration_status_is_submitter_scoped_and_private_fields_are_redacted(client):
    from app.config import get_settings

    settings = get_settings()
    previous = settings.knowledge_integration_keys
    settings.knowledge_integration_keys = "integration-one,integration-two"
    try:
        topic = existing_topic(client)
        payload = proposal_payload(topic["id"], {"items": [{"name": "Scoped surface", "internal_notes": "do not disclose", "excerpt": "private embedded excerpt"}]}, references=[{"source_type": "technical_article", "title": "Private source", "url": "https://example.com/private", "access_scope": "private", "is_private": True, "verification_status": "authoritative", "excerpt": "private source excerpt"}])
        created = client.post("/api/v1/knowledge/proposals", headers={"X-Knowledge-Integration-Key": "integration-one"}, json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["references"][0]["verification_status"] == "unverified"
        assert body["references"][0]["excerpt"] is None
        assert body["review_decisions"] == []
        assert "internal_notes" not in str(body["proposed_content"])
        assert client.get(f"/api/v1/knowledge/proposals/{body['id']}", headers={"X-Knowledge-Integration-Key": "integration-two"}).status_code == 404
    finally:
        settings.knowledge_integration_keys = previous


def test_relationship_target_must_be_a_positive_integer(client):
    topic = existing_topic(client)
    payload = proposal_payload(topic["id"], {"target_topic_id": "not-an-id", "relationship_type": "related"}, action="ADD_TOPIC_RELATIONSHIP", section=None)
    response = client.post("/api/v1/knowledge/proposals", headers=ADMIN, json=payload)
    assert response.status_code == 422


def test_admin_review_endpoints_are_not_public(client):
    assert client.get("/api/v1/knowledge/admin/proposals").status_code == 401
    assert client.get("/api/v1/knowledge/admin/topics/1").status_code == 401
