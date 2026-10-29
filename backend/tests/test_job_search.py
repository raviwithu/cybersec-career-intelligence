import json
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


def test_jsearch_connection_does_not_call_network_when_unconfigured(client):
    response = client.post("/api/v1/research/automated/job-searches/provider-status/jsearch/test", headers=ADMIN_HEADERS)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]

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


def test_job_search_rename_updates_automation_source(client):
    created = client.post("/api/v1/research/automated/job-searches", headers=ADMIN_HEADERS, json={"name": "Original search", "provider_type": "import", "keywords": ["security"]})
    assert created.status_code == 201
    search_id = created.json()["id"]
    updated = client.patch(f"/api/v1/research/automated/job-searches/{search_id}", headers=ADMIN_HEADERS, json={"name": "Renamed search"})
    assert updated.status_code == 200
    with SessionLocal() as db:
        search = db.get(JobSearch, search_id)
        assert search.automated_source.name == "job-search:Renamed search"




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



class JSearchFetcher:
    sleep = staticmethod(lambda _: None)

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response, "application/json", 200


def jsearch_settings(**overrides):
    values = {
        "jsearch_api_key": "rapid-secret",
        "jsearch_api_host": "jsearch.p.rapidapi.com",
        "jsearch_api_endpoint": "https://jsearch.p.rapidapi.com/search",
        "jsearch_job_details_endpoint": "https://jsearch.p.rapidapi.com/job-details",
        "jsearch_timeout_seconds": 3,
        "jsearch_max_requests_per_run": 10,
        "jsearch_max_pages_per_run": 3,
        "jsearch_retry_count": 2,
        "jsearch_retry_base_seconds": 0,
        "jsearch_rate_limit_sleep_seconds": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_jsearch_parses_official_fields_paginates_and_fetches_details():
    first_page = {
        "status": "OK", "estimated_total": 2, "data": [{
            "job_id": "j-1", "job_title": "Cloud Security Engineer", "job_apply_link": "https://jobs.example/one",
            "job_description": "Short listing", "job_city": "Austin", "job_state": "TX", "job_country": "US",
            "job_employment_type": "FULLTIME", "job_posted_at_datetime_utc": "2026-10-01T10:00:00Z",
            "job_required_skills": ["AWS", "Terraform"], "job_is_remote": False,
        }],
    }
    second_page = {"status": "OK", "data": [{
        "job_id": "j-2", "job_title": "Product Security Engineer", "job_apply_link": "https://jobs.example/two",
        "job_description": "Complete product security description " * 8, "job_country": "US", "job_employment_type": "CONTRACTOR",
    }]}
    details = {"status": "OK", "data": [{"job_description": "Complete cloud security description " * 8}]}
    fetcher = JSearchFetcher([json.dumps(first_page).encode(), json.dumps(second_page).encode(), json.dumps(details).encode()])
    from app.job_search_providers import JSearchProvider

    provider = JSearchProvider(jsearch_settings(), fetcher=fetcher)
    criteria = JobSearchCriteria(["security engineer"], "Austin", "", "all", "", "any", 2, "us", 2)
    page = provider.search(criteria, limit=1)
    next_page = provider.search(criteria, cursor=page.next_cursor, limit=1)
    description = provider.retrieve_description(page.items[0])

    assert page.total == 2
    assert page.next_cursor == "2"
    assert next_page.items[0].employment_type == "CONTRACTOR"
    assert "job_required_skills" not in next_page.items[0].metadata
    assert len(description) > 120
    assert fetcher.calls[0][1]["headers"]["X-RapidAPI-Key"] == "rapid-secret"
    assert fetcher.calls[0][1]["headers"]["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"
    assert provider.stats.pages_requested == 2
    assert provider.stats.api_requests == 3
    assert "rapid-secret" not in str(page.items[0].metadata)


def test_jsearch_v2_parses_jobs_and_follows_api_cursor():
    first_page = {"status": "OK", "data": {"cursor": "api-cursor-2", "jobs": [{
        "job_id": "v2-1", "job_title": "Security Manager", "job_apply_link": "https://jobs.example/v2-one",
        "job_description": "Complete security manager description " * 8, "job_country": "US",
    }]}}
    last_page = {"status": "OK", "data": {"cursor": None, "jobs": [{
        "job_id": "v2-2", "job_title": "Information Security Manager", "job_apply_link": "https://jobs.example/v2-two",
        "job_description": "Complete information security description " * 8, "job_country": "US",
    }]}}
    fetcher = JSearchFetcher([json.dumps(first_page).encode(), json.dumps(last_page).encode()])
    from app.job_search_providers import JSearchProvider

    provider = JSearchProvider(jsearch_settings(), fetcher=fetcher)
    criteria = JobSearchCriteria(["security manager"], "", "", "today", "", "any", 10, "us", 3)
    page = provider.search(criteria, limit=10)
    next_page = provider.search(criteria, cursor=page.next_cursor, limit=10)

    assert page.items[0].title == "Security Manager"
    assert page.next_cursor == "2:api-cursor-2"
    assert "cursor=api-cursor-2" in fetcher.calls[1][0]
    assert "page=" not in fetcher.calls[1][0]
    assert next_page.items[0].title == "Information Security Manager"
    assert next_page.next_cursor is None


def test_jsearch_rate_limit_retries_and_request_budget():
    from app.job_search_providers import JSearchProvider

    fetcher = JSearchFetcher([
        CollectionError("rate limited", status_code=429, retryable=True),
        b'{"status":"OK","data":[]}',
    ])
    provider = JSearchProvider(jsearch_settings(), fetcher=fetcher)
    page = provider.search(JobSearchCriteria(["security"], "", "", "all", "", "any", 1), limit=1)
    assert page.items == []
    assert provider.stats.rate_limit_errors == 1
    assert provider.stats.api_requests == 2

    limited = JSearchProvider(jsearch_settings(jsearch_max_requests_per_run=1), fetcher=JSearchFetcher([b'{"status":"OK","data":[]}']))
    limited.search(JobSearchCriteria(["security"], "", "", "all", "", "any", 1), limit=1)
    with pytest.raises(CollectionError, match="request budget"):
        limited.search(JobSearchCriteria(["security"], "", "", "all", "", "any", 1), limit=1)
    assert limited.stats.quota_errors == 1


def test_jsearch_run_invokes_analysis_for_each_complete_description(client, monkeypatch):
    created = client.post("/api/v1/research/automated/job-searches", headers=ADMIN_HEADERS, json={
        "name": "JSearch analysis coverage", "provider_type": "jsearch", "keywords": ["security"], "max_results": 2,
    })
    assert created.status_code == 201, created.text

    class Provider:
        provider_type = "jsearch"
        def __init__(self): self.analyzed = 0
        def search(self, criteria, *, cursor=None, limit):
            return JobSearchPage(items=[JobSearchItem("One", "https://jobs.example/one"), JobSearchItem("Two", "https://jobs.example/two")], total=2)
        def retrieve_description(self, item):
            self.analyzed += 1
            return f"Complete description for {item.title}. " * 15

    provider = Provider()
    monkeypatch.setattr("app.job_search_pipeline.build_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr("app.job_search_pipeline._analyze_version", lambda *args, **kwargs: True)
    run = client.post(f"/api/v1/research/automated/job-searches/{created.json()['id']}/runs", headers=ADMIN_HEADERS, json={})
    assert run.status_code == 201, run.text
    assert run.json()["descriptions_retrieved"] == 2
    assert run.json()["successfully_analyzed"] == 2
    assert provider.analyzed == 2

