from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .config import get_settings
from .database import get_db
from .job_search_pipeline import create_job_search_run, execute_job_search_run, retry_job_search_results
from .job_search_providers import CollectionError, JSearchProvider, JobSearchCriteria, JobSearchItem, provider_statuses
from .models import AutomatedResearchSource, JobSearch, JobSearchResult, JobSearchRun, ResearchAutomationAudit
from .phase6_schemas import (
    JobSearchCreate, JobSearchImportRequest, JobSearchProviderResponse, JobSearchResponse,
    JobSearchResultResponse, JobSearchRunRequest, JobSearchRunResponse, JobSearchScheduleRequest,
    JobSearchUpdate, JobSearchPreviewItem, JobSearchPreviewResponse,
)

router = APIRouter(prefix="/research/automated/job-searches", tags=["automated-job-search"])
settings = get_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_status(provider_type: str) -> dict[str, Any]:
    return next((item for item in provider_statuses(settings) if item["provider_type"] == provider_type), {"provider_type": provider_type, "status": "unsupported", "display_name": provider_type, "limitations": [], "configured": False})


def _search_response(search: JobSearch) -> JobSearchResponse:
    provider = _provider_status(search.provider_type)
    return JobSearchResponse(
        id=search.id, name=search.name, provider_type=search.provider_type, provider_status=provider["status"], enabled=search.enabled,
        keywords=search.keywords or [], location=search.location, country=search.country, experience_level=search.experience_level, date_posted=search.date_posted,
        employment_type=search.employment_type, work_mode=search.work_mode, max_results=search.max_results, max_pages=search.max_pages, search_frequency=search.search_frequency,
        next_run_at=search.next_run_at, last_run_at=search.last_run_at, last_status=search.last_status, last_error=search.last_error,
        configuration=search.configuration or {},
    )


def _run_response(run: JobSearchRun) -> JobSearchRunResponse:
    return JobSearchRunResponse(
        id=run.id, search_id=run.search_id, trigger=run.trigger, status=run.status, provider_status=run.provider_status,
        provider_total=run.provider_total, pages_requested=run.pages_requested, api_requests_used=run.api_requests_used,
        results_retrieved=run.results_retrieved, unique_results=run.unique_results, results_queued=run.results_queued,
        results_unavailable=run.results_unavailable, complete_descriptions=run.complete_descriptions, partial_descriptions=run.partial_descriptions,
        descriptions_retrieved=run.descriptions_retrieved, successfully_analyzed=run.successfully_analyzed, duplicates_skipped=run.duplicates_skipped,
        manual_review_required=run.manual_review_required, failed=run.failed, rate_limit_errors=run.rate_limit_errors, quota_errors=run.quota_errors,
        summary=run.summary or {}, error_message=run.error_message,
        started_at=run.started_at, completed_at=run.completed_at, created_by=run.created_by, created_at=run.created_at,
    )


def _result_response(result: JobSearchResult) -> JobSearchResultResponse:
    return JobSearchResultResponse(
        id=result.id, search_id=result.search_id, run_id=result.run_id, title=result.title, canonical_url=result.canonical_url,
        description_url=result.description_url, location=result.location, country=result.country, employment_type=result.employment_type,
        posted_at=result.posted_at, description_complete=result.description_complete, status=result.status, content_hash=result.content_hash,
        attempt_count=result.attempt_count, error_message=result.error_message, manual_review_reason=result.manual_review_reason,
        metadata=result.metadata_payload or {}, first_seen_at=result.first_seen_at, processed_at=result.processed_at,
    )


def _get_search(db: Session, search_id: int) -> JobSearch:
    search = db.scalar(select(JobSearch).options(selectinload(JobSearch.automated_source)).where(JobSearch.id == search_id))
    if search is None:
        raise HTTPException(status_code=404, detail="Saved job search was not found")
    return search




def _jsearch_http_error(exc: CollectionError) -> HTTPException:
    code = exc.status_code if exc.status_code in {429, 503} else status.HTTP_502_BAD_GATEWAY
    return HTTPException(status_code=code, detail=str(exc))

def _preview_response(provider: JSearchProvider, page, limit: int) -> JobSearchPreviewResponse:
    return JobSearchPreviewResponse(
        provider=provider.provider_type,
        provider_total=page.total,
        items=[JobSearchPreviewItem(
            title=item.title, canonical_url=item.url, external_id=item.external_id, location=item.location,
            country=item.country, employment_type=item.employment_type, posted_at=item.posted_at,
            has_description=bool(item.description), metadata=item.metadata or {},
        ) for item in page.items[:limit]],
        pages_requested=provider.stats.pages_requested, api_requests_used=provider.stats.api_requests,
    )


@router.post("/provider-status/jsearch/test", response_model=JobSearchPreviewResponse, dependencies=[Depends(require_admin)])
def test_jsearch_connection() -> JobSearchPreviewResponse:
    provider = JSearchProvider(settings)
    try:
        return _preview_response(provider, provider.test_connection(), 1)
    except CollectionError as exc:
        raise _jsearch_http_error(exc) from exc


