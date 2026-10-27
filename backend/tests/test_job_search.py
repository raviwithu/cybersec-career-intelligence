from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.job_search_pipeline import _deduplicate, execute_job_search_run
from app.job_search_providers import (
    CollectionError,
    ImportJobSearchProvider,
    JobSearchCriteria,
    JobSearchItem,
    JobSearchPage,
    _HTTPJobSearchProvider,
    provider_statuses,
)
from app.models import AutomatedResearchSource, JobSearch, JobSearchRun, JobSearchResult
from app.phase6_schemas import JobSearchCreate, JobSearchImportItem

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


class ProviderSettings:
    linkedin_authorized_api_base_url = None
    linkedin_authorized_api_key = None
    licensed_job_provider_base_url = None
    licensed_job_provider_api_key = None
    employer_ats_api_base_url = None
    employer_ats_api_key = None
    research_request_timeout_seconds = 1
    research_response_max_bytes = 100_000
    research_retry_count = 0
    research_retry_base_seconds = 0
    url_import_max_redirects = 2
    research_allowed_user_agent = "test-agent"
    research_default_respect_robots = False
    research_lock_ttl_seconds = 30
    job_search_retention_days = 90
    ai_provider = "ollama"
    ai_model = None
    ollama_model = "test-model"


def test_job_search_criteria_normalizes_keywords_and_rejects_secret_configuration():
    assert JobSearchCreate(name="Cloud", keywords=[" Cloud Security Engineer "]).keywords == ["Cloud Security Engineer"]
    with pytest.raises(ValueError, match="credentials"):
        JobSearchCreate(name="Secret", keywords=["security"], configuration={"api_key": "never"})
    with pytest.raises(ValueError, match="credentials"):
        JobSearchImportItem(title="Job", url="https://example.test/job", metadata={"authorization": "never"})


def test_provider_status_does_not_claim_linkedin_without_authorized_configuration():
    statuses = {item["provider_type"]: item for item in provider_statuses(ProviderSettings())}
    assert statuses["linkedin_authorized"]["status"] == "unconfigured"
    assert statuses["linkedin_authorized"]["configured"] is False
    assert statuses["import"]["status"] == "configured"


def test_search_result_pagination_and_deduplication():
    first = JobSearchPage(items=[JobSearchItem("A", "https://example.test/a?utm_source=x"), JobSearchItem("A duplicate", "https://example.test/a")], total=3, next_cursor="next")
    second = JobSearchPage(items=[JobSearchItem("B", "https://example.test/b")], total=3)

    class FakeProvider:
        def __init__(self): self.calls = []
        def search(self, criteria, *, cursor=None, limit):
            self.calls.append((cursor, limit))
            return first if cursor is None else second

    provider = FakeProvider()
    from app.job_search_pipeline import _pages
    items, total = _pages(provider, JobSearchCriteria(["security"], "", "", "any", "", "any", 3))
    unique, duplicates = _deduplicate(items)
    assert total == 3
    assert len(items) == 3
    assert len(unique) == 2
    assert duplicates == 1
    assert provider.calls == [(None, 3), ("next", 1)]


def test_import_provider_never_treats_snippet_as_complete_description():
    provider = ImportJobSearchProvider(ProviderSettings())
    item = JobSearchItem("Security role", "https://example.test/job", snippet="Short result snippet")
    with pytest.raises(CollectionError, match="complete job description"):
        provider.retrieve_description(item)


def test_http_provider_requires_complete_description_and_parses_provider_rows(monkeypatch):
    responses = iter([
        (b'{"total":1,"results":[{"id":"1","title":"Security Engineer","url":"https://example.test/job","description":"short"}]}', "application/json"),
        (b"<html><main>" + b"Complete job description content. " * 10 + b"</main></html>", "text/html"),
    ])

    class Fetcher:
        sleep = staticmethod(lambda _: None)
        def __init__(self): self.calls = []
        def fetch(self, url, **kwargs):
            self.calls.append((url, kwargs))
            body, content_type = next(responses)
            return body, content_type, 200

    fetcher = Fetcher()


    provider = _HTTPJobSearchProvider("licensed_api", "https://provider.example/search", "secret-not-persisted", ProviderSettings(), fetcher=fetcher)
    page = provider.search(JobSearchCriteria(["security"], "", "", "any", "", "any", 10), limit=10)
    assert page.total == 1
    assert fetcher.calls[0][1]["headers"]["Authorization"] == "Bearer secret-not-persisted"
    assert page.items[0].title == "Security Engineer"
    assert len(provider.retrieve_description(page.items[0])) > 120


