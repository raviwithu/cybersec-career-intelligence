from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.database import SessionLocal
from app.models import (
    AutomatedResearchSource,
    ResearchAutomationAnalysis,
    ResearchChangeEvent,
    ResearchContentVersion,
    ResearchFinding,
    ResearchRun,
    ResearchSubmission,
    ReviewChange,
)
from app.phase5_schemas import ExtractedRequirement, ExtractionResult
from app.phase6_collectors import (
    CollectionError,
    ResearchCollector,
    SecureResearchFetcher,
    normalize_content,
    normalize_url,
    parse_feed,
)
from app.phase6_pipeline import SourceLock, create_run, execute_run
from app.phase6_schemas import AutomatedSourceCreate

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


class CollectorSettings:
    url_import_max_redirects = 3
    research_request_timeout_seconds = 1
    research_response_max_bytes = 100_000
    research_retry_count = 1
    research_retry_base_seconds = 0
    research_max_items_per_run = 10
    research_lock_ttl_seconds = 30
    max_research_bytes = 100_000
    ollama_model = "test-model"
    ai_model = None
    ai_provider = "ollama"


def test_url_and_content_normalization(monkeypatch):
    monkeypatch.setattr("app.phase6_collectors.validate_url", lambda value: value)
    assert normalize_url("HTTPS://Example.TEST/research?utm_source=news&b=2#ignored") == "https://example.test/research?b=2"
    assert normalize_content(" A\n\t cybersecurity   finding ") == "A cybersecurity finding"



def test_source_configuration_rejects_private_destinations_and_secrets():
    with pytest.raises(ValueError, match="private"):
        AutomatedSourceCreate(name="Local", source_type="html", endpoint_url="http://127.0.0.1/admin")
    with pytest.raises(ValueError, match="credentials"):
        AutomatedSourceCreate(name="Secret", source_type="public_api", endpoint_url="https://example.test/api", configuration={"headers": {"api_key": "do-not-store"}})