@router.post("/{search_id}/preview", response_model=JobSearchPreviewResponse, dependencies=[Depends(require_admin)])
def preview_search(search_id: int, db: Session = Depends(get_db)) -> JobSearchPreviewResponse:
    search = _get_search(db, search_id)
    if search.provider_type != "jsearch":
        raise HTTPException(status_code=409, detail="Preview is currently available for JSearch saved searches only")
    provider = JSearchProvider(settings)
    criteria = JobSearchCriteria(
        keywords=search.keywords or [], location=search.location, experience_level=search.experience_level,
        date_posted=search.date_posted, employment_type=search.employment_type, work_mode=search.work_mode,
        max_results=min(search.max_results, settings.jsearch_max_results_per_run), country=search.country or "us", max_pages=1,
    )
    try:
        return _preview_response(provider, provider.search(criteria, limit=min(search.max_results, 20)), min(search.max_results, 20))
    except CollectionError as exc:
        raise _jsearch_http_error(exc) from exc


@router.get("/provider-status", response_model=list[JobSearchProviderResponse], dependencies=[Depends(require_admin)])
def provider_status() -> list[JobSearchProviderResponse]:
    return [JobSearchProviderResponse(**item) for item in provider_statuses(settings)]


@router.get("", response_model=list[JobSearchResponse], dependencies=[Depends(require_admin)])
def list_searches(db: Session = Depends(get_db)) -> list[JobSearchResponse]:
    return [_search_response(search) for search in db.scalars(select(JobSearch).order_by(JobSearch.name)).all()]


