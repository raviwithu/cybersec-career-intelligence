ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}

from pathlib import Path
import os
import subprocess
import sys


def test_taxonomy_matches_revised_domain_and_track_requirements(client):
    taxonomy = client.get("/api/v1/taxonomy").json()
    assert {domain["name"] for domain in taxonomy["domains"]} == {
        "Web Application Security",
        "Cloud API Security",
        "Cloud Infrastructure Security",
        "Traditional Server Infrastructure Security",
        "Embedded Systems Security",
        "Governance, Risk, and Compliance",
        "Identity and Access Management",
        "Security Operations",
        "AI System Security",
        "AI-Enabled Security Products",
        "Security Automation",
        "Vulnerability Research",
    }
    embedded = next(domain for domain in taxonomy["domains"] if domain["name"] == "Embedded Systems Security")
    assert [child["name"] for child in embedded["children"]] == [
        "Embedded Application Security",
        "Operating System Security",
        "Boot Security",
        "Hardware Security",
        "Wireless Security",
    ]
    assert [level["name"] for level in taxonomy["career_levels"]] == [
        "Junior", "Intermediate", "Senior", "Guide", "Supervisor", "Manager", "Architect", "Director"
    ]
    tracks = {level["name"]: level["career_track"] for level in taxonomy["career_levels"]}
    assert tracks["Guide"] == "management"
    assert tracks["Supervisor"] == "management"
    assert tracks["Manager"] == "management"
    assert tracks["Architect"] == "technical"
    assert {category["name"] for category in taxonomy["competency_categories"]} >= {
        "Technical Knowledge", "Technical Skills", "Tools and Technologies", "Security Architecture",
        "Security Testing", "Experience", "Education", "Certifications", "Security Standards",
        "Responsibilities", "Leadership", "Communication", "Risk Management",
    }


def test_competency_relationship_expectation_reuse_and_sources(client):
    taxonomy = client.get("/api/v1/taxonomy").json()
    categories = {category["name"]: category["id"] for category in taxonomy["competency_categories"]}
    domains = {domain["name"]: domain["id"] for domain in taxonomy["domains"]}
    levels = {level["name"]: level["id"] for level in taxonomy["career_levels"]}

    secure_boot = client.post("/api/v1/competencies", headers=ADMIN_HEADERS, json={
        "name": "Test Secure Boot Architecture", "slug": "test-secure-boot-architecture",
        "description": "Illustrative test competency.", "category_id": categories["Security Architecture"],
    })
    chain = client.post("/api/v1/competencies", headers=ADMIN_HEADERS, json={
        "name": "Test Chain of Trust", "slug": "test-chain-of-trust",
        "description": "Illustrative test prerequisite.", "category_id": categories["Technical Knowledge"],
    })
    assert secure_boot.status_code == 201
    assert chain.status_code == 201

    relationship = client.post("/api/v1/competency-relationships", headers=ADMIN_HEADERS, json={
        "source_competency_id": secure_boot.json()["id"],
        "target_competency_id": chain.json()["id"],
        "relationship_type": "prerequisite",
    })
    assert relationship.status_code == 201

    expectation_payload = {
        "domain_id": domains["Embedded Systems Security"],
        "career_level_id": levels["Architect"],
        "competency_id": secure_boot.json()["id"],
        "expectation_description": "Design trust boundaries for secure startup.",
        "proficiency_level": "expert",
        "importance": "essential",
        "responsibility_type": "design",
        "experience_years_min": 7,
    }
    first = client.post("/api/v1/expectations", headers=ADMIN_HEADERS, json=expectation_payload)
    second_payload = {**expectation_payload, "expectation_description": "Define key provisioning and rotation requirements."}
    second = client.post("/api/v1/expectations", headers=ADMIN_HEADERS, json=second_payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    source = client.post("/api/v1/research-sources", headers=ADMIN_HEADERS, json={
        "source_type": "standard", "source_url": "https://example.test/standard",
        "source_title": "Illustrative test source", "notes": "Test-only reference.",
    })
    assert source.status_code == 201
    link = client.post(
        f"/api/v1/expectations/{first.json()['id']}/sources/{source.json()['id']}",
        headers=ADMIN_HEADERS, json={"supporting_excerpt": "Test excerpt supporting the expectation."},
    )
    assert link.status_code == 201

    filtered = client.get(f"/api/v1/expectations?domain_id={domains['Embedded Systems Security']}&career_level_id={levels['Architect']}")
    assert filtered.status_code == 200
    matching = [item for item in filtered.json() if item["competency_id"] == secure_boot.json()["id"]]
    assert len(matching) == 2
    assert next(item for item in matching if item["id"] == first.json()["id"])["source_count"] == 1


def test_domain_extension_and_referential_integrity(client):
    taxonomy = client.get("/api/v1/taxonomy").json()
    parent_id = taxonomy["domains"][0]["id"]
    extension = client.post("/api/v1/domains", headers=ADMIN_HEADERS, json={
        "name": "Test Domain Extension", "slug": "test-domain-extension", "parent_id": parent_id, "display_order": 99,
    })
    assert extension.status_code == 201
    assert extension.json()["parent_id"] == parent_id

    invalid_parent = client.post("/api/v1/domains", headers=ADMIN_HEADERS, json={
        "name": "Invalid Child", "slug": "invalid-child", "parent_id": 999999,
    })
    assert invalid_parent.status_code == 404


def test_alembic_migration_creates_revised_tables():
    backend = Path(__file__).parents[1]
    temp_database = backend / "migration_test.sqlite3"
    temp_database.unlink(missing_ok=True)
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{temp_database}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade", "head"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
    )
    try:
        assert result.returncode == 0, result.stderr
        from sqlalchemy import create_engine, inspect

        tables = set(inspect(create_engine(f"sqlite:///{temp_database}")).get_table_names())
        assert "job_postings" not in tables
        assert {
            "security_domains", "career_levels", "competency_categories", "competencies",
            "domain_level_expectations", "competency_relationships", "research_sources",
            "expectation_sources", "analysis_versions", "research_submissions", "research_findings",
            "draft_expectations", "draft_evidence", "research_submission_audits",
        } <= tables
    finally:
        temp_database.unlink(missing_ok=True)
