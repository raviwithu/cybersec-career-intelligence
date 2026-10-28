from datetime import datetime, timezone

from app.database import SessionLocal
from app.knowledge_topic_service import ensure_topic_proposal
from app.models import (
    CareerLevel,
    CompetencyCategory,
    Industry,
    KnowledgeTopic,
    ResearchFinding,
    ResearchSource,
    ResearchSubmission,
    SecurityDomain,
)

ADMIN = {"X-Admin-API-Key": "test-admin-key"}


def _taxonomy(client):
    domains = client.get("/api/v1/domains").json()
    categories = client.get("/api/v1/categories").json()
    return domains[0]["id"], categories[0]["id"]


def test_topic_mutations_require_administrator_authentication(client):
    response = client.post("/api/v1/research/career-readiness/topics", json={"name": "Unauthorized topic"})
    assert response.status_code == 401
    assert client.get("/api/v1/research/career-readiness/proposals").status_code == 401


def test_manual_topic_publication_isolated_and_versioned(client):
    domain_id, category_id = _taxonomy(client)
    payload = {
        "name": "IDOR / BOLA",
        "description": "Object-level authorization weaknesses that allow access without appropriate permissions.",
        "category_id": category_id,
        "domain_ids": [domain_id],
        "aliases": ["object-level authorization"],
    }
    created = client.post("/api/v1/research/career-readiness/topics", headers=ADMIN, json=payload)
    assert created.status_code == 201
    topic = created.json()
    assert topic["publication_status"] == "draft"
    assert client.get(f"/api/v1/knowledge-topics/{topic['id']}").status_code == 404

    published = client.post(
        f"/api/v1/research/career-readiness/topics/{topic['id']}/publish",
        headers=ADMIN,
        json={"confirm": True, "expected_versions": {str(topic["id"]): topic["version"]}, "change_reason": "Initial reviewed publication"},
    )
    assert published.status_code == 200
    public = client.get(f"/api/v1/knowledge-topics/{topic['id']}")
    assert public.status_code == 200
    assert public.json()["name"] == "IDOR / BOLA"

    update = client.patch(
        f"/api/v1/research/career-readiness/topics/{topic['id']}",
        headers=ADMIN,
        json={"expected_version": published.json()["versions"][str(topic["id"])], "description": "Updated reviewed description.", "change_reason": "Clarified authorization scope"},
    )
    assert update.status_code == 200
    assert update.json()["publication_status"] == "review"
    assert client.get(f"/api/v1/knowledge-topics/{topic['id']}").status_code == 404

    republished = client.post(
        f"/api/v1/research/career-readiness/topics/{topic['id']}/publish",
        headers=ADMIN,
        json={"confirm": True, "expected_versions": {str(topic["id"]): update.json()["version"]}, "change_reason": "Approved edited content"},
    )
    assert republished.status_code == 200
    assert client.get(f"/api/v1/knowledge-topics/{topic['id']}").json()["description"] == "Updated reviewed description."
    history = client.get(f"/api/v1/research/career-readiness/topics/{topic['id']}/history", headers=ADMIN)
    assert history.status_code == 200
    assert any(item["kind"] == "version" and item["version"] >= 2 for item in history.json()["items"])