@router.post("", response_model=JobSearchResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_search(payload: JobSearchCreate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchResponse:
    if db.scalar(select(JobSearch).where(JobSearch.name == payload.name)):
        raise HTTPException(status_code=409, detail="A saved job search with this name already exists")
    source = AutomatedResearchSource(
        name=f"job-search:{payload.name}", source_type="job_search", endpoint_url="https://job-search-provider.invalid/search",
        enabled=payload.enabled, collection_frequency=payload.search_frequency, interval_minutes=payload.interval_minutes,
        keywords=payload.keywords, configuration={"provider_type": payload.provider_type}, created_by=actor,
    )
    db.add(source)
    db.flush()
    search = JobSearch(automated_source_id=source.id, name=payload.name, provider_type=payload.provider_type, enabled=payload.enabled, keywords=payload.keywords, location=payload.location, country=payload.country, experience_level=payload.experience_level, date_posted=payload.date_posted, employment_type=payload.employment_type, work_mode=payload.work_mode, max_results=payload.max_results, max_pages=payload.max_pages, search_frequency=payload.search_frequency, interval_minutes=payload.interval_minutes, next_run_at=_now() if payload.enabled and payload.search_frequency != "manual" else None, configuration=payload.configuration, created_by=actor)
    db.add(search)
    db.flush()
    source.configuration = {**source.configuration, "job_search_id": search.id}
    db.add(ResearchAutomationAudit(actor=actor, action="job_search_created", source_id=source.id, details={"provider_type": search.provider_type, "search_id": search.id}))
    db.commit()
    return _search_response(_get_search(db, search.id))


@router.patch("/{search_id}", response_model=JobSearchResponse, dependencies=[Depends(require_admin)])
def update_search(search_id: int, payload: JobSearchUpdate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchResponse:
    search = _get_search(db, search_id)
    values = payload.model_dump(exclude_none=True)
    if "name" in values and db.scalar(select(JobSearch).where(JobSearch.name == values["name"], JobSearch.id != search_id)):
        raise HTTPException(status_code=409, detail="A saved job search with this name already exists")
    for key, value in values.items():
        setattr(search, key, value)
    if search.enabled and search.search_frequency != "manual" and search.next_run_at is None:
        search.next_run_at = _now()
    if not search.enabled:
        search.next_run_at = None
    search.automated_source.name = f"job-search:{search.name}"
    search.automated_source.keywords = search.keywords or []
    search.automated_source.configuration = {**(search.automated_source.configuration or {}), "provider_type": search.provider_type, "job_search_id": search.id}
    search.automated_source.enabled = search.enabled
    search.automated_source.collection_frequency = search.search_frequency
    search.automated_source.interval_minutes = search.interval_minutes
    db.add(ResearchAutomationAudit(actor=actor, action="job_search_updated", source_id=search.automated_source_id, details={"search_id": search.id, "fields": list(values)}))
    db.commit()
    return _search_response(_get_search(db, search_id))


@router.delete("/{search_id}", response_model=JobSearchResponse, dependencies=[Depends(require_admin)])
def disable_search(search_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchResponse:
    search = _get_search(db, search_id)
    search.enabled = False
    search.next_run_at = None
    search.last_status = "disabled"
    search.automated_source.enabled = False
    db.add(ResearchAutomationAudit(actor=actor, action="job_search_disabled", source_id=search.automated_source_id, details={"search_id": search.id}))
    db.commit()
    return _search_response(_get_search(db, search_id))


@router.post("/{search_id}/schedule", response_model=JobSearchResponse, dependencies=[Depends(require_admin)])
def schedule_search(search_id: int, payload: JobSearchScheduleRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchResponse:
    search = _get_search(db, search_id)
    search.search_frequency = payload.frequency
    search.interval_minutes = payload.interval_minutes
    search.enabled = payload.enabled
    search.next_run_at = _now() if payload.enabled else None
    search.automated_source.collection_frequency = payload.frequency
    search.automated_source.interval_minutes = payload.interval_minutes
    search.automated_source.enabled = payload.enabled
    db.add(ResearchAutomationAudit(actor=actor, action="job_search_scheduled", source_id=search.automated_source_id, details={"search_id": search.id, "frequency": payload.frequency}))
    db.commit()
    return _search_response(_get_search(db, search_id))


@router.post("/{search_id}/runs", response_model=JobSearchRunResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def run_search(search_id: int, payload: JobSearchRunRequest | None = None, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchRunResponse:
    search = _get_search(db, search_id)
    run = create_job_search_run(db, search, trigger="manual", actor=actor, provider_status=_provider_status(search.provider_type)["status"])
    return _run_response(execute_job_search_run(db, run, settings, max_results=payload.max_results if payload else None))


@router.post("/{search_id}/pause", response_model=JobSearchResponse, dependencies=[Depends(require_admin)])
def pause_search(search_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchResponse:
    search = _get_search(db, search_id)
    search.enabled = False
    search.next_run_at = None
    search.last_status = "paused"
    search.automated_source.enabled = False
    db.add(ResearchAutomationAudit(actor=actor, action="job_search_paused", source_id=search.automated_source_id, details={"search_id": search.id}))
    db.commit()
    return _search_response(_get_search(db, search_id))


@router.post("/{search_id}/resume", response_model=JobSearchResponse, dependencies=[Depends(require_admin)])
def resume_search(search_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchResponse:
    search = _get_search(db, search_id)
    search.enabled = True
    search.next_run_at = _now() if search.search_frequency != "manual" else None
    search.automated_source.enabled = True
    db.add(ResearchAutomationAudit(actor=actor, action="job_search_resumed", source_id=search.automated_source_id, details={"search_id": search.id}))
    db.commit()
    return _search_response(_get_search(db, search_id))


@router.post("/{search_id}/import", response_model=JobSearchRunResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def import_results(search_id: int, payload: JobSearchImportRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchRunResponse:
    search = _get_search(db, search_id)
    if search.provider_type != "import":
        raise HTTPException(status_code=409, detail="Result imports require a saved search using the import provider")
    selected = payload.items[:search.max_results]
    run = create_job_search_run(db, search, trigger="import", actor=actor, provider_status="configured")
    items = [JobSearchItem(title=item.title, url=item.url, description_url=item.description_url, description=item.description, snippet=item.snippet, location=item.location, external_id=item.external_id, metadata=item.metadata) for item in selected]
    result = execute_job_search_run(db, run, settings, imported_items=items, provider_total=payload.provider_total if payload.provider_total is not None else len(payload.items), max_results=search.max_results)
    if len(payload.items) > len(selected):
        result.summary = {**(result.summary or {}), "configured_limit_applied": search.max_results, "input_items": len(payload.items)}
        db.commit()
    return _run_response(result)


@router.get("/{search_id}/runs", response_model=list[JobSearchRunResponse], dependencies=[Depends(require_admin)])
def list_runs(search_id: int, db: Session = Depends(get_db)) -> list[JobSearchRunResponse]:
    _get_search(db, search_id)
    return [_run_response(run) for run in db.scalars(select(JobSearchRun).where(JobSearchRun.search_id == search_id).order_by(JobSearchRun.created_at.desc()).limit(100)).all()]


@router.get("/runs/{run_id}", response_model=JobSearchRunResponse, dependencies=[Depends(require_admin)])
def get_run(run_id: int, db: Session = Depends(get_db)) -> JobSearchRunResponse:
    run = db.get(JobSearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Job search run was not found")
    return _run_response(run)


@router.get("/runs/{run_id}/results", response_model=list[JobSearchResultResponse], dependencies=[Depends(require_admin)])
def list_results(run_id: int, db: Session = Depends(get_db)) -> list[JobSearchResultResponse]:
    if db.get(JobSearchRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Job search run was not found")
    return [_result_response(result) for result in db.scalars(select(JobSearchResult).where(JobSearchResult.run_id == run_id).order_by(JobSearchResult.id)).all()]


@router.post("/runs/{run_id}/retry", response_model=JobSearchRunResponse, dependencies=[Depends(require_admin)])
def retry_run(run_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> JobSearchRunResponse:
    run = db.get(JobSearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Job search run was not found")
    if run.status not in {"completed_with_errors", "failed", "blocked"}:
        raise HTTPException(status_code=409, detail="Only failed or incomplete runs can be retried")
    return _run_response(retry_job_search_results(db, run_id, settings))