def test_import_api_tracks_real_counts_and_manual_review(client, monkeypatch):
    created = client.post("/api/v1/research/automated/job-searches", headers=ADMIN_HEADERS, json={
        "name": "Import search progress", "provider_type": "import", "keywords": ["Product Security Engineer"], "max_results": 2,
    })
    assert created.status_code == 201, created.text
    search_id = created.json()["id"]
    monkeypatch.setattr("app.job_search_pipeline._analyze_version", lambda *args, **kwargs: True)
    imported = client.post(f"/api/v1/research/automated/job-searches/{search_id}/import", headers=ADMIN_HEADERS, json={
        "provider_total": 3,
        "items": [
            {"title": "Complete product security", "url": "https://example.test/jobs/1", "description": "Complete job description. " * 20},
            {"title": "Snippet only", "url": "https://example.test/jobs/2", "snippet": "A search snippet only"},
            {"title": "Limited by configured max", "url": "https://example.test/jobs/3", "description": "Complete job description. " * 20},
        ],
    })
    assert imported.status_code == 201, imported.text
    run = imported.json()
    assert run["provider_total"] == 3
    assert run["results_retrieved"] == 2
    assert run["unique_results"] == 2
    assert run["results_queued"] == 2
    assert run["descriptions_retrieved"] == 1
    assert run["successfully_analyzed"] == 1
    assert run["manual_review_required"] == 1
    assert run["summary"]["configured_limit_applied"] == 2
    results = client.get(f"/api/v1/research/automated/job-searches/runs/{run['id']}/results", headers=ADMIN_HEADERS)
    assert results.status_code == 200
    assert {item["status"] for item in results.json()} == {"analyzed", "manual_review_required"}


def test_job_search_run_does_not_overlap_and_reports_provider_unavailable(client):
    created = client.post("/api/v1/research/automated/job-searches", headers=ADMIN_HEADERS, json={
        "name": "Unconfigured LinkedIn search", "provider_type": "linkedin_authorized", "keywords": ["Cloud Security Engineer"],
    })
    assert created.status_code == 201
    run = client.post(f"/api/v1/research/automated/job-searches/{created.json()['id']}/runs", headers=ADMIN_HEADERS, json={})
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "blocked"
    assert run.json()["provider_status"] == "unconfigured"
    assert "authorized LinkedIn" in (run.json()["error_message"] or "")


def test_job_search_schedule_and_retry_manual_review(client, monkeypatch):
    created = client.post("/api/v1/research/automated/job-searches", headers=ADMIN_HEADERS, json={
        "name": "Retryable scheduled search", "provider_type": "import", "keywords": ["Application Security Engineer"],
    })
    assert created.status_code == 201
    search_id = created.json()["id"]
    scheduled = client.post(f"/api/v1/research/automated/job-searches/{search_id}/schedule", headers=ADMIN_HEADERS, json={"frequency": "daily", "enabled": True})
    assert scheduled.status_code == 200
    assert scheduled.json()["search_frequency"] == "daily"
    assert scheduled.json()["next_run_at"] is not None

    monkeypatch.setattr("app.job_search_pipeline._analyze_version", lambda *args, **kwargs: True)
    imported = client.post(f"/api/v1/research/automated/job-searches/{search_id}/import", headers=ADMIN_HEADERS, json={"items": [{"title": "Retry me", "url": "https://example.test/jobs/retry", "snippet": "Short snippet"}]})
    assert imported.status_code == 201
    assert imported.json()["manual_review_required"] == 1

    class CompleteProvider:
        def retrieve_description(self, item):
            return "Complete permitted employer description. " * 20

    monkeypatch.setattr("app.job_search_pipeline.build_provider", lambda *args, **kwargs: CompleteProvider())
    retried = client.post(f"/api/v1/research/automated/job-searches/runs/{imported.json()['id']}/retry", headers=ADMIN_HEADERS)
    assert retried.status_code == 200, retried.text
    assert retried.json()["successfully_analyzed"] == 1
    assert retried.json()["manual_review_required"] == 0