def test_research_finding_creates_one_evidence_backed_topic_proposal(client):
    domain_id, category_id = _taxonomy(client)
    db = SessionLocal()
    try:
        level = db.query(CareerLevel).filter_by(slug="senior").one()
        source = ResearchSource(source_type="jsearch", source_url="https://jobs.example/idor", source_title="API Security Engineer", collected_at=datetime.now(timezone.utc))
        submission = ResearchSubmission(source=source, source_type="jsearch", content_sha256="a" * 64, content_size=100, status="draft_ready")
        finding = ResearchFinding(
            submission=submission, domain_id=domain_id, career_level_id=level.id, category_id=category_id,
            candidate_name="SPIFFE / SPIRE", normalized_name="SPIFFE / SPIRE", finding_type="technical-knowledge",
            technical_knowledge="Service identity and workload attestation.", practical_capability="Configure workload identity safely.",
            evidence_excerpt="Experience with SPIFFE and SPIRE workload identity.", confidence=0.91, status="normalized",
        )
        db.add(finding)
        db.commit()
        first = ensure_topic_proposal(db, finding)
        db.commit()
        second = ensure_topic_proposal(db, finding)
        assert first.id == second.id
        assert first.proposal_type == "new_topic"
        assert first.evidence_status == "explicitly_supported"
        proposal_id = first.id
    finally:
        db.close()

    queue = client.get("/api/v1/research/career-readiness/proposals", headers=ADMIN)
    assert queue.status_code == 200
    proposal = next(item for item in queue.json()["items"] if item["id"] == proposal_id)
    assert proposal["source_references"][0]["excerpt"].startswith("Experience with SPIFFE")
    assert proposal["proposed"]["name"] == "SPIFFE / SPIRE"

    reviewed = client.post(
        f"/api/v1/research/career-readiness/proposals/{proposal_id}/review",
        headers=ADMIN,
        json={"expected_version": proposal["version"], "action": "accept", "reviewer_note": "Evidence is explicit."},
    )
    assert reviewed.status_code == 200
    approved = reviewed.json()
    published = client.post(
        "/api/v1/research/career-readiness/proposals/publish",
        headers=ADMIN,
        json={"confirm": True, "proposal_ids": [proposal_id], "expected_versions": {str(proposal_id): approved["version"]}},
    )
    assert published.status_code == 200
    topic_id = published.json()["published_topic_ids"][0]
    public = client.get(f"/api/v1/knowledge-topics/{topic_id}")
    assert public.status_code == 200
    assert public.json()["name"] == "SPIFFE / SPIRE"
    assert public.json()["evidence_count"] == 1



def test_existing_topic_matching_proposes_update_not_duplicate(client):
    db = SessionLocal()
    try:
        topic = db.query(KnowledgeTopic).filter_by(slug="api-authorization").one()
        level = db.query(CareerLevel).filter_by(slug="senior").one()
        source = ResearchSource(source_type="jsearch", source_url="https://jobs.example/oauth", source_title="API authorization update", collected_at=datetime.now(timezone.utc))
        submission = ResearchSubmission(source=source, source_type="jsearch", content_sha256="c" * 64, content_size=60, status="draft_ready")
        finding = ResearchFinding(submission=submission, domain_id=topic.domains[0].domain_id, career_level_id=level.id, category_id=topic.category_id, competency_id=topic.competencies[0].competency_id, candidate_name="API Authorization", normalized_name="API Authorization", finding_type="technical-knowledge", technical_knowledge="Add token exchange and PKCE.", practical_capability="Assess OAuth token exchange and PKCE.", evidence_excerpt="Requires knowledge of OAuth token exchange and PKCE.", confidence=0.88, status="normalized")
        db.add(finding)
        db.commit()
        proposal = ensure_topic_proposal(db, finding)
        db.commit()
        assert proposal.topic_id == topic.id
        assert proposal.proposal_type in {"topic_update", "evidence_update"}
        assert proposal.proposed_snapshot["name"] == topic.name
        assert proposal.proposed_snapshot["domain_ids"]
    finally:
        db.close()


def test_rejected_topic_proposal_never_reaches_public_api(client):
    db = SessionLocal()
    try:
        domain = db.query(SecurityDomain).filter(SecurityDomain.is_active.is_(True)).first()
        category = db.query(CompetencyCategory).filter(CompetencyCategory.is_active.is_(True)).first()
        level = db.query(CareerLevel).filter(CareerLevel.slug == "senior").one()
        source = ResearchSource(source_type="jsearch", source_url="https://jobs.example/rejected", source_title="Rejected source", collected_at=datetime.now(timezone.utc))
        submission = ResearchSubmission(source=source, source_type="jsearch", content_sha256="b" * 64, content_size=50, status="draft_ready")
        finding = ResearchFinding(submission=submission, domain_id=domain.id, career_level_id=level.id, category_id=category.id, candidate_name="Unpublished Secret Topic", normalized_name="Unpublished Secret Topic", finding_type="technical-knowledge", evidence_excerpt="A source excerpt.", confidence=0.8, status="normalized")
        db.add(finding)
        db.commit()
        proposal = ensure_topic_proposal(db, finding)
        db.commit()
        proposal_id, version = proposal.id, proposal.version
    finally:
        db.close()
    rejected = client.post(f"/api/v1/research/career-readiness/proposals/{proposal_id}/review", headers=ADMIN, json={"expected_version": version, "action": "reject"})
    assert rejected.status_code == 200
    assert client.get("/api/v1/knowledge-topics", params={"search": "Unpublished Secret Topic"}).json() == []
