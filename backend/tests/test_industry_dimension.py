from app.industry_service import expectation_scope_clause, normalize_industry


def test_industries_are_listed_with_alias_provenance(client):
    response = client.get("/api/v1/industries")
    assert response.status_code == 200
    industries = response.json()
    automotive = next(item for item in industries if item["slug"] == "automotive")
    assert automotive["name"] == "Automotive"
    assert any(alias["alias"] == "Connected Vehicles" for alias in automotive["aliases"])


def test_context_sensitive_alias_requires_context_and_resolves(client):
    missing_context = client.get("/api/v1/competencies?industry=OT")
    assert missing_context.status_code == 422
    resolved = client.get("/api/v1/competencies?industry=OT&context=industrial%20control%20system")
    assert resolved.status_code == 200


def test_industry_scope_preserves_general_expectations():
    clause = expectation_scope_clause(7)
    compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
    assert "industry_id IS NULL" in compiled
    assert "industry_id = 7" in compiled
    assert normalize_industry("  Medical   Devices ") == "medical devices"
