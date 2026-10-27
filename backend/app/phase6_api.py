from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .config import get_settings
from .database import get_db
from .models import (
    AutomatedResearchSource,
    CareerLevel,
    Industry,
    ResearchAutomationAudit,
    ResearchChangeEvent,
    ResearchCollectionAttempt,
    ResearchContentVersion,
    ResearchFinding,
    ResearchFindingDomain,
    ResearchRun,
    ResearchSchedule,
    ResearchSource,
    ResearchSubmission,
    ReviewChange,
    SecurityDomain,
)
from .phase6_pipeline import create_run, execute_run, schedule_delta, schedule_next
from .phase6_schemas import (
    AutomatedChangeResponse,
    AutomatedDashboardResponse,
    AutomatedSourceCreate,
    AutomatedSourceResponse,
    AutomatedSourceUpdate,
    CollectionAttemptResponse,
    CoverageCell,
    CoverageResponse,
    ResearchRunResponse,
    RunStartRequest,
    ScheduleRequest,
)

router = APIRouter(prefix="/research/automated", tags=["automated-research"])
settings = get_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_response(run: ResearchRun) -> ResearchRunResponse:
    return ResearchRunResponse(
        id=run.id, trigger=run.trigger, status=run.status, requested_source_ids=run.requested_source_ids or [],
        target_filters=run.target_filters or {}, sources_collected=run.sources_collected, sources_analyzed=run.sources_analyzed,
        duplicates_skipped=run.duplicates_skipped, failed_collections=run.failed_collections, started_at=run.started_at,
        completed_at=run.completed_at, error_message=run.error_message, summary=run.summary or {}, created_by=run.created_by,
        created_at=run.created_at,
    )


def _source_response(source: AutomatedResearchSource) -> AutomatedSourceResponse:
    schedule = source.schedule
    return AutomatedSourceResponse(
        id=source.id, name=source.name, source_type=source.source_type, endpoint_url=source.endpoint_url,
        enabled=source.enabled, collection_frequency=source.collection_frequency, interval_minutes=source.interval_minutes,
        applicable_industries=source.applicable_industries or [], applicable_domains=source.applicable_domains or [],
        applicable_career_levels=source.applicable_career_levels or [], keywords=source.keywords or [],
        configuration=source.configuration or {}, collection_status=source.collection_status,
        last_successful_collection=source.last_successful_collection, last_attempted_collection=source.last_attempted_collection,
        next_run_at=source.next_run_at, last_error=source.last_error,
        schedule={"id": schedule.id, "frequency": schedule.frequency, "interval_minutes": schedule.interval_minutes, "enabled": schedule.enabled, "paused": schedule.paused, "next_run_at": schedule.next_run_at, "last_run_at": schedule.last_run_at} if schedule else None,
    )


def _get_source(db: Session, source_id: int) -> AutomatedResearchSource:
    source = db.scalar(select(AutomatedResearchSource).options(selectinload(AutomatedResearchSource.schedule)).where(AutomatedResearchSource.id == source_id))
    if source is None:
        raise HTTPException(status_code=404, detail="Automated research source was not found")
    return source


def _filters(payload: RunStartRequest) -> dict[str, Any]:
    return {key: value for key, value in {"industry": payload.industry, "domain": payload.domain, "career_level": payload.career_level, "keywords": payload.keywords, "date_from": payload.date_from.isoformat() if payload.date_from else None, "date_to": payload.date_to.isoformat() if payload.date_to else None}.items() if value not in (None, "", [])}


