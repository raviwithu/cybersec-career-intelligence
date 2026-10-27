from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .ai_providers import AIProviderRegistry
from .config import Settings
from .models import AutomatedResearchSource, JobSearch, JobSearchResult, JobSearchRun, ResearchChangeEvent, ResearchContentVersion
from .phase6_collectors import CollectedItem, CollectionError, normalize_content, normalize_url
from .phase5_api import providers
from .phase6_pipeline import SourceLock, _analyze_version, _create_version, now
from .job_search_providers import JobSearchCriteria, JobSearchItem, JobSearchPage, JobSearchProvider, build_provider


def create_job_search_run(db: Session, search: JobSearch, *, trigger: str, actor: str, provider_status: str = "unconfigured") -> JobSearchRun:
    run = JobSearchRun(search_id=search.id, trigger=trigger, status="queued", provider_status=provider_status, created_by=actor)
    db.add(run)
    search.last_status = "queued"
    db.commit()
    db.refresh(run)
    return run


def _criteria(search: JobSearch, max_results: int | None = None) -> JobSearchCriteria:
    return JobSearchCriteria(
        keywords=search.keywords or [], location=search.location, experience_level=search.experience_level,
        date_posted=search.date_posted, employment_type=search.employment_type, work_mode=search.work_mode,
        max_results=max_results or search.max_results,
    )


def _fingerprint(content: str) -> str:
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def _job_item_url(item: JobSearchItem) -> str:
    return normalize_url(item.url)


def _deduplicate(items: Iterable[JobSearchItem]) -> tuple[list[JobSearchItem], int]:
    unique: list[JobSearchItem] = []
    seen: set[str] = set()
    duplicates = 0
    for item in items:
        canonical = _job_item_url(item)
        key = f"id:{item.external_id}" if item.external_id else f"url:{canonical}"
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(JobSearchItem(**{**item.__dict__, "url": canonical}))
    return unique, duplicates


def _complete_description(provider: JobSearchProvider, item: JobSearchItem) -> str:
    return normalize_content(provider.retrieve_description(item))


def _mark_change_run(db: Session, version_id: int, run_id: int) -> None:
    event = db.scalar(select(ResearchChangeEvent).where(ResearchChangeEvent.current_version_id == version_id).order_by(ResearchChangeEvent.id.desc()))
    if event is not None and event.run_id is None:
        event.run_id = run_id


def _process_result(db: Session, run: JobSearchRun, search: JobSearch, source: AutomatedResearchSource, result: JobSearchResult, item: JobSearchItem, provider: JobSearchProvider, settings: Settings, provider_registry: AIProviderRegistry) -> None:
    result.attempt_count += 1
    was_manual_review = result.status == "manual_review_required"
    try:
        description = _complete_description(provider, item)
        result.description_text = description
        result.content_hash = _fingerprint(description)
        run.descriptions_retrieved += 1
        if was_manual_review:
            run.results_unavailable = max(0, run.results_unavailable - 1)
        version, duplicate, duplicate_version = _create_version(db, source, CollectedItem(title=item.title, url=item.url, content=description, metadata={**(item.metadata or {}), "job_search_id": search.id, "job_search_result_id": result.id, "provider_type": search.provider_type}))
        db.flush()
        result.content_version_id = version.id if version else None
        if duplicate:
            result.status = "duplicate"
            result.duplicate_of_id = duplicate_version.id if duplicate_version else None
            run.duplicates_skipped += 1
            return
        _mark_change_run(db, version.id, run.id)
        if _analyze_version(db, version, source, settings, provider_registry):
            result.status = "analyzed"
            run.successfully_analyzed += 1
        else:
            result.status = "failed"
            result.error_message = "AI analysis failed; retry is available"
            run.failed += 1
    except CollectionError as exc:
        result.status = "manual_review_required" if exc.status_code == 422 else "failed"
        result.manual_review_reason = str(exc) if result.status == "manual_review_required" else None
        result.error_message = str(exc)
        if result.status == "manual_review_required":
            run.manual_review_required += 1
            run.results_unavailable += 1
        else:
            run.failed += 1
    except (ValueError, TypeError) as exc:
        result.status = "failed"
        result.error_message = str(exc)[:500]
        run.failed += 1
    result.processed_at = now()


def _pages(provider: JobSearchProvider, criteria: JobSearchCriteria) -> tuple[list[JobSearchItem], int | None]:
    items: list[JobSearchItem] = []
    cursor: str | None = None
    reported_total: int | None = None
    while len(items) < criteria.max_results:
        page_limit = min(100, criteria.max_results - len(items))
        page = provider.search(criteria, cursor=cursor, limit=page_limit)
        if reported_total is None:
            reported_total = page.total
        items.extend(page.items[:page_limit])
        if not page.next_cursor or not page.items:
            break
        cursor = page.next_cursor
    return items, reported_total


