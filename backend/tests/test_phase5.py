import json

import httpx
import pytest

from app.ollama_client import OllamaClient, OllamaError, _parse_json
from app.models import CareerLevel, Competency, SecurityDomain
from app.phase5_api import ollama, url_importer
from app.phase5_schemas import ExtractionResult, ExtractedRequirement
from app.phase5_service import classify_domain, classify_level, normalize_competency, parse_research_file
from app.url_importer import ImportedJob, UrlImportError, UrlImporter, extract_job, html_to_text, validate_url

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


def extraction(name="K8s", level="senior", excerpt="Securely operate Kubernetes workloads."):
    return ExtractionResult(requirements=[ExtractedRequirement(
        domain_slugs=["cloud-infrastructure-security"], security_subdomains=[], career_level=level,
        competency_name=name, category_slug="tools-technologies", technical_knowledge="Kubernetes security",
        practical_capability="Secure and operate Kubernetes workloads.", responsibilities="Lead workload security reviews.",
        proficiency_level="advanced", importance="essential", experience_years_min=4, evidence_excerpt=excerpt, confidence=0.94,
    )])


def test_ollama_health_and_malformed_json_handling():
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "test-model"}]})
        return httpx.Response(200, json={"response": "not json"})

    client = OllamaClient(
        type("Settings", (), {"ollama_base_url": "http://test", "ollama_model": "test-model", "ollama_timeout_seconds": 1, "ollama_retries": 0})(),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.health() == (True, "configured model available")
    with pytest.raises(OllamaError):
        client.extract("untrusted input", {"domains": [], "career_levels": [], "categories": []})
    with pytest.raises(OllamaError):
        _parse_json("```")
    assert _parse_json('{"requirements": [], "unclassified_notes": []}') == {"requirements": [], "unclassified_notes": []}
    assert _parse_json('Here you go:\n{"requirements": []} done') == {"requirements": []}
    client.close()


@pytest.mark.parametrize("model, expects_format", [("llama3.2:latest", True), ("gpt-oss:20b", False), ("library/gpt-oss:120b", False)])
def test_json_format_skipped_for_reasoning_models(model, expects_format):
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"response": '{"requirements": [], "unclassified_notes": []}'})

    client = OllamaClient(
        type("Settings", (), {"ollama_base_url": "http://test", "ollama_model": model, "ollama_timeout_seconds": 1, "ollama_retries": 0})(),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.extract("untrusted input", {"domains": [], "career_levels": [], "categories": []})
    assert ("format" in sent) is expects_format
    client.close()


def test_file_parsers_reject_unsupported_and_traversal():
    assert parse_research_file("input.txt", b"Security requirement", 100)[1] == "Security requirement"
    assert "skills: Python" in parse_research_file("input.json", b'{"skills": "Python"}', 100)[1]
    assert "Kubernetes" in parse_research_file("input.csv", b"skill\nKubernetes\n", 100)[1]
    with pytest.raises(ValueError, match="path traversal"):
        parse_research_file("../input.txt", b"unsafe", 100)
    with pytest.raises(ValueError, match="supported"):
        parse_research_file("input.pdf", b"unsupported", 100)
    with pytest.raises(ValueError, match="limit"):
        parse_research_file("input.txt", b"12345", 4)


def test_domain_level_and_competency_normalization():
    domain = SecurityDomain(id=1, slug="cloud-infrastructure-security", name="Cloud Infrastructure Security")
    level = CareerLevel(id=1, slug="architect", name="Architect", career_track="technical", description="", display_order=1)
    competency = Competency(id=1, slug="kubernetes-security", name="Kubernetes Security", description="", category_id=1)
    requirement = extraction().requirements[0]
    assert classify_domain(requirement, [domain]) is domain
    assert classify_level(requirement, [level]) is None
    requirement.career_level = "architect"
    assert classify_level(requirement, [level]) is level
    assert normalize_competency("K8s", [competency]) == (competency, "Kubernetes Security")


def test_research_workflow_requires_admin_and_publishes_approved_draft(client, monkeypatch):
    monkeypatch.setattr(ollama, "extract", lambda content, taxonomy: extraction())
    payload = {"content": "Senior engineer must securely operate Kubernetes workloads.", "source_title": "Cloud security research", "source_url": "https://example.test/cloud"}
    assert client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json={**payload, "source_url": "javascript:alert(1)"}).status_code == 422
    assert client.post("/api/v1/research/submissions", json=payload).status_code == 401
    submission = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json=payload)
    assert submission.status_code == 201
    body = submission.json()
    assert body["status"] == "draft_ready"
    drafts = client.get("/api/v1/research/drafts", headers=ADMIN_HEADERS)
    assert drafts.status_code == 200
    assert drafts.json()["total"] == 1
    draft = drafts.json()["items"][0]
    assert draft["competency_name"] == "Kubernetes Security"
    assert draft["evidence"][0]["supporting_excerpt"] == "Securely operate Kubernetes workloads."

    edited = {"expectation_description": "Secure and review Kubernetes workloads.", "proficiency_level": "expert", "importance": "essential", "responsibility_type": "lead", "experience_years_min": 5, "experience_years_max": None, "reviewer_note": "Reviewed."}
    updated = client.patch(f"/api/v1/research/drafts/{draft['id']}", headers=ADMIN_HEADERS, json=edited)
    assert updated.status_code == 200
    approved = client.post(f"/api/v1/research/drafts/{draft['id']}/approve", headers=ADMIN_HEADERS, json={"reviewer_note": "Approved."})
    assert approved.status_code == 200
    published = client.post(f"/api/v1/research/drafts/{draft['id']}/publish", headers=ADMIN_HEADERS)
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    public = client.get("/api/v1/expectations?domain=cloud-infrastructure-security&level=senior")
    assert any(item["expectation_description"] == edited["expectation_description"] for item in public.json()["items"])


