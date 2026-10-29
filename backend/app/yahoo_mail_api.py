from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .config import get_settings
from .database import get_db
from .models import YahooAlertSource, YahooJobCandidate, YahooMailConnection, YahooMailSyncRun
from .yahoo_mail import ALLOWED_SENDER, YahooMailError
from .yahoo_mail_schemas import (
    AlertSourceResponse,
    AlertSourceUpdate,
    BulkReview,
    BulkReviewResult,
    CandidatePage,
    CandidateResponse,
    CandidateReview,
    CandidateUpdate,
    MailConnectionCreate,
    MailConnectionResponse,
    MailConnectionTest,
    MailConnectionTestResponse,
    MailConnectionUpdate,
    MailSyncRequest,
    SyncRunResponse,
)
from .yahoo_mail_service import (
    MailConfigurationError,
    bulk_review,
    candidate_response,
    connection_response,
    create_or_update_connection,
    retry_description,
    review_candidate,
    sync_connection,
    sync_run_response,
    test_connection,
    update_connection,
)

router = APIRouter(prefix="/admin/mail", tags=["yahoo-mail-administration"])
settings = get_settings()


def _connection(db: Session, connection_id: int) -> YahooMailConnection:
    item = db.get(YahooMailConnection, connection_id)
    if item is None or not item.enabled:
        raise HTTPException(status_code=404, detail="Yahoo Mail connection was not found")
    return item


def _candidate_query():
    return select(YahooJobCandidate).options(
        selectinload(YahooJobCandidate.alert_email), selectinload(YahooJobCandidate.provenance), selectinload(YahooJobCandidate.reviews),
    )