@router.get("/dashboard", response_model=AutomatedDashboardResponse, dependencies=[Depends(require_admin)])
def dashboard(db: Session = Depends(get_db)) -> AutomatedDashboardResponse:
    source_count = db.scalar(select(func.count()).select_from(AutomatedResearchSource).where(AutomatedResearchSource.enabled.is_(True), AutomatedResearchSource.source_type != "job_search")) or 0
    run_rows = list(db.scalars(select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(10)).all())
    last_run = db.scalar(select(ResearchRun).order_by(ResearchRun.created_at.desc()))
    next_run = db.scalar(select(func.min(ResearchSchedule.next_run_at)).where(ResearchSchedule.enabled.is_(True), ResearchSchedule.paused.is_(False)))
    pending = db.scalar(select(func.count()).select_from(ReviewChange).join(ResearchSubmission).join(ResearchSource, ResearchSubmission.source_id == ResearchSource.id).where(ReviewChange.status == "pending", ResearchSource.source_type.like("automated_%"))) or 0
    totals = db.execute(select(func.coalesce(func.sum(ResearchRun.sources_collected), 0), func.coalesce(func.sum(ResearchRun.sources_analyzed), 0), func.coalesce(func.sum(ResearchRun.duplicates_skipped), 0), func.coalesce(func.sum(ResearchRun.failed_collections), 0))).one()
    events = list(db.scalars(select(ResearchChangeEvent).order_by(ResearchChangeEvent.detected_at.desc()).limit(10)).all())
    overview = {
        "active_research_sources": source_count, "last_research_run": last_run.completed_at if last_run else None,
        "next_scheduled_run": next_run, "sources_collected": totals[0], "sources_successfully_analyzed": totals[1],
        "duplicate_sources_skipped": totals[2], "failed_collections": totals[3], "new_findings_awaiting_review": pending,
        "domain_coverage": _coverage_summary(db, "domain"), "industry_coverage": _coverage_summary(db, "industry"),
        "career_level_coverage": _coverage_summary(db, "career_level"),
    }
    return AutomatedDashboardResponse(overview=overview, recent_runs=[_run_response(run) for run in run_rows], pending_findings=pending, change_events=[_event_response(db, event) for event in events])


def _coverage_summary(db: Session, dimension: str) -> dict[str, int]:
    if dimension == "domain":
        rows = db.execute(select(SecurityDomain.slug, func.count(ResearchFinding.id)).join(ResearchFindingDomain, ResearchFindingDomain.domain_id == SecurityDomain.id).join(ResearchFinding, ResearchFinding.id == ResearchFindingDomain.finding_id).join(ResearchSubmission).join(ResearchSource, ResearchSubmission.source_id == ResearchSource.id).where(ResearchSource.source_type.like("automated_%")).group_by(SecurityDomain.slug)).all()
    elif dimension == "industry":
        rows = db.execute(select(Industry.slug, func.count(ResearchFinding.id)).join(ResearchFinding, ResearchFinding.primary_industry_id == Industry.id).join(ResearchSubmission).join(ResearchSource, ResearchSubmission.source_id == ResearchSource.id).where(ResearchSource.source_type.like("automated_%")).group_by(Industry.slug)).all()
    else:
        rows = db.execute(select(CareerLevel.slug, func.count(ResearchFinding.id)).join(ResearchFinding, ResearchFinding.career_level_id == CareerLevel.id).join(ResearchSubmission).join(ResearchSource, ResearchSubmission.source_id == ResearchSource.id).where(ResearchSource.source_type.like("automated_%")).group_by(CareerLevel.slug)).all()
    return {"covered": sum(1 for _, count in rows if count >= 1), "adequate": sum(1 for _, count in rows if count >= 3), "total": len(rows)}


def _event_response(db: Session, event: ResearchChangeEvent) -> dict[str, Any]:
    source = db.get(AutomatedResearchSource, event.registry_source_id)
    current = db.get(ResearchContentVersion, event.current_version_id)
    return {"id": event.id, "source_id": event.registry_source_id, "run_id": event.run_id, "change_type": event.change_type, "summary": event.summary or {}, "status": event.status, "detected_at": event.detected_at, "source_name": source.name if source else None, "source_url": current.canonical_url if current else None}


@router.get("/sources", response_model=list[AutomatedSourceResponse], dependencies=[Depends(require_admin)])
def list_sources(db: Session = Depends(get_db)) -> list[AutomatedSourceResponse]:
    return [_source_response(source) for source in db.scalars(select(AutomatedResearchSource).options(selectinload(AutomatedResearchSource.schedule)).where(AutomatedResearchSource.source_type != "job_search").order_by(AutomatedResearchSource.name)).all()]


