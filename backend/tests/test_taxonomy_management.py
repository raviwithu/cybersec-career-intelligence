from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DomainLevelExpectation, ResearchSource, SecurityDomain

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


def test_taxonomy_management_requires_admin(client):
    assert client.get("/api/v1/research/taxonomy").status_code == 401
    assert client.post("/api/v1/research/taxonomy/domain", json={"name": "Unauthorized"}).status_code == 401


def test_taxonomy_crud_aliases_hierarchy_and_history(client):
    created = client.post("/api/v1/research/taxonomy/domain", headers=ADMIN_HEADERS, json={
        "name": "Embedded Systems Security Research",
        "description": "A managed domain.",
        "aliases": [{"alias": "Embedded Research Security"}],
        "display_order": 90,
    })
    assert created.status_code == 201
    domain = created.json()
    assert domain["slug"] == "embedded-systems-security-research"
    assert domain["aliases"][0]["alias"] == "Embedded Research Security"

    child = client.post("/api/v1/research/taxonomy/domain", headers=ADMIN_HEADERS, json={
        "name": "Firmware Research Security",
        "parent_id": domain["id"],
    })
    assert child.status_code == 201
    assert child.json()["parent_name"] == domain["name"]

    cycle = client.patch(f"/api/v1/research/taxonomy/domain/{domain['id']}", headers=ADMIN_HEADERS, json={"parent_id": child.json()["id"]})
    assert cycle.status_code == 422

    updated = client.patch(f"/api/v1/research/taxonomy/domain/{domain['id']}", headers=ADMIN_HEADERS, json={
        "description": "Updated managed domain.",
        "display_order": 12,
        "aliases": [{"alias": "Embedded Research Security"}, {"alias": "Embedded Platform Security"}],
    })
    assert updated.status_code == 200
    assert updated.json()["display_order"] == 12
    assert len(updated.json()["aliases"]) == 2

    duplicate = client.post("/api/v1/research/taxonomy/domain", headers=ADMIN_HEADERS, json={"name": domain["name"]})
    assert duplicate.status_code == 409

    history = client.get("/api/v1/research/taxonomy/history", headers=ADMIN_HEADERS)
    assert history.status_code == 200
    assert {item["action"] for item in history.json()["items"]} >= {"created", "updated"}


def test_taxonomy_lifecycle_merge_and_dependency_protection(client):
    industry = client.post("/api/v1/research/taxonomy/industry", headers=ADMIN_HEADERS, json={"name": "Managed Industry", "aliases": [{"alias": "Managed Sector"}]})
    assert industry.status_code == 201
    industry_id = industry.json()["id"]
    assert client.get("/api/v1/industries").json()

    level = client.post("/api/v1/research/taxonomy/career_level", headers=ADMIN_HEADERS, json={"name": "Managed Level", "career_track": "technical"})
    category = client.post("/api/v1/research/taxonomy/category", headers=ADMIN_HEADERS, json={"name": "Managed Category"})
    assert level.status_code == category.status_code == 201

    deactivated = client.post(f"/api/v1/research/taxonomy/industry/{industry_id}/deactivate", headers=ADMIN_HEADERS)
    assert deactivated.status_code == 200
    assert industry_id not in {item["id"] for item in client.get("/api/v1/industries").json()}
    reactivated = client.post(f"/api/v1/research/taxonomy/industry/{industry_id}/reactivate", headers=ADMIN_HEADERS)
    assert reactivated.status_code == 200
    assert industry_id in {item["id"] for item in client.get("/api/v1/industries").json()}

    source = client.post("/api/v1/research/taxonomy/domain", headers=ADMIN_HEADERS, json={"name": "Merge Source Domain"}).json()
    target = client.post("/api/v1/research/taxonomy/domain", headers=ADMIN_HEADERS, json={"name": "Merge Target Domain"}).json()
    merged = client.post(f"/api/v1/research/taxonomy/domain/{source['id']}/merge", headers=ADMIN_HEADERS, json={"target_id": target["id"], "confirm": True})
    assert merged.status_code == 200
    inactive = client.get("/api/v1/research/taxonomy", headers=ADMIN_HEADERS).json()["items"]
    assert next(item for item in inactive if item["id"] == source["id"])["is_active"] is False

    with SessionLocal() as db:
        protected = db.scalar(select(SecurityDomain).where(SecurityDomain.is_active.is_(True), SecurityDomain.id.in_(select(DomainLevelExpectation.domain_id))))
        assert protected is not None
        protected_id = protected.id
    deletion = client.delete(f"/api/v1/research/taxonomy/domain/{protected_id}", headers=ADMIN_HEADERS)
    assert deletion.status_code == 409

    merge_history = client.get("/api/v1/research/taxonomy/history?action=merged", headers=ADMIN_HEADERS)
    assert merge_history.status_code == 200
    assert any(item["merge_source_id"] == source["id"] and item["merge_target_id"] == target["id"] for item in merge_history.json()["items"])


def test_unused_taxonomy_entry_can_be_deleted(client):
    created = client.post("/api/v1/research/taxonomy/category", headers=ADMIN_HEADERS, json={"name": "Disposable Category"})
    assert created.status_code == 201
    entry_id = created.json()["id"]
    deleted = client.delete(f"/api/v1/research/taxonomy/category/{entry_id}", headers=ADMIN_HEADERS)
    assert deleted.status_code == 204
    assert not any(item["id"] == entry_id and item["taxonomy_type"] == "category" for item in client.get("/api/v1/research/taxonomy", headers=ADMIN_HEADERS).json()["items"])