def test_rejection_and_duplicate_consolidation(client, monkeypatch):
    monkeypatch.setattr(ollama, "extract", lambda content, taxonomy: extraction(name="Secure Boot Chain", level="architect", excerpt="Verify startup trust."))
    first = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json={"content": "first unique research"})
    assert first.status_code == 201
    second = client.post("/api/v1/research/submissions", headers=ADMIN_HEADERS, json={"content": "second unique research"})
    assert second.status_code == 201
    drafts = client.get("/api/v1/research/drafts?status_filter=draft", headers=ADMIN_HEADERS).json()
    assert drafts["total"] == 1
    draft_id = drafts["items"][0]["id"]
    rejected = client.post(f"/api/v1/research/drafts/{draft_id}/reject", headers=ADMIN_HEADERS, json={"reviewer_note": "Insufficient evidence."})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.post(f"/api/v1/research/drafts/{draft_id}/publish", headers=ADMIN_HEADERS).status_code == 409
    assert client.get("/api/v1/research/ollama", headers=ADMIN_HEADERS).status_code == 200


def importer_for(handler, resolver=None, **settings_overrides):
    class Settings:
        url_import_max_redirects = settings_overrides.get("url_import_max_redirects", 5)
        url_import_max_bytes = settings_overrides.get("url_import_max_bytes", 100000)
        max_research_bytes = settings_overrides.get("max_research_bytes", 50000)
        url_import_timeout_seconds = 1
    def factory(destination_ip):
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return UrlImporter(Settings(), client_factory=factory, resolver=resolver or (lambda host, port: ["93.184.216.34"]))


def test_url_import_json_ld_and_html_to_text():
    html = """<html><head><script type='application/ld+json'>{\"@type\":\"JobPosting\",\"title\":\"Senior Embedded Security Engineer\",\"datePosted\":\"2026-01-15\",\"description\":\"<p>Own secure boot.</p><ul><li>Review firmware threats.</li></ul>\"}</script></head><body><nav>Unrelated navigation</nav></body></html>"""
    result = extract_job("https://jobs.example.test/security", html.encode(), 50000)
    assert result.extraction_method == "json_ld"
    assert result.job_title == "Senior Embedded Security Engineer"
    assert "Review firmware threats." in result.job_description
    assert html_to_text("<p>Required <b>skills</b></p><script>ignore()</script>") == "Required\nskills"


def test_url_import_html_fallback_and_missing_fields():
    html = "<html><head><title>Security Engineer</title></head><body><nav>Menu</nav><main><h1>Security Engineer</h1><h2>Responsibilities</h2><p>Secure product releases.</p><h2>Qualifications</h2><p>Threat modeling experience.</p></main><footer>Ads</footer></body></html>"
    result = extract_job("https://jobs.example.test/security", html.encode(), 50000)
    assert result.extraction_method == "html"
    assert "Secure product releases." in result.job_description
    with pytest.raises(UrlImportError, match="usable job title"):
        extract_job("https://jobs.example.test/security", b"<html><body><main><p>Description only</p></main></body></html>", 50000)
    with pytest.raises(UrlImportError, match="usable job description"):
        extract_job("https://jobs.example.test/security", b"<html><h1>Security Engineer</h1></html>", 50000)


def test_url_import_blocks_private_ips_and_revalidates_redirects():
    with pytest.raises(UrlImportError, match="Private"):
        validate_url("http://127.0.0.1/internal")
    result = importer_for(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text="<h1>x</h1><main><p>description</p></main>"), resolver=lambda host, port: ["93.184.216.34", "93.184.216.35"]).import_job("https://jobs.example.test/security")
    assert result.job_title == "x"
    def redirect(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
    def redirect_resolver(host, port):
        return ["127.0.0.1"] if host == "127.0.0.1" else ["93.184.216.34"]
    with pytest.raises(UrlImportError, match="Private"):
        importer_for(redirect, resolver=redirect_resolver).import_job("https://jobs.example.test/security")


def test_url_import_handles_timeout_size_and_content_type():
    def timeout(request):
        raise httpx.ReadTimeout("timed out")
    with pytest.raises(UrlImportError, match="timed out"):
        importer_for(timeout).import_job("https://jobs.example.test/security")
    def oversized(request):
        return httpx.Response(200, headers={"content-type": "text/html", "content-length": "1000"}, text="small")
    with pytest.raises(UrlImportError, match="exceeds"):
        importer_for(oversized, url_import_max_bytes=100).import_job("https://jobs.example.test/security")
    def pdf(request):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"pdf")
    with pytest.raises(UrlImportError, match="HTML"):
        importer_for(pdf).import_job("https://jobs.example.test/security")


def test_url_import_api_requires_admin_and_returns_preview(client, monkeypatch):
    assert client.post("/api/v1/research/import-url", json={"url": "https://jobs.example.test/security"}).status_code == 401
    monkeypatch.setattr(url_importer, "import_job", lambda url: ImportedJob(url, "Security Engineer", "Secure systems.", "json_ld", "2026-01-15"))
    response = client.post("/api/v1/research/import-url", headers=ADMIN_HEADERS, json={"url": "https://jobs.example.test/security"})
    assert response.status_code == 200
    assert response.json()["job_title"] == "Security Engineer"
    assert response.json()["status"] == "success"