@router.post("/sources", response_model=AutomatedSourceResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_source(payload: AutomatedSourceCreate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> AutomatedSourceResponse:
    if db.scalar(select(AutomatedResearchSource).where(AutomatedResearchSource.name == payload.name)):
        raise HTTPException(status_code=409, detail="An automated research source with this name already exists")
    item = AutomatedResearchSource(**payload.model_dump(), created_by=actor)
    db.add(item)
    db.flush()
    if payload.collection_frequency != "manual":
        schedule = ResearchSchedule(source_id=item.id, frequency=payload.collection_frequency, interval_minutes=payload.interval_minutes, enabled=payload.enabled, paused=False, next_run_at=_now() if payload.enabled else None)
        db.add(schedule)
        item.next_run_at = schedule.next_run_at
    db.add(ResearchAutomationAudit(actor=actor, action="source_created", source_id=item.id, details={"source_type": item.source_type}))
    db.commit()
    return _source_response(_get_source(db, item.id))


@router.patch("/sources/{source_id}", response_model=AutomatedSourceResponse, dependencies=[Depends(require_admin)])
def update_source(source_id: int, payload: AutomatedSourceUpdate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> AutomatedSourceResponse:
    item = _get_source(db, source_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(item, key, value)
    if item.schedule:
        if payload.collection_frequency is not None:
            item.schedule.frequency = payload.collection_frequency
        if payload.interval_minutes is not None:
            item.schedule.interval_minutes = payload.interval_minutes
        if payload.enabled is not None:
            item.schedule.enabled = payload.enabled
        if item.schedule.enabled and not item.schedule.paused and item.schedule.next_run_at is None:
            item.schedule.next_run_at = _now()
        item.next_run_at = item.schedule.next_run_at
    elif item.collection_frequency != "manual":
        item.schedule = ResearchSchedule(frequency=item.collection_frequency, interval_minutes=item.interval_minutes, enabled=item.enabled, next_run_at=_now() if item.enabled else None)
        item.next_run_at = item.schedule.next_run_at
    db.add(ResearchAutomationAudit(actor=actor, action="source_updated", source_id=item.id, details=payload.model_dump(exclude_none=True)))
    db.commit()
    return _source_response(_get_source(db, source_id))


@router.delete("/sources/{source_id}", response_model=AutomatedSourceResponse, dependencies=[Depends(require_admin)])
def disable_source(source_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> AutomatedSourceResponse:
    item = _get_source(db, source_id)
    item.enabled = False
    item.collection_status = "disabled"
    if item.schedule:
        item.schedule.enabled = False
        item.schedule.paused = True
        item.schedule.next_run_at = None
    item.next_run_at = None
    db.add(ResearchAutomationAudit(actor=actor, action="source_disabled", source_id=item.id, details={}))
    db.commit()
    return _source_response(_get_source(db, source_id))


@router.post("/sources/{source_id}/schedule", response_model=AutomatedSourceResponse, dependencies=[Depends(require_admin)])
def configure_schedule(source_id: int, payload: ScheduleRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> AutomatedSourceResponse:
    item = _get_source(db, source_id)
    if payload.frequency == "manual":
        if item.schedule:
            item.schedule.enabled = False
            item.schedule.next_run_at = None
        item.collection_frequency = "manual"
        item.next_run_at = None
    else:
        schedule = item.schedule or ResearchSchedule(source_id=item.id)
        schedule.frequency = payload.frequency
        schedule.interval_minutes = payload.interval_minutes
        schedule.enabled = payload.enabled and item.enabled
        schedule.paused = payload.paused
        schedule.next_run_at = _now() if schedule.enabled and not schedule.paused else None
        item.schedule = schedule
        item.collection_frequency = payload.frequency
        item.interval_minutes = payload.interval_minutes
        item.next_run_at = schedule.next_run_at
    db.add(ResearchAutomationAudit(actor=actor, action="schedule_updated", source_id=item.id, details=payload.model_dump()))
    db.commit()
    return _source_response(_get_source(db, source_id))


@router.post("/sources/{source_id}/pause", response_model=AutomatedSourceResponse, dependencies=[Depends(require_admin)])
def pause_schedule(source_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> AutomatedSourceResponse:
    item = _get_source(db, source_id)
    if item.schedule is None:
        raise HTTPException(status_code=409, detail="Source has no configured schedule")
    item.schedule.paused = True
    item.schedule.next_run_at = None
    item.next_run_at = None
    db.add(ResearchAutomationAudit(actor=actor, action="schedule_paused", source_id=source_id, details={}))
    db.commit()
    return _source_response(_get_source(db, source_id))


@router.post("/sources/{source_id}/resume", response_model=AutomatedSourceResponse, dependencies=[Depends(require_admin)])
def resume_schedule(source_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> AutomatedSourceResponse:
    item = _get_source(db, source_id)
    if item.schedule is None:
        raise HTTPException(status_code=409, detail="Source has no configured schedule")
    item.schedule.paused = False
    item.schedule.enabled = item.enabled
    item.schedule.next_run_at = _now() if item.schedule.enabled else None
    item.next_run_at = item.schedule.next_run_at
    db.add(ResearchAutomationAudit(actor=actor, action="schedule_resumed", source_id=source_id, details={}))
    db.commit()
    return _source_response(_get_source(db, source_id))


@router.post("/runs", response_model=ResearchRunResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def start_run(payload: RunStartRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> ResearchRunResponse:
    try:
        run = create_run(db, source_ids=payload.source_ids, filters=_filters(payload), trigger="manual", actor=actor)
        return _run_response(execute_run(db, run, settings))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs", response_model=list[ResearchRunResponse], dependencies=[Depends(require_admin)])
def list_runs(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[ResearchRunResponse]:
    return [_run_response(run) for run in db.scalars(select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit)).all()]


@router.get("/runs/{run_id}", response_model=ResearchRunResponse, dependencies=[Depends(require_admin)])
def get_run(run_id: int, db: Session = Depends(get_db)) -> ResearchRunResponse:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run was not found")
    return _run_response(run)


@router.get("/runs/{run_id}/attempts", response_model=list[CollectionAttemptResponse], dependencies=[Depends(require_admin)])
def run_attempts(run_id: int, db: Session = Depends(get_db)) -> list[CollectionAttemptResponse]:
    if db.get(ResearchRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Research run was not found")
    return [CollectionAttemptResponse.model_validate(item) for item in db.scalars(select(ResearchCollectionAttempt).where(ResearchCollectionAttempt.run_id == run_id).order_by(ResearchCollectionAttempt.id)).all()]


@router.get("/status", response_model=list[AutomatedSourceResponse], dependencies=[Depends(require_admin)])
def collection_status(db: Session = Depends(get_db)) -> list[AutomatedSourceResponse]:
    return list_sources(db)


@router.get("/changes", response_model=list[AutomatedChangeResponse], dependencies=[Depends(require_admin)])
def changes(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[AutomatedChangeResponse]:
    events = db.scalars(select(ResearchChangeEvent).order_by(ResearchChangeEvent.detected_at.desc()).limit(limit)).all()
    return [AutomatedChangeResponse(**_event_response(db, event)) for event in events]


@router.get("/findings", dependencies=[Depends(require_admin)])
def pending_findings(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, Any]:
    changes = db.scalars(select(ReviewChange).join(ResearchSubmission).join(ResearchSource, ResearchSubmission.source_id == ResearchSource.id).where(ReviewChange.status == "pending", ResearchSource.source_type.like("automated_%")).order_by(ReviewChange.created_at.desc()).limit(limit)).all()
    return {"items": [{"id": item.id, "submission_id": item.submission_id, "finding_id": item.finding_id, "change_type": item.change_type, "status": item.status, "version": item.version, "review_url": f"/research-review?submission={item.submission_id}", "proposed": item.proposed_snapshot} for item in changes], "total": len(changes)}


@router.get("/coverage", response_model=CoverageResponse, dependencies=[Depends(require_admin)])
def coverage(db: Session = Depends(get_db)) -> CoverageResponse:
    industries = list(db.scalars(select(Industry).where(Industry.is_active.is_(True)).order_by(Industry.display_order, Industry.name)).all())
    domains = list(db.scalars(select(SecurityDomain).order_by(SecurityDomain.display_order, SecurityDomain.name)).all())
    levels = list(db.scalars(select(CareerLevel).order_by(CareerLevel.display_order)).all())
    cells = []
    for industry in industries:
        for domain in domains:
            for level in levels:
                finding_query = select(func.count(func.distinct(ResearchFinding.id)), func.count(func.distinct(ResearchSource.id))).join(ResearchFindingDomain, ResearchFindingDomain.finding_id == ResearchFinding.id).join(ResearchSubmission).join(ResearchSource, ResearchSubmission.source_id == ResearchSource.id).where(ResearchFindingDomain.domain_id == domain.id, ResearchFinding.career_level_id == level.id, ResearchFinding.primary_industry_id == industry.id, ResearchSource.source_type.like("automated_%"))
                evidence_count, source_count = db.execute(finding_query).one()
                label = "adequate" if evidence_count >= 3 and source_count >= 2 else "limited" if evidence_count >= 1 else "none"
                cell = CoverageCell(industry={"id": industry.id, "name": industry.name, "slug": industry.slug}, domain={"id": domain.id, "name": domain.name, "slug": domain.slug}, career_level={"id": level.id, "name": level.name, "slug": level.slug}, evidence_count=evidence_count, source_count=source_count, label=label)
                cells.append(cell)
    under = [cell for cell in cells if cell.label != "adequate"]
    return CoverageResponse(thresholds={"limited_evidence": 1, "adequate_evidence": 3, "adequate_sources": 2}, cells=cells, under_researched=under)