def test_source_lock_falls_back_to_process_local_lock_when_redis_unavailable():
    settings = SimpleNamespace(redis_url="redis://127.0.0.1:6399/0", research_lock_ttl_seconds=2)
    first = SourceLock(settings, "test-lock")
    second = SourceLock(settings, "test-lock")
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_feed_adapter_extracts_atom_and_rss_entries(monkeypatch):
    monkeypatch.setattr("app.phase6_collectors.validate_url", lambda value: value)
    feed = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Cloud security research</title><link href='https://example.test/cloud?utm_medium=x'/><summary>Long enough cybersecurity research content for analysis.</summary><updated>2026-01-01T00:00:00Z</updated></entry></feed>"""
    items = parse_feed("https://example.test/feed", feed)
    assert len(items) == 1
    assert items[0].title == "Cloud security research"
    assert items[0].url == "https://example.test/cloud"
    assert items[0].published_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_public_api_adapter_uses_configured_fields_and_bounded_transport():
    payload = b'{"results":[{"headline":"API research","href":"https://example.test/item","body":"A cybersecurity research finding with evidence."}]}'

    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, content=payload)

    fetcher = SecureResearchFetcher(
        CollectorSettings(),
        client_factory=lambda ip: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
        resolver=lambda host, port: ["93.184.216.34"],
        sleep=lambda _: None,
    )
    source = SimpleNamespace(
        source_type="public_api", endpoint_url="https://example.test/api",
        configuration={"items_path": "results", "title_field": "headline", "url_field": "href", "content_field": "body"},
    )
    items = ResearchCollector(CollectorSettings(), fetcher).collect(source)
    assert [(item.title, item.url) for item in items] == [("API research", "https://example.test/item")]


def test_fetcher_rejects_permanent_access_denial_without_retry():
    attempts = []

    def handler(request):
        attempts.append(request.url.path)
        return httpx.Response(403, headers={"content-type": "text/html"})

    fetcher = SecureResearchFetcher(
        CollectorSettings(),
        client_factory=lambda ip: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
        resolver=lambda host, port: ["93.184.216.34"],
        sleep=lambda _: None,
    )
    source = SimpleNamespace(source_type="html", endpoint_url="https://example.test/research", configuration={"respect_robots": False})
    with pytest.raises(CollectionError, match="403") as error:
        ResearchCollector(CollectorSettings(), fetcher).collect(source)
    assert error.value.retryable is False
    assert attempts == ["/research"]


def test_automated_source_registry_schedule_run_auth_and_coverage(client, monkeypatch):
    assert client.get("/api/v1/research/automated/sources").status_code == 401
    created = client.post("/api/v1/research/automated/sources", headers=ADMIN_HEADERS, json={
        "name": "Approved Cyber Research Feed", "source_type": "rss", "endpoint_url": "https://example.test/feed",
        "collection_frequency": "manual", "configuration": {"respect_robots": True},
    })
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["source_type"] == "rss"
    schedule = client.post(f"/api/v1/research/automated/sources/{source['id']}/schedule", headers=ADMIN_HEADERS, json={"frequency": "daily", "enabled": True})
    assert schedule.status_code == 200
    assert schedule.json()["schedule"]["frequency"] == "daily"
    paused = client.post(f"/api/v1/research/automated/sources/{source['id']}/pause", headers=ADMIN_HEADERS)
    assert paused.status_code == 200 and paused.json()["schedule"]["paused"] is True
    resumed = client.post(f"/api/v1/research/automated/sources/{source['id']}/resume", headers=ADMIN_HEADERS)
    assert resumed.status_code == 200 and resumed.json()["schedule"]["paused"] is False
    monkeypatch.setattr("app.phase6_api.execute_run", lambda db, run, settings: run)
    started = client.post("/api/v1/research/automated/runs", headers=ADMIN_HEADERS, json={"source_ids": [source["id"]]})
    assert started.status_code == 201, started.text
    assert started.json()["trigger"] == "manual"
    dashboard = client.get("/api/v1/research/automated/dashboard", headers=ADMIN_HEADERS)
    assert dashboard.status_code == 200
    assert dashboard.json()["overview"]["active_research_sources"] == 1
    coverage = client.get("/api/v1/research/automated/coverage", headers=ADMIN_HEADERS)
    assert coverage.status_code == 200
    assert coverage.json()["thresholds"] == {"limited_evidence": 1, "adequate_evidence": 3, "adequate_sources": 2}
    assert all(cell["label"] == "none" for cell in coverage.json()["cells"])
    disabled = client.delete(f"/api/v1/research/automated/sources/{source['id']}", headers=ADMIN_HEADERS)
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False


def extraction_result():
    return ExtractionResult(requirements=[ExtractedRequirement(
        domain_slugs=["cloud-infrastructure-security"], career_level="senior", competency_name="Kubernetes Security",
        category_slug="tools-technologies", technical_knowledge="Kubernetes workload controls",
        practical_capability="Secure Kubernetes workloads.", responsibilities="Review workload security.",
        evidence_excerpt="The study requires secure Kubernetes workloads.", confidence=None,
    )])


class FakeAI:
    model = "test-model"

    def extract(self, content, taxonomy, model=None):
        return extraction_result()


def test_pipeline_creates_provenance_review_records_and_skips_unchanged_content():
    settings = CollectorSettings()
    item = SimpleNamespace(title="Cloud research", url="https://example.test/item", content="Secure Kubernetes workloads with evidence.", metadata={"source": "test"})

    class FakeCollector:
        def __init__(self):
            self.items = [item]

        def collect(self, source):
            return self.items

    with SessionLocal() as db:
        source = AutomatedResearchSource(name="Pipeline test source", source_type="url_collection", endpoint_url="https://example.test/list", enabled=True, collection_frequency="manual", configuration={"urls": ["https://example.test/item"]})
        db.add(source)
        db.commit()
        db.refresh(source)
        collector = FakeCollector()
        baseline_submissions = db.scalar(select_count(ResearchSubmission))
        baseline_versions = db.scalar(select_count(ResearchContentVersion))
        baseline_findings = db.scalar(select_count(ResearchFinding))
        baseline_changes = db.scalar(select_count(ReviewChange))
        baseline_analyses = db.scalar(select_count(ResearchAutomationAnalysis))
        baseline_events = db.scalar(select_count(ResearchChangeEvent))
        run = create_run(db, source_ids=[source.id], filters={}, trigger="manual", actor="test-admin")
        completed = execute_run(db, run, settings, collector=collector, provider_registry=FakeAI())
        assert completed.status == "completed"
        assert completed.sources_collected == 1
        assert completed.sources_analyzed == 1
        assert db.scalar(select_count(ResearchContentVersion)) == baseline_versions + 1
        assert db.scalar(select_count(ResearchSubmission)) == baseline_submissions + 1
        assert db.scalar(select_count(ResearchFinding)) == baseline_findings + 1
        assert db.scalar(select_count(ReviewChange)) == baseline_changes + 1
        assert db.scalar(select_count(ResearchAutomationAnalysis)) == baseline_analyses + 1

        second = create_run(db, source_ids=[source.id], filters={}, trigger="manual", actor="test-admin")
        completed_second = execute_run(db, second, settings, collector=collector, provider_registry=FakeAI())
        assert completed_second.duplicates_skipped == 1
        assert db.scalar(select_count(ResearchContentVersion)) == baseline_versions + 1

        changed = SimpleNamespace(title=item.title, url=item.url, content="Secure Kubernetes workloads and incident response evidence.", metadata={})
        collector.items = [changed]
        third = create_run(db, source_ids=[source.id], filters={}, trigger="manual", actor="test-admin")
        completed_third = execute_run(db, third, settings, collector=collector, provider_registry=FakeAI())
        assert completed_third.sources_collected == 1
        assert db.scalar(select_count(ResearchChangeEvent)) == baseline_events + 1
        assert db.scalar(select_count(ResearchContentVersion)) == baseline_versions + 2


def select_count(model):
    from sqlalchemy import func, select

    return select(func.count()).select_from(model)