def _candidate(db: Session, candidate_id: int) -> YahooJobCandidate:
    item = db.scalar(_candidate_query().where(YahooJobCandidate.id == candidate_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Job candidate was not found")
    return item


@router.get("/connections", response_model=list[MailConnectionResponse], dependencies=[Depends(require_admin)])
def list_connections(db: Session = Depends(get_db)):
    return [connection_response(item) for item in db.scalars(select(YahooMailConnection).where(YahooMailConnection.enabled.is_(True)).order_by(YahooMailConnection.id)).all()]


@router.post("/connections", response_model=MailConnectionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def save_connection(payload: MailConnectionCreate, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return connection_response(create_or_update_connection(db, payload, settings, actor))
    except MailConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.patch("/connections/{connection_id}", response_model=MailConnectionResponse, dependencies=[Depends(require_admin)])
def patch_connection(connection_id: int, payload: MailConnectionUpdate, db: Session = Depends(get_db)):
    item = _connection(db, connection_id)
    if payload.app_password is not None:
        from .yahoo_mail_service import encrypt_app_password
        try:
            item.encrypted_app_password = encrypt_app_password(settings, payload.app_password)
        except MailConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        payload = payload.model_copy(update={"app_password": None})
    return connection_response(update_connection(db, item, payload))


@router.post("/connections/test", response_model=MailConnectionTestResponse, dependencies=[Depends(require_admin)])
def test_connection_endpoint(payload: MailConnectionTest) -> MailConnectionTestResponse:
    try:
        test_connection(payload, settings)
        return MailConnectionTestResponse(connected=True, detail="Yahoo IMAP TLS connection and read-only mailbox access confirmed")
    except (YahooMailError, MailConfigurationError) as exc:
        return MailConnectionTestResponse(connected=False, detail=str(exc))


@router.post("/connections/{connection_id}/disconnect", response_model=MailConnectionResponse, dependencies=[Depends(require_admin)])
def disconnect_connection(connection_id: int, db: Session = Depends(get_db)):
    item = _connection(db, connection_id)
    item.enabled = False
    item.automatic_sync_enabled = False
    item.next_sync_at = None
    item.status = "disconnected"
    db.commit()
    db.refresh(item)
    return connection_response(item)


@router.post("/connections/{connection_id}/sync", response_model=SyncRunResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def sync_connection_endpoint(connection_id: int, payload: MailSyncRequest | None = None, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
    item = _connection(db, connection_id)
    try:
        return sync_run_response(sync_connection(db, item, settings, payload or MailSyncRequest(mode="manual"), actor))
    except YahooMailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sync-runs", response_model=list[SyncRunResponse], dependencies=[Depends(require_admin)])
def list_sync_runs(connection_id: int | None = None, db: Session = Depends(get_db)):
    query = select(YahooMailSyncRun).order_by(YahooMailSyncRun.started_at.desc()).limit(100)
    if connection_id:
        query = query.where(YahooMailSyncRun.connection_id == connection_id)
    return [sync_run_response(item) for item in db.scalars(query).all()]


@router.get("/alert-sources", response_model=list[AlertSourceResponse], dependencies=[Depends(require_admin)])
def list_alert_sources(connection_id: int | None = None, db: Session = Depends(get_db)):
    query = select(YahooAlertSource).where(YahooAlertSource.sender_address == ALLOWED_SENDER).order_by(YahooAlertSource.id)
    if connection_id:
        query = query.where(YahooAlertSource.connection_id == connection_id)
    return [item for item in db.scalars(query).all()]


@router.patch("/alert-sources/{source_id}", response_model=AlertSourceResponse, dependencies=[Depends(require_admin)])
def update_alert_source(source_id: int, payload: AlertSourceUpdate, db: Session = Depends(get_db)):
    item = db.get(YahooAlertSource, source_id)
    if item is None or item.sender_address != ALLOWED_SENDER:
        raise HTTPException(status_code=404, detail="LinkedIn alert source was not found")
    item.subject_pattern = payload.subject_pattern.strip()
    item.enabled = payload.enabled
    db.commit()
    db.refresh(item)
    return item


@router.get("/job-candidates", response_model=CandidatePage, dependencies=[Depends(require_admin)])
def list_candidates(
    status_filter: str | None = Query(default=None, alias="status"),
    source: str | None = None,
    search: str | None = None,
    description: str | None = Query(default=None, pattern="^(complete|partial)$"),
    db: Session = Depends(get_db),
):
    query = _candidate_query().order_by(YahooJobCandidate.created_at.desc())
    if status_filter:
        query = query.where(YahooJobCandidate.review_status == status_filter)
    if source:
        query = query.where(YahooJobCandidate.source_provider == source)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(YahooJobCandidate.title.ilike(term), YahooJobCandidate.employer.ilike(term), YahooJobCandidate.location.ilike(term)))
    if description == "complete":
        query = query.where(YahooJobCandidate.description_complete.is_(True))
    elif description == "partial":
        query = query.where(YahooJobCandidate.description_complete.is_(False))
    items = list(db.scalars(query).unique().all())
    counts = {value: int(db.scalar(select(func.count()).select_from(YahooJobCandidate).where(YahooJobCandidate.review_status == value)) or 0) for value in ("pending", "approved", "rejected", "deferred")}
    counts["duplicates"] = int(db.scalar(select(func.count()).select_from(YahooJobCandidate).where(YahooJobCandidate.duplicate_status == "duplicate")) or 0)
    counts["extraction_failed"] = int(db.scalar(select(func.count()).select_from(YahooJobCandidate).where(YahooJobCandidate.description_status == "failed")) or 0)
    for value, count in db.execute(select(YahooJobCandidate.ingestion_status, func.count()).group_by(YahooJobCandidate.ingestion_status)).all():
        counts[f"ingestion_{value}"] = int(count)
    return CandidatePage(items=[candidate_response(item) for item in items], total=len(items), counts=counts)


@router.get("/job-candidates/{candidate_id}", response_model=CandidateResponse, dependencies=[Depends(require_admin)])
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    return candidate_response(_candidate(db, candidate_id))


@router.patch("/job-candidates/{candidate_id}", response_model=CandidateResponse, dependencies=[Depends(require_admin)])
def patch_candidate(candidate_id: int, payload: CandidateUpdate, db: Session = Depends(get_db)):
    item = _candidate(db, candidate_id)
    values = payload.model_dump(exclude_none=True)
    if "description_text" in values and values["description_text"] == item.description_text:
        values.pop("description_text")
    if "description_text" in values:
        item.description_text = values.pop("description_text")
        item.description_complete = len(item.description_text.strip()) >= 240
        item.description_status = "complete" if item.description_complete else "partial"
        item.extraction_method = "administrator_corrected"
    values.pop("note", None)
    for key, value in values.items():
        setattr(item, key, value)
    db.commit()
    return candidate_response(_candidate(db, candidate_id))


@router.post("/job-candidates/{candidate_id}/retry-description", response_model=CandidateResponse, dependencies=[Depends(require_admin)])
def retry_candidate_description(candidate_id: int, db: Session = Depends(get_db)):
    item = _candidate(db, candidate_id)
    try:
        return candidate_response(retry_description(db, item, settings))
    except Exception as exc:
        item.description_status = "failed"
        item.review_note = str(exc)[:2000]
        db.commit()
        raise HTTPException(status_code=422, detail="A complete description could not be retrieved; manual entry remains available") from exc


@router.post("/job-candidates/bulk-review", response_model=BulkReviewResult, dependencies=[Depends(require_admin)])
def bulk_review_endpoint(payload: BulkReview, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return bulk_review(db, payload, actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/job-candidates/{candidate_id}/approve", response_model=CandidateResponse, dependencies=[Depends(require_admin)])
def approve_candidate(candidate_id: int, payload: CandidateReview | None = None, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return candidate_response(review_candidate(db, _candidate(db, candidate_id), "approve", payload or CandidateReview(), actor))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/job-candidates/{candidate_id}/reject", response_model=CandidateResponse, dependencies=[Depends(require_admin)])
def reject_candidate(candidate_id: int, payload: CandidateReview | None = None, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
    return candidate_response(review_candidate(db, _candidate(db, candidate_id), "rejected", payload or CandidateReview(), actor))


@router.post("/job-candidates/{candidate_id}/defer", response_model=CandidateResponse, dependencies=[Depends(require_admin)])
def defer_candidate(candidate_id: int, payload: CandidateReview | None = None, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
    return candidate_response(review_candidate(db, _candidate(db, candidate_id), "deferred", payload or CandidateReview(), actor))
