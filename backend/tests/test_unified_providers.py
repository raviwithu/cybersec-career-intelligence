import json

import httpx
import pytest
from sqlalchemy.orm import Session

from app.ai_providers import AIProviderRegistry
from app.config import Settings
from app.models import ModelSelection
from app.ollama_client import OllamaClient
from app.openwebui_client import OpenWebUIClient
from app.phase5_api import providers as api_providers
from app.provider_common import AIModel, ProviderCatalog, ProviderError

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


def provider_settings():
    return Settings(
        database_url="sqlite:///unused.sqlite3",
        ollama_base_url="http://ollama.test",
        ollama_model="qwen2.5-coder:32b",
        openwebui_base_url="http://openwebui.test",
        openwebui_api_key="secret-not-for-responses",
        ollama_timeout_seconds=1,
        openwebui_timeout_seconds=1,
        admin_api_key="test-admin-key",
    )


def empty_extraction_response():
    return {"requirements": [], "unclassified_notes": []}


def test_ollama_discovery_preserves_size_and_details():
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:32b", "size": 123, "details": {"family": "qwen2"}}]})

    records = OllamaClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(handler))).list_model_records()
    assert records[0].model_id == "qwen2.5-coder:32b"
    assert records[0].size == 123
    assert records[0].details["family"] == "qwen2"


def test_openwebui_discovery_uses_bearer_auth_and_preserves_provider_metadata():
    def handler(request):
        assert request.url.path == "/api/models"
        assert request.headers["authorization"] == "Bearer secret-not-for-responses"
        return httpx.Response(200, json={"data": [{"id": "remote/custom-model", "name": "Custom Model", "owned_by": "external-provider", "context_length": 8192, "api_key": "must-not-escape"}]})

    records = OpenWebUIClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(handler))).list_model_records()
    assert records[0].model_id == "remote/custom-model"
    assert records[0].name == "Custom Model"
    assert records[0].provider_info == "external-provider"
    assert records[0].metadata["context_length"] == 8192
    assert "api_key" not in records[0].metadata


def test_openwebui_authentication_and_unavailability_are_provider_specific():
    unauthorized = OpenWebUIClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401))))
    with pytest.raises(ProviderError, match="authentication failed"):
        unauthorized.list_models()

    unavailable = OpenWebUIClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline")))))
    with pytest.raises(ProviderError, match="Unable to reach"):
        unavailable.list_models()


def test_openwebui_errors_include_provider_detail_and_name_missing_models():
    missing = OpenWebUIClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"detail": "Model not found"}))))
    with pytest.raises(ProviderError, match="Model 'retired-model' is no longer available in OpenWebUI"):
        missing.extract("research", {"domains": []}, model="retired-model")

    rejected = OpenWebUIClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"error": {"message": "context length exceeded"}}))))
    with pytest.raises(ProviderError, match="HTTP 400: context length exceeded"):
        rejected.test_model("custom-model")


def test_combined_discovery_keeps_providers_and_marks_possible_duplicates():
    settings = provider_settings()
    ollama = OllamaClient(settings, httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:32b"}]}))))
    openwebui = OpenWebUIClient(settings, httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "qwen2.5-coder:32b", "name": "Qwen through OpenWebUI"}]}))))
    catalogs = AIProviderRegistry(settings, ollama=ollama, openwebui=openwebui).discover()
    assert [catalog.provider for catalog in catalogs] == ["ollama", "openwebui"]
    assert all(catalog.models[0].possible_duplicate for catalog in catalogs)
    assert catalogs[0].models[0].duplicate_with == ("openwebui:qwen2.5-coder:32b",)


def test_ollama_inference_normalizes_native_response():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"response": '{"requirements": [], "unclassified_notes": []}'})

    result = OllamaClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(handler))).extract("research", {"domains": []})
    assert result.requirements == []
    assert sent["model"] == "qwen2.5-coder:32b"
    assert sent["format"] == "json"


def test_openwebui_inference_uses_exact_id_and_neutral_chat_payload():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"requirements": [], "unclassified_notes": []}'}}]})

    client = OpenWebUIClient(provider_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.extract("research", {"domains": []}, model="remote/custom-model")
    assert result.requirements == []
    assert sent["model"] == "remote/custom-model"
    assert sent["stream"] is False
    assert "options" not in sent
    assert sent["messages"][0]["role"] == "system"


def test_openwebui_malformed_model_response_is_rejected():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    client = OpenWebUIClient(provider_settings(), httpx.Client(transport=transport))
    with pytest.raises(ProviderError, match="malformed|JSON"):
        client.extract("research", {"domains": []}, model="custom-model")


def test_unified_api_lists_both_routes_without_exposing_api_key(client, monkeypatch):
    catalogs = [
        ProviderCatalog("ollama", "connected", (AIModel("ollama", "local-model", "Local Model"),)),
        ProviderCatalog("openwebui", "connected", (AIModel("openwebui", "remote-model", "Remote Model", provider_info="external"),)),
    ]
    monkeypatch.setattr(api_providers, "discover", lambda: catalogs)
    response = client.get("/api/v1/research/models", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert [item["provider"] for item in body["providers"]] == ["ollama", "openwebui"]
    assert body["providers"][1]["models"][0]["id"] == "remote-model"
    assert "secret-not-for-responses" not in response.text


def test_unified_selection_persists_provider_and_model(client, monkeypatch):
    catalogs = [
        ProviderCatalog("ollama", "connected", (AIModel("ollama", "local-model", "Local Model"),)),
        ProviderCatalog("openwebui", "connected", (AIModel("openwebui", "remote-model", "Remote Model"),)),
    ]
    monkeypatch.setattr(api_providers, "discover", lambda: catalogs)
    selected = client.post("/api/v1/research/models/select", headers=ADMIN_HEADERS, json={"provider": "openwebui", "model_id": "remote-model"})
    assert selected.status_code == 200
    assert selected.json()["active_provider"] == "openwebui"
    assert selected.json()["active_model_id"] == "remote-model"
    with Session(__import__("app.database", fromlist=["engine"]).engine) as db:
        selection = db.get(ModelSelection, 1)
        assert selection.selected_provider == "openwebui"
        assert selection.selected_model == "remote-model"
        db.delete(selection)
        db.commit()


def test_extraction_prompt_requests_qualifications_and_tools():
    from app.provider_common import build_extraction_prompt, parse_extraction

    prompt = build_extraction_prompt("Requires CISSP and Splunk.", {"domains": []})
    assert '"qualifications":""' in prompt
    assert '"tools_technologies":""' in prompt

    result = parse_extraction(json.dumps({"requirements": [{
        "competency_name": "Detection engineering", "evidence_excerpt": "Requires CISSP and Splunk.",
        "qualifications": ["CISSP"], "tools_technologies": ["Splunk", "Sentinel"],
    }]}))
    assert result.requirements[0].qualifications == "CISSP"
    assert result.requirements[0].tools_technologies == "Splunk, Sentinel"


def test_extraction_prompt_contains_ai_domain_names_and_disambiguating_descriptions():
    from app.database import SessionLocal
    from app.phase5_service import taxonomy
    from app.provider_common import build_extraction_prompt
    from app.seed import DOMAIN_SEED, seed_reference_data

    with SessionLocal() as db:
        seed_reference_data(db)
        db.commit()
        prompt = build_extraction_prompt("AI security research", taxonomy(db))

    expected = {
        slug: (name, description)
        for slug, name, description, parent_id, display_order in DOMAIN_SEED
        if slug in {"ai-system-security", "ai-enabled-security-products"}
    }
    for name, description in expected.values():
        assert name in prompt
        assert description in prompt
