def test_liveness(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend"}


def test_profiles_are_persisted_in_database(client):
    payload = {
        "full_name": "Ravi Tamilarasan",
        "target_role": "Security Engineer",
        "skills": ["Python", "Threat Modeling"],
    }

    created = client.post("/api/v1/profiles", headers={"X-Admin-API-Key": "test-admin-key"}, json=payload)
    listed = client.get("/api/v1/profiles", headers={"X-Admin-API-Key": "test-admin-key"})

    assert created.status_code == 201
    assert created.json()["target_role"] == payload["target_role"]
    assert listed.status_code == 200
    assert listed.json()[0]["skills"] == payload["skills"]


def test_readiness_reports_database_and_redis(client):
    response = client.get("/health/ready")

    assert response.status_code in (200, 503)
    body = response.json()
    if response.status_code == 503:
        body = body["detail"]
    assert set(body["services"]) == {"postgres", "redis"}
    assert body["services"]["postgres"]["status"] == "up"
