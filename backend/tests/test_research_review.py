from datetime import datetime, timezone

import pytest

from app.phase5_api import providers
from app.phase5_schemas import ExtractedRequirement, ExtractionResult
from app.models import Competency, DomainLevelExpectation, ExpectationRevision

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


def result_for(content: str) -> ExtractionResult:
    requirements = [
        ExtractedRequirement(
            domain_slugs=["boot-security", "hardware-security"], career_level="architect",
            competency_name="Firmware Integrity Controls", category_slug="security-architecture",
            technical_knowledge="Firmware trust anchors", practical_capability="Design firmware integrity controls.",
            qualifications="Secure boot experience", tools_technologies="TPM", responsibilities="Lead firmware reviews.",
            finding_type="security-architecture", evidence_excerpt="The role requires firmware integrity controls.", confidence=None,
        ),
        ExtractedRequirement(
            domain_slugs=["boot-security"], career_level="architect", competency_name="Secure Boot",
            category_slug="security-architecture", technical_knowledge="Secure boot policy review",
            practical_capability="Design and evaluate verified startup.", responsibilities="Review startup trust.",
            finding_type="technical-knowledge", evidence_excerpt="Design secure boot policy and review startup trust.", confidence=0.91,
        ),
        ExtractedRequirement(
            domain_slugs=["hardware-security"], career_level="architect", competency_name="Firmware Integrity Controls",
            category_slug="security-architecture", technical_knowledge="Hardware-backed verification",
            practical_capability="Use hardware-backed verification.", responsibilities="Lead hardware trust reviews.",
            finding_type="technical-skills", evidence_excerpt="Use hardware-backed verification for device trust.", confidence=None,
        ),
        ExtractedRequirement(
            domain_slugs=["operating-system-security"], career_level="senior", competency_name="Unsupported Classification",
            category_slug=None, technical_knowledge="Unclear requirement", practical_capability="",
            responsibilities="", finding_type="qualifications", evidence_excerpt="An ambiguous requirement needs manual classification.", confidence=None,
        ),
    ]
    return ExtractionResult(requirements=requirements if "review" in content else requirements[:1])


def submit_review_source(client, monkeypatch, content="review lifecycle source"):
    monkeypatch.setattr(providers, "extract_selected", lambda provider, model_id, content, taxonomy: result_for(content))
    response = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json={"content": content, "source_title": "Review source", "source_url": "https://example.test/review"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_review_dashboard_requires_admin(client):
    assert client.get("/api/v1/research/review/dashboard").status_code == 401


def test_review_lifecycle_impact_actions_and_publication_are_audited(client, monkeypatch):
    submission_id = submit_review_source(client, monkeypatch)
    detail = client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["findings"]) == 4
    assert len(body["domain_impact"]) == 3
    firmware = next(item for item in body["findings"] if item["candidate_name"] == "Firmware Integrity Controls")
    secure_boot = next(item for item in body["findings"] if item["candidate_name"] == "Secure Boot")
    manual = next(item for item in body["findings"] if item["candidate_name"] == "Unsupported Classification")
    assert firmware["confidence"] is None
    assert firmware["confidence_meaningful"] is False
    assert firmware["existing_matches"] == []
    assert secure_boot["existing_matches"]
    assert "category" in manual["classification_gaps"]

    firmware_change = firmware["review_change"]
    secure_change = secure_boot["review_change"]
    manual_change = manual["review_change"]
    firmware_id = firmware_change["id"]
    secure_id = secure_change["id"]
    manual_id = manual_change["id"]

    comparison = client.get(f"/api/v1/research/review/changes/{secure_id}/comparison", headers=ADMIN_HEADERS)
    assert comparison.status_code == 200
    assert comparison.json()["differences"]["additions"]

    accepted = client.post(f"/api/v1/research/review/changes/{firmware_id}/accept", headers=ADMIN_HEADERS, json={"expected_version": firmware_change["version"], "reviewer_note": "Supported by source."})
    assert accepted.status_code == 200, accepted.text
    accepted_version = accepted.json()["change"]["version"]

    modified = client.patch(f"/api/v1/research/review/changes/{secure_id}", headers=ADMIN_HEADERS, json={
        "expected_version": secure_change["version"], "expectation_description": "Review secure startup trust boundaries.",
        "technical_knowledge": "Secure boot policy review", "practical_capability": "Review startup trust boundaries.",
        "supporting_evidence": ["Design secure boot policy and review startup trust."], "reviewer_note": "Clarified by reviewer.",
    })
    assert modified.status_code == 200, modified.text

    from app.models import Competency
    from app.database import SessionLocal
    with SessionLocal() as db:
        target = db.query(Competency).filter(Competency.slug == "secure-boot").one()
        target_id = target.id

    merged = client.post(f"/api/v1/research/review/changes/{firmware_id}/merge", headers=ADMIN_HEADERS, json={
        "expected_version": accepted_version, "target_competency_id": target_id,
        "merged": {"expected_version": accepted_version, "technical_knowledge": "Hardware-backed firmware trust."},
    })
    assert merged.status_code == 200, merged.text
    assert merged.json()["change"]["status"] == "merged"

    rejected = client.post(f"/api/v1/research/review/changes/{manual_id}/reject", headers=ADMIN_HEADERS, json={"expected_version": manual_change["version"], "reviewer_note": "Manual classification is required."})
    assert rejected.status_code == 200

    conflict = client.post(f"/api/v1/research/review/changes/{secure_id}/accept", headers=ADMIN_HEADERS, json={"expected_version": secure_change["version"], "reviewer_note": "stale"})
    assert conflict.status_code == 409

    preview = client.get("/api/v1/research/review/publication-preview", headers=ADMIN_HEADERS)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["ready"] is True
    assert preview_body["merged_findings"] == 1
    expected_versions = {str(item["id"]): item["version"] for item in preview_body["changes"]}

    published = client.post("/api/v1/research/review/publish", headers=ADMIN_HEADERS, json={"confirm": True, "expected_versions": expected_versions})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    duplicate_publish = client.post("/api/v1/research/review/publish", headers=ADMIN_HEADERS, json={"confirm": True, "expected_versions": expected_versions})
    assert duplicate_publish.status_code == 409
    history = client.get("/api/v1/research/review/history", headers=ADMIN_HEADERS).json()
    assert any(item["action"] == "published" for item in history["items"])

    with SessionLocal() as db:
        secure = db.query(Competency).filter(Competency.slug == "secure-boot").one()
        expectations = db.query(DomainLevelExpectation).filter(DomainLevelExpectation.competency_id == secure.id).all()
        assert any("Hardware-backed firmware trust" in item.technical_knowledge for item in expectations)