def execute_job_search_run(db: Session, run: JobSearchRun, settings: Settings, *, provider: JobSearchProvider | None = None, provider_registry: AIProviderRegistry | None = None, imported_items: list[JobSearchItem] | None = None, provider_total: int | None = None, max_results: int | None = None) -> JobSearchRun:
    search = db.scalar(select(JobSearch).options(selectinload(JobSearch.automated_source)).where(JobSearch.id == run.search_id))
    if search is None:
        run.status = "failed"
        run.error_message = "Saved job search no longer exists"
        db.commit()
        return run
    source = search.automated_source
    provider_registry = provider_registry or providers
    run.status = "running"
    run.started_at = now()
    search.last_status = "running"
    search.last_run_at = now()
    db.commit()
    lock = SourceLock(settings, f"cybersec:research:job-search:{search.id}")
    if not lock.acquire():
        run.status = "skipped_overlap"
        run.error_message = "Another execution for this saved search is already running"
        run.completed_at = now()
        db.commit()
        return run
    try:
        provider = provider or build_provider(search.provider_type, settings)
        run.provider_status = "configured"
        criteria = _criteria(search, max_results)
        discovered, reported_total = (imported_items or [], provider_total) if imported_items is not None else _pages(provider, criteria)
        unique, duplicate_count = _deduplicate(discovered)
        run.provider_total = reported_total
        run.results_retrieved = len(discovered)
        run.unique_results = len(unique)
        run.duplicates_skipped = duplicate_count
        search.configuration = {**(search.configuration or {}), "last_provider_total": reported_total, "last_retrieved": len(discovered), "last_unique": len(unique)}
        for item in unique:
            result = JobSearchResult(search_id=search.id, run_id=run.id, external_id=item.external_id, canonical_url=item.url, title=item.title[:300], location=item.location[:300], snippet=item.snippet[:20_000], description_url=item.description_url, metadata_payload=item.metadata or {})
            db.add(result)
            db.flush()
            run.results_queued += 1
            _process_result(db, run, search, source, result, item, provider, settings, provider_registry)
        run.requested_result_ids = [result.id for result in run.results]
        run.status = "completed_with_errors" if run.failed or run.manual_review_required else "completed"
        search.last_status = run.status
        search.last_error = None if run.status == "completed" else "One or more results require review or retry"
    except Exception as exc:
        db.rollback()
        run = db.get(JobSearchRun, run.id)
        search = db.get(JobSearch, search.id)
        run.status = "blocked" if run.provider_status != "configured" else "failed"
        run.error_message = str(exc)[:500]
        search.last_status = run.status
        search.last_error = run.error_message
    finally:
        run.completed_at = now()
        run.summary = {
            "provider_total": run.provider_total, "results_retrieved": run.results_retrieved, "unique_results": run.unique_results,
            "results_queued": run.results_queued, "descriptions_retrieved": run.descriptions_retrieved,
            "successfully_analyzed": run.successfully_analyzed, "duplicates_skipped": run.duplicates_skipped,
            "manual_review_required": run.manual_review_required, "failed": run.failed,
        }
        db.commit()
        lock.release()
    return run


def retry_job_search_results(db: Session, run_id: int, settings: Settings, *, provider_registry: AIProviderRegistry | None = None) -> JobSearchRun:
    run = db.scalar(select(JobSearchRun).options(selectinload(JobSearchRun.search).selectinload(JobSearch.automated_source), selectinload(JobSearchRun.results)).where(JobSearchRun.id == run_id))
    if run is None:
        raise ValueError("job search run was not found")
    search = run.search
    source = search.automated_source
    provider = build_provider(search.provider_type, settings)
    run.status = "running"
    run.error_message = None
    run.failed = 0
    run.manual_review_required = 0
    run.started_at = now()
    db.commit()
    lock = SourceLock(settings, f"cybersec:research:job-search:{search.id}")
    if not lock.acquire():
        run.status = "skipped_overlap"
        run.completed_at = now()
        db.commit()
        return run
    try:
        for result in run.results:
            if result.status not in {"failed", "manual_review_required"}:
                continue
            item = JobSearchItem(title=result.title, url=result.canonical_url, description_url=result.description_url, description=result.description_text, snippet=result.snippet, location=result.location, external_id=result.external_id, metadata=result.metadata_payload)
            _process_result(db, run, search, source, result, item, provider, settings, provider_registry or providers)
        run.status = "completed_with_errors" if run.failed or run.manual_review_required else "completed"
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:500]
    finally:
        run.completed_at = now()
        db.commit()
        lock.release()
    return run


def purge_expired_job_search_records(db: Session, settings: Settings) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.job_search_retention_days)
    old_runs = list(db.scalars(select(JobSearchRun).where(JobSearchRun.created_at < cutoff)).all())
    for run in old_runs:
        db.delete(run)
    db.commit()
    return len(old_runs)


def run_due_job_searches(settings: Settings) -> int:
    from .database import SessionLocal

    count = 0
    with SessionLocal() as db:
        purge_expired_job_search_records(db, settings)
        searches = list(db.scalars(select(JobSearch).where(JobSearch.enabled.is_(True), JobSearch.search_frequency != "manual", JobSearch.next_run_at.is_not(None), JobSearch.next_run_at <= now())).all())
        for search in searches:
            run = create_job_search_run(db, search, trigger="scheduled", actor="scheduler")
            search.next_run_at = now() + timedelta(days=1 if search.search_frequency == "daily" else 7)
            db.commit()
            execute_job_search_run(db, run, settings)
            count += 1
    return count
