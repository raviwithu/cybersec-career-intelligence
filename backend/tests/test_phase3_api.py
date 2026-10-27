ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


def taxonomy(client):
    response = client.get("/api/v1/taxonomy")
    assert response.status_code == 200
    return response.json()


def test_domain_hierarchy_and_missing_resource(client):
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    domains = response.json()
    assert len(domains) == 5
    embedded = next(item for item in domains if item["slug"] == "embedded-systems-security")
    assert len(embedded["children"]) == 5
    assert all(child["parent_id"] == embedded["id"] for child in embedded["children"])

    detail = client.get(f"/api/v1/domains/{embedded['id']}")
    assert detail.status_code == 200
    assert {child["slug"] for child in detail.json()["children"]} == {
        "embedded-application-security", "operating-system-security", "boot-security",
        "hardware-security", "wireless-security",
    }
    assert client.get("/api/v1/domains/999999").status_code == 404


def test_levels_and_categories(client):
    levels = client.get("/api/v1/levels")
    categories = client.get("/api/v1/categories")
    assert levels.status_code == 200
    assert categories.status_code == 200
    assert [item["name"] for item in levels.json()] == ["Junior", "Intermediate", "Senior", "Manager", "Architect", "Director"]
    assert {item["career_track"] for item in levels.json()} == {"shared", "management", "technical"}
    assert len(categories.json()) == 13


def test_competency_filtering_detail_and_pagination(client):
    data = taxonomy(client)
    category = next(item for item in data["competency_categories"] if item["slug"] == "security-architecture")
    filtered = client.get(f"/api/v1/competencies?category={category['slug']}&page=1&page_size=2")
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["meta"]["page_size"] == 2
    assert body["meta"]["total"] >= 3
    assert len(body["items"]) <= 2
    assert all(item["category"]["slug"] == category["slug"] for item in body["items"])

    domain_filtered = client.get("/api/v1/competencies?domain=boot-security&level=architect")
    assert domain_filtered.status_code == 200
    assert any(item["slug"] == "secure-boot" for item in domain_filtered.json()["items"])

    detail = client.get(f"/api/v1/competencies/{body['items'][0]['id']}")
    assert detail.status_code == 200
    assert "related_competencies" in detail.json()
    assert "expectations" in detail.json()
    assert client.get("/api/v1/competencies/999999").status_code == 404
    assert client.get("/api/v1/competencies?page=0").status_code == 422


def test_expectation_filters_and_research_source_association(client):
    response = client.get("/api/v1/expectations?domain=boot-security&level=architect&importance=essential&proficiency=expert")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] >= 1
    expectation = body["items"][0]
    assert expectation["competency"]["slug"] == "secure-boot"
    assert expectation["supporting_sources"] == []

    source = client.post("/api/v1/research-sources", headers=ADMIN_HEADERS, json={
        "source_type": "test", "source_url": "https://example.test/phase3-source",
        "source_title": "Phase 3 source", "notes": "Integration test source",
    })
    assert source.status_code == 201
    link = client.post(
        f"/api/v1/expectations/{expectation['id']}/sources/{source.json()['id']}",
        headers=ADMIN_HEADERS, json={"supporting_excerpt": "Supporting test excerpt."},
    )
    assert link.status_code == 201

    detail = client.get(f"/api/v1/expectations/{expectation['id']}")
    assert detail.status_code == 200
    assert detail.json()["supporting_sources"][0]["supporting_excerpt"] == "Supporting test excerpt."
    sources = client.get("/api/v1/research-sources")
    assert sources.status_code == 200
    source_item = next(item for item in sources.json()["items"] if item["id"] == source.json()["id"])
    assert expectation["id"] in source_item["expectation_ids"]
    assert client.get("/api/v1/expectations/999999").status_code == 404


def test_career_matrix_and_comparison(client):
    data = taxonomy(client)
    domains = {item["slug"]: item["id"] for item in data["domains"]}
    levels = {item["slug"]: item["id"] for item in data["career_levels"]}
    secure_boot = next(item for item in data["competencies"] if item["slug"] == "secure-boot")
    api_auth = next(item for item in data["competencies"] if item["slug"] == "api-authorization")

    architect_expectation = client.post("/api/v1/expectations", headers=ADMIN_HEADERS, json={
        "domain_id": domains["cloud-api-security"], "career_level_id": levels["architect"],
        "competency_id": api_auth["id"], "expectation_description": "Architect API authorization boundaries.",
        "proficiency_level": "expert", "importance": "essential", "responsibility_type": "design",
    })
    assert architect_expectation.status_code == 201

    matrix = client.get("/api/v1/career-matrix")
    assert matrix.status_code == 200
    cloud = next(item for item in matrix.json()["domains"] if item["domain"]["slug"] == "cloud-api-security")
    architect_cell = next(item for item in cloud["cells"] if item["career_level_id"] == levels["architect"])
    assert architect_cell["expectation_count"] >= 1
    assert architect_cell["competency_count"] >= 1

    comparison = client.get("/api/v1/compare?domain=cloud-api-security&levels=senior,architect")
    assert comparison.status_code == 200
    comparison_body = comparison.json()
    assert comparison_body["domain"]["slug"] == "cloud-api-security"
    assert {item["level"]["slug"] for item in comparison_body["levels"]} == {"senior", "architect"}
    assert any(item["competency"]["slug"] == "api-authorization" for item in comparison_body["shared_competencies"])
    assert any(item["competency"]["slug"] == "api-authorization" for item in comparison_body["differences"])
    assert client.get("/api/v1/compare?domain=cloud-api-security&levels=senior").status_code == 422


def test_search_filters_pagination_and_empty_results(client):
    response = client.get("/api/v1/search?keyword=secure&page=1&page_size=2")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] >= 1
    assert len(body["items"]) <= 2
    assert any(item["result_type"] in {"competency", "expectation", "domain"} for item in body["items"])

    filtered = client.get("/api/v1/search?keyword=boot&domain=embedded-systems-security&level=architect")
    assert filtered.status_code == 200
    assert filtered.json()["meta"]["total"] >= 1

    empty = client.get("/api/v1/search?keyword=does-not-exist-anywhere")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["meta"]["total"] == 0
    assert client.get("/api/v1/search?keyword=x&page_size=0").status_code == 422