def test_review_invalid_merge_target_and_atomic_conflict(client, monkeypatch):
    submission_id = submit_review_source(client, monkeypatch, content="review invalid merge source")
    detail = client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()
    change = detail["findings"][0]["review_change"]
    invalid = client.post(f"/api/v1/research/review/changes/{change['id']}/merge", headers=ADMIN_HEADERS, json={"expected_version": change["version"], "target_competency_id": 999999})
    assert invalid.status_code == 404
    accepted = client.post(f"/api/v1/research/review/changes/{change['id']}/accept", headers=ADMIN_HEADERS, json={"expected_version": change["version"]})
    assert accepted.status_code == 200
    preview = client.get("/api/v1/research/review/publication-preview", headers=ADMIN_HEADERS).json()
    expected_versions = {str(item["id"]): item["version"] for item in preview["changes"]}
    expected_versions[next(iter(expected_versions))] += 1
    failed = client.post("/api/v1/research/review/publish", headers=ADMIN_HEADERS, json={"confirm": True, "expected_versions": expected_versions})
    assert failed.status_code == 409
    current = client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()
    assert current["findings"][0]["review_change"]["status"] == "accepted"


def test_accept_with_publish_merges_into_domain_and_reuses_existing_competency(client, monkeypatch):
    from app.database import SessionLocal

    first_id = submit_review_source(client, monkeypatch, content="first merge source")
    first = client.get(f"/api/v1/research/review/submissions/{first_id}", headers=ADMIN_HEADERS).json()["findings"][0]
    assert first["classification_gaps"] == []
    merged = client.post(f"/api/v1/research/review/changes/{first['review_change']['id']}/accept", headers=ADMIN_HEADERS, json={"expected_version": first["review_change"]["version"], "publish": True})
    assert merged.status_code == 200, merged.text
    assert merged.json()["status"] == "published"
    assert merged.json()["change"]["status"] == "published"

    second_id = submit_review_source(client, monkeypatch, content="second merge source")
    second = client.get(f"/api/v1/research/review/submissions/{second_id}", headers=ADMIN_HEADERS).json()["findings"][0]
    again = client.post(f"/api/v1/research/review/changes/{second['review_change']['id']}/accept", headers=ADMIN_HEADERS, json={"expected_version": second["review_change"]["version"], "publish": True})
    assert again.status_code == 200, again.text

    with SessionLocal() as db:
        competencies = db.query(Competency).filter(Competency.name == "Firmware Integrity Controls").all()
        assert len(competencies) == 1
        expectations = db.query(DomainLevelExpectation).filter(DomainLevelExpectation.competency_id == competencies[0].id).all()
        assert {item.domain.slug for item in expectations} >= {"boot-security", "hardware-security"}


