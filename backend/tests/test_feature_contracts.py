import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import DomainLevelExpectation, Industry

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/research/review/dashboard"),
        ("post", "/api/v1/domains"),
        ("post", "/api/v1/research/submissions"),
        ("post", "/api/v1/research/models/refresh"),
        ("post", "/api/v1/research/review/publish"),
    ],
)
def test_admin_features_reject_missing_credentials(client, method, path):
    request = getattr(client, method)
    response = request(path) if method == "get" else request(path, json={})
    assert response.status_code == 401


def test_public_catalog_health_and_not_found_contracts(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert set(health.json()["services"]) == {"postgres", "redis", "ollama"}

    for path, key in [
        ("/api/v1/domains", "id"),
        ("/api/v1/levels", "id"),
        ("/api/v1/categories", "id"),
        ("/api/v1/industries", "id"),
        ("/api/v1/research-sources", "items"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert key in body[0] if isinstance(body, list) else key in body

    assert client.get("/api/v1/domains/999999").status_code == 404
    assert client.get("/api/v1/competencies/999999").status_code == 404
    assert client.get("/api/v1/expectations/999999").status_code == 404


def test_knowledge_catalog_creation_and_validation(client):
    level = client.post(
        "/api/v1/career-levels",
        headers=ADMIN_HEADERS,
        json={"name": "Contract Test Level", "slug": "contract-test-level", "career_track": "shared", "display_order": 99},
    )
    category = client.post(
        "/api/v1/competency-categories",
        headers=ADMIN_HEADERS,
        json={"name": "Contract Test Category", "slug": "contract-test-category"},
    )
    version = client.post(
        "/api/v1/analysis-versions",
        headers=ADMIN_HEADERS,
        json={
            "version": "contract-test-v1",
            "analysis_date": "2026-01-15T00:00:00Z",
            "description": "Contract test analysis",
            "methodology": "Deterministic API contract test",
        },
    )
    try:
        assert level.status_code == 201
        assert category.status_code == 201
        assert version.status_code == 201
        assert version.json()["version"] == "contract-test-v1"

        invalid_expectation = client.post(
            "/api/v1/expectations",
            headers=ADMIN_HEADERS,
            json={
                "domain_id": 1,
                "career_level_id": level.json()["id"],
                "competency_id": 1,
                "expectation_description": "Invalid range",
                "proficiency_level": "advanced",
                "importance": "essential",
                "responsibility_type": "implement",
                "experience_years_min": 8,
                "experience_years_max": 2,
            },
        )
        assert invalid_expectation.status_code == 422
    finally:
        from app.models import AnalysisVersion, CareerLevel, CompetencyCategory

        with SessionLocal() as db:
            db.query(AnalysisVersion).filter(AnalysisVersion.version == "contract-test-v1").delete()
            db.query(CareerLevel).filter(CareerLevel.slug == "contract-test-level").delete()
            db.query(CompetencyCategory).filter(CompetencyCategory.slug == "contract-test-category").delete()
            db.commit()


def test_industry_scope_returns_general_and_selected_expectations(client):
    with SessionLocal() as db:
        industry = db.scalar(select(Industry).where(Industry.slug == "automotive"))
        expectation = db.scalar(select(DomainLevelExpectation).where(DomainLevelExpectation.industry_id.is_(None)))
        assert industry is not None and expectation is not None
        previous_industry_id = expectation.industry_id
        expectation.industry_id = industry.id
        expectation_id = expectation.id
        db.commit()

    try:
        scoped = client.get("/api/v1/expectations?industry=automotive&page_size=100")
        assert scoped.status_code == 200
        item = next(item for item in scoped.json()["items"] if item["id"] == expectation_id)
        assert item["industry"]["slug"] == "automotive"

        other = client.get("/api/v1/expectations?industry=medical-devices-healthcare-technology&page_size=100")
        assert other.status_code == 200
        assert all(item["industry"] is None or item["industry"]["slug"] == "medical-devices-healthcare-technology" for item in other.json()["items"])
    finally:
        with SessionLocal() as db:
            restored = db.get(DomainLevelExpectation, expectation_id)
            restored.industry_id = previous_industry_id
            db.commit()


def test_query_validation_and_unknown_industry_errors(client):
    assert client.get("/api/v1/compare?domain=boot-security&levels=senior").status_code == 422
    assert client.get("/api/v1/search?keyword=boot&industry=not-a-real-industry").status_code == 404
    assert client.get("/api/v1/competencies?page=0").status_code == 422