def test_accept_reports_missing_domain_as_classification_gap(client, monkeypatch):
    submission_id = submit_review_source(client, monkeypatch, content="review gap source")
    findings = client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()["findings"]
    change = findings[0]["review_change"]
    cleared = client.patch(f"/api/v1/research/review/changes/{change['id']}", headers=ADMIN_HEADERS, json={"expected_version": change["version"], "domain_ids": [999999]})
    assert cleared.status_code == 422
    still_pending = client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()["findings"][0]["review_change"]
    assert still_pending["status"] == "pending"


def test_submission_accepts_blank_optional_form_fields(client, monkeypatch):
    monkeypatch.setattr(providers, "extract_selected", lambda provider, model_id, content, taxonomy: result_for(content))
    response = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json={
        "content": "blank date source", "source_title": "Imported role", "source_url": "https://example.test/role",
        "research_date": "", "source_type": "url_imported",
    })
    assert response.status_code == 201, response.text


def test_failed_submission_can_be_retried_with_same_content(client, monkeypatch):
    from app.provider_common import ProviderError

    def unavailable(provider, model_id, content, taxonomy):
        raise ProviderError("openwebui", f"Model '{model_id}' is no longer available in OpenWebUI; select another model")

    payload = {"content": "retry after provider failure", "source_title": "Retry source"}
    monkeypatch.setattr(providers, "extract_selected", unavailable)
    failed = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json=payload)
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "failed"
    assert "no longer available" in failed.json()["error_message"]

    monkeypatch.setattr(providers, "extract_selected", lambda provider, model_id, content, taxonomy: result_for(content))
    retried = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json=payload)
    assert retried.status_code == 201, retried.text
    assert retried.json()["status"] != "failed"
    assert client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json=payload).status_code == 409


def test_accept_all_publishes_every_ready_change_of_a_source_in_one_batch(client, monkeypatch):
    submission_id = submit_review_source(client, monkeypatch, content="accept all review source")
    findings = client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()["findings"]
    ready = [item["review_change"] for item in findings if not item["classification_gaps"]]
    gapped = [item["review_change"] for item in findings if item["classification_gaps"]]
    assert len(ready) == 3 and len(gapped) == 1
    accepted = client.post(f"/api/v1/research/review/submissions/{submission_id}/accept-all", headers=ADMIN_HEADERS, json={"expected_versions": {str(change["id"]): change["version"] for change in ready}})
    assert accepted.status_code == 200, accepted.text
    assert sorted(accepted.json()["published_change_ids"]) == sorted(change["id"] for change in ready)
    statuses = {item["review_change"]["id"]: item["review_change"]["status"] for item in client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()["findings"]}
    assert {statuses[change["id"]] for change in ready} == {"published"}
    # The finding that still needs classification is left for individual review.
    assert statuses[gapped[0]["id"]] == "pending"


def test_accept_all_publishes_nothing_when_one_change_is_stale(client, monkeypatch):
    submission_id = submit_review_source(client, monkeypatch, content="accept all stale review source")
    changes = [item["review_change"] for item in client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()["findings"]]
    expected = {str(change["id"]): change["version"] for change in changes}
    expected[str(changes[-1]["id"])] += 1
    stale = client.post(f"/api/v1/research/review/submissions/{submission_id}/accept-all", headers=ADMIN_HEADERS, json={"expected_versions": expected})
    assert stale.status_code == 409
    statuses = {item["review_change"]["status"] for item in client.get(f"/api/v1/research/review/submissions/{submission_id}", headers=ADMIN_HEADERS).json()["findings"]}
    assert statuses == {"pending"}


def test_accept_all_rejects_changes_from_another_source(client, monkeypatch):
    first_id = submit_review_source(client, monkeypatch, content="accept all first review source")
    second_id = submit_review_source(client, monkeypatch, content="accept all second review source")
    other = client.get(f"/api/v1/research/review/submissions/{second_id}", headers=ADMIN_HEADERS).json()["findings"][0]["review_change"]
    response = client.post(f"/api/v1/research/review/submissions/{first_id}/accept-all", headers=ADMIN_HEADERS, json={"expected_versions": {str(other["id"]): other["version"]}})
    assert response.status_code == 404
    assert client.post(f"/api/v1/research/review/submissions/{first_id}/accept-all", headers=ADMIN_HEADERS, json={"expected_versions": {}}).status_code == 422
