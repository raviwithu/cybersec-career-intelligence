from datetime import datetime, timezone
from pathlib import PurePath
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .ai_providers import AIProviderRegistry
from .config import get_settings
from .database import get_db
from .models import (
    DomainLevelExpectation,
    ModelSelection,
    DraftEvidence,
    DraftExpectation,
    ExpectationSource,
    ResearchSource,
    ResearchSubmission,
)
from .ollama_client import OllamaClient, OllamaError
from .model_selection import ModelSelectionError, ModelSelectionService
from .provider_common import ProviderError
from .phase5_schemas import (
    DraftExpectationResponse,
    DraftPage,
    DraftUpdate,
    ModelSelectRequest,
    ModelTestResponse,
    OllamaStatusResponse,
    AIModelResponse,
    ProviderModelsResponse,
    UnifiedModelsResponse,
    SubmissionCreate,
    ResearchSubmissionResponse,
    UrlImportRequest,
    UrlImportResponse,
    ReviewAction,
    SubmissionPage,
    WorkflowResponse,
)
from .phase5_service import content_digest, parse_research_file, process_submission, published_expectation
from .submission_deletion import SubmissionDeletionBlocked, delete_submission
from .url_importer import UrlImportError, UrlImporter

router = APIRouter(prefix="/research", tags=["research-administration"])
settings = get_settings()
ollama = OllamaClient(settings)
providers = AIProviderRegistry(settings, ollama=ollama)
model_selection = ModelSelectionService(providers, settings)
url_importer = UrlImporter(settings)


def ollama_status_response(db: Session, available_models: list[str] | None = None, detail: str | None = None) -> OllamaStatusResponse:
    selection = db.get(ModelSelection, 1)
    active_model = model_selection.active_model(db)
    if available_models is None:
        try:
            available_models = model_selection.list_models()
        except ModelSelectionError as exc:
            available_models = []
            detail = detail or str(exc)
    configured = active_model in available_models
    evaluations = model_selection.recent_evaluations(db, provider="ollama")
    return OllamaStatusResponse(
        status="configured" if configured else ("unavailable" if detail else "unconfigured"),
        model=active_model, active_model=active_model,
        mode=selection.mode if selection else "fallback",
        evaluation_version=selection.evaluation_version if selection else None,
        available_models=available_models,
        evaluations=evaluations,
        detail=detail or ("configured model available" if configured else "configured model is not installed on Ollama"),
    )


def unified_models_response(db: Session, catalogs=None) -> UnifiedModelsResponse:
    catalogs = catalogs if catalogs is not None else providers.discover()
    active_provider, active_model_id, active_model_name = model_selection.active_selection(db)
    active_model_name = next((model.name for catalog in catalogs if catalog.provider == active_provider for model in catalog.models if model.model_id == active_model_id), active_model_name)
    selection = db.get(ModelSelection, 1)
    return UnifiedModelsResponse(
        providers=[ProviderModelsResponse(
            provider=catalog.provider,
            status=catalog.status,
            models=[AIModelResponse(
                provider=model.provider, id=model.model_id, name=model.name, size=model.size,
                details=model.details, provider_info=model.provider_info, metadata=model.metadata,
                possible_duplicate=model.possible_duplicate, duplicate_with=list(model.duplicate_with),
            ) for model in catalog.models],
            error=catalog.error,
        ) for catalog in catalogs],
        active_provider=active_provider,
        active_model_id=active_model_id,
        active_model_name=active_model_name,
        mode=selection.mode if selection else "fallback",
        evaluation_version=selection.evaluation_version if selection else None,
        evaluations=model_selection.recent_evaluations(db),
    )


def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="research_date must be an ISO date or datetime") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def create_submission(db: Session, *, content: str, source_title: str | None, source_url: str | None, research_date: str | None, source_type: str, filename: str | None) -> ResearchSubmission:
    if source_url:
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise HTTPException(status_code=422, detail="source_url must be an HTTP or HTTPS URL")
    if len(content.encode("utf-8")) > settings.max_research_bytes:
        raise HTTPException(status_code=413, detail="research input exceeds the configured size limit")
    digest = content_digest(content)
    # Failed analyses stay in history but must not block a retry of the same content.
    if db.scalar(select(ResearchSubmission).where(ResearchSubmission.content_sha256 == digest, ResearchSubmission.status != "failed")):
        raise HTTPException(status_code=409, detail="This research input has already been submitted")
    source = ResearchSource(
        source_type=source_type,
        source_url=(source_url or "about:blank")[:1000],
        source_title=(source_title or filename or "Untitled cybersecurity research")[:300],
        collected_at=parse_date(research_date),
        notes="Temporary research input; full submitted content is not retained.",
    )
    db.add(source)
    db.flush()
    active_provider, active_model_id, active_model_name = model_selection.active_selection(db)
    submission = ResearchSubmission(
        source_id=source.id, source_type=source_type, original_filename=filename,
        content_sha256=digest, content_size=len(content.encode("utf-8")), status="received",
        model_provider=active_provider, model_id=active_model_id, model_name=active_model_name,
        evaluation_version=model_selection.active_evaluation_version(db),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    try:
        process_submission(db, submission, content, providers, settings)
    except Exception:
        db.refresh(submission)
    return submission


def submission_review_status(item: ResearchSubmission) -> str:
    statuses = {change.status for change in item.review_changes}
    if statuses and statuses <= {"published", "rejected"} and "published" in statuses:
        return "published"
    if statuses and statuses <= {"rejected"}:
        return "rejected"
    return "in_review" if statuses else "pending"


def submission_response(item: ResearchSubmission) -> ResearchSubmissionResponse:
    return ResearchSubmissionResponse(
        id=item.id, source_id=item.source_id, source_title=item.source.source_title, source_url=item.source.source_url,
        source_type=item.source_type, original_filename=item.original_filename, content_size=item.content_size,
        status=item.status, model_provider=item.model_provider, model_id=item.model_id, model_name=item.model_name,
        evaluation_version=item.evaluation_version,
        error_message=item.error_message, submitted_at=item.submitted_at, completed_at=item.completed_at,
        review_status=submission_review_status(item), finding_count=len(item.findings), draft_count=len(item.drafts),
    )


def draft_query():
    return select(DraftExpectation).options(
        selectinload(DraftExpectation.domain), selectinload(DraftExpectation.career_level),
        selectinload(DraftExpectation.competency), selectinload(DraftExpectation.evidence).selectinload(DraftEvidence.source),
    )


def draft_response(item: DraftExpectation) -> DraftExpectationResponse:
    return DraftExpectationResponse(
        id=item.id, submission_id=item.submission_id, domain_id=item.domain_id, domain_name=item.domain.name,
        career_level_id=item.career_level_id, career_level_name=item.career_level.name, competency_id=item.competency_id,
        competency_name=item.competency.name, technical_knowledge=item.technical_knowledge,
        practical_capability=item.practical_capability, qualifications=item.qualifications,
        tools_technologies=item.tools_technologies, expectation_description=item.expectation_description,
        proficiency_level=item.proficiency_level, importance=item.importance, responsibility_type=item.responsibility_type,
        experience_years_min=item.experience_years_min, experience_years_max=item.experience_years_max,
        status=item.status, reviewer_note=item.reviewer_note, reviewed_by=item.reviewed_by,
        reviewed_at=item.reviewed_at, published_expectation_id=item.published_expectation_id,
        evidence=[{"source_title": evidence.source.source_title, "source_url": evidence.source.source_url,
                   "collected_at": evidence.source.collected_at, "supporting_excerpt": evidence.supporting_excerpt} for evidence in item.evidence],
    )


@router.get("/models", response_model=UnifiedModelsResponse, dependencies=[Depends(require_admin)])
def unified_models(db: Session = Depends(get_db)) -> UnifiedModelsResponse:
    return unified_models_response(db)


@router.post("/models/refresh", response_model=UnifiedModelsResponse, dependencies=[Depends(require_admin)])
def refresh_unified_models(db: Session = Depends(get_db)) -> UnifiedModelsResponse:
    return unified_models_response(db, providers.discover())


@router.post("/models/select", response_model=UnifiedModelsResponse, dependencies=[Depends(require_admin)])
def select_unified_model(payload: ModelSelectRequest, db: Session = Depends(get_db)) -> UnifiedModelsResponse:
    try:
        model_selection.set_manual(db, provider=payload.provider, model_id=payload.model_id, model_name=payload.model_name)
        return unified_models_response(db)
    except ModelSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/models/test", response_model=ModelTestResponse, dependencies=[Depends(require_admin)])
def test_unified_model(payload: ModelSelectRequest) -> ModelTestResponse:
    model_id = payload.model_id or payload.model_name
    try:
        latency = providers.test_model(payload.provider, model_id)
        return ModelTestResponse(provider=payload.provider, model_id=model_id, reachable=True, latency_ms=latency, detail="Model connectivity confirmed")
    except (ProviderError, OllamaError) as exc:
        return ModelTestResponse(provider=payload.provider, model_id=model_id, reachable=False, detail=str(exc))


@router.post("/models/evaluate", response_model=UnifiedModelsResponse, dependencies=[Depends(require_admin)])
def evaluate_unified_models(db: Session = Depends(get_db)) -> UnifiedModelsResponse:
    try:
        model_selection.evaluate_and_select(db)
        return unified_models_response(db)
    except ModelSelectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/ollama", response_model=OllamaStatusResponse, dependencies=[Depends(require_admin)])
def ollama_status(db: Session = Depends(get_db)) -> OllamaStatusResponse:
    return ollama_status_response(db)


@router.post("/ollama/models/refresh", response_model=OllamaStatusResponse, dependencies=[Depends(require_admin)])
def refresh_ollama_models(db: Session = Depends(get_db)) -> OllamaStatusResponse:
    try:
        return ollama_status_response(db, model_selection.list_models())
    except ModelSelectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ollama/evaluate", response_model=OllamaStatusResponse, dependencies=[Depends(require_admin)])
def evaluate_ollama_models(db: Session = Depends(get_db)) -> OllamaStatusResponse:
    try:
        model_selection.evaluate_and_select(db, provider="ollama")
        return ollama_status_response(db)
    except ModelSelectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ollama/select", response_model=OllamaStatusResponse, dependencies=[Depends(require_admin)])
def select_ollama_model(payload: ModelSelectRequest, db: Session = Depends(get_db)) -> OllamaStatusResponse:
    try:
        model_selection.set_manual(db, provider="ollama", model_id=payload.model_id, model_name=payload.model_name)
        return ollama_status_response(db)
    except ModelSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/submissions", response_model=ResearchSubmissionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def submit_text(payload: SubmissionCreate, db: Session = Depends(get_db)) -> ResearchSubmissionResponse:
    item = create_submission(
        db, content=payload.content.strip(), source_title=payload.source_title, source_url=payload.source_url,
        research_date=payload.research_date.isoformat() if payload.research_date else None, source_type=payload.source_type, filename=None,
    )
    return submission_response(item)


@router.post("/import-url", response_model=UrlImportResponse, dependencies=[Depends(require_admin)])
def import_url(payload: UrlImportRequest) -> UrlImportResponse:
    try:
        imported = url_importer.import_job(payload.url)
    except UrlImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from exc
    return UrlImportResponse(
        source_url=imported.source_url, job_title=imported.job_title, job_description=imported.job_description,
        extraction_method=imported.extraction_method, date_posted=imported.date_posted,
    )


@router.post("/submissions/file", response_model=ResearchSubmissionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def submit_file(
    file: UploadFile = File(...), source_title: str | None = Form(default=None), source_url: str | None = Form(default=None),
    research_date: str | None = Form(default=None), db: Session = Depends(get_db),
) -> ResearchSubmissionResponse:
    filename = PurePath(file.filename or "research.txt").name
    try:
        raw = file.file.read(settings.max_research_bytes + 1)
        safe_filename, content = parse_research_file(filename, raw, settings.max_research_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = create_submission(db, content=content, source_title=source_title, source_url=source_url, research_date=research_date, source_type=PurePath(safe_filename).suffix.casefold()[1:], filename=safe_filename)
    return submission_response(item)


@router.get("/submissions", response_model=SubmissionPage, dependencies=[Depends(require_admin)])
def list_submissions(db: Session = Depends(get_db)) -> SubmissionPage:
    query = select(ResearchSubmission).options(
        selectinload(ResearchSubmission.source), selectinload(ResearchSubmission.findings),
        selectinload(ResearchSubmission.drafts), selectinload(ResearchSubmission.review_changes),
    ).order_by(ResearchSubmission.submitted_at.desc())
    items = list(db.scalars(query).unique().all())
    return SubmissionPage(items=[submission_response(item) for item in items], total=len(items))


@router.get("/submissions/{submission_id}", response_model=ResearchSubmissionResponse, dependencies=[Depends(require_admin)])
def get_submission(submission_id: int, db: Session = Depends(get_db)) -> ResearchSubmissionResponse:
    item = db.scalar(select(ResearchSubmission).where(ResearchSubmission.id == submission_id).options(
        selectinload(ResearchSubmission.source), selectinload(ResearchSubmission.findings),
        selectinload(ResearchSubmission.drafts), selectinload(ResearchSubmission.review_changes),
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Research submission was not found")
    return submission_response(item)


@router.get("/drafts", response_model=DraftPage, dependencies=[Depends(require_admin)])
def list_drafts(status_filter: str | None = None, db: Session = Depends(get_db)) -> DraftPage:
    query = draft_query().order_by(DraftExpectation.created_at.desc())
    if status_filter:
        query = query.where(DraftExpectation.status == status_filter)
    items = list(db.scalars(query).unique().all())
    return DraftPage(items=[draft_response(item) for item in items], total=len(items))


@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_submission_endpoint(submission_id: int = Path(gt=0), actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    try:
        delete_submission(db, submission_id, actor)
    except SubmissionDeletionBlocked as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Research submission deletion failed and was rolled back") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/drafts/{draft_id}", response_model=DraftExpectationResponse, dependencies=[Depends(require_admin)])
def get_draft(draft_id: int, db: Session = Depends(get_db)) -> DraftExpectationResponse:
    item = db.scalar(draft_query().where(DraftExpectation.id == draft_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Draft expectation was not found")
    return draft_response(item)


@router.patch("/drafts/{draft_id}", response_model=DraftExpectationResponse, dependencies=[Depends(require_admin)])
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)) -> DraftExpectationResponse:
    item = db.scalar(draft_query().where(DraftExpectation.id == draft_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Draft expectation was not found")
    if item.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Only draft or rejected expectations can be edited")
    if payload.technical_knowledge is not None:
        item.technical_knowledge = payload.technical_knowledge
    if payload.practical_capability is not None:
        item.practical_capability = payload.practical_capability
    if payload.qualifications is not None:
        item.qualifications = payload.qualifications
    if payload.tools_technologies is not None:
        item.tools_technologies = payload.tools_technologies
    item.expectation_description = payload.expectation_description
    item.proficiency_level = payload.proficiency_level
    item.importance = payload.importance
    item.responsibility_type = payload.responsibility_type
    item.experience_years_min = payload.experience_years_min
    item.experience_years_max = payload.experience_years_max
    item.reviewer_note = payload.reviewer_note
    item.status = "draft"
    db.commit()
    return draft_response(db.scalar(draft_query().where(DraftExpectation.id == item.id)))


@router.post("/drafts/{draft_id}/approve", response_model=WorkflowResponse, dependencies=[Depends(require_admin)])
def approve_draft(draft_id: int, payload: ReviewAction, db: Session = Depends(get_db)) -> WorkflowResponse:
    item = _review(db, draft_id, "approved", payload.reviewer_note)
    return WorkflowResponse(status=item.status, draft=draft_response(item))


@router.post("/drafts/{draft_id}/reject", response_model=WorkflowResponse, dependencies=[Depends(require_admin)])
def reject_draft(draft_id: int, payload: ReviewAction, db: Session = Depends(get_db)) -> WorkflowResponse:
    item = _review(db, draft_id, "rejected", payload.reviewer_note)
    return WorkflowResponse(status=item.status, draft=draft_response(item))


def _review(db: Session, draft_id: int, next_status: str, note: str | None) -> DraftExpectation:
    item = db.scalar(draft_query().where(DraftExpectation.id == draft_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Draft expectation was not found")
    if item.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Only draft or rejected expectations can be reviewed")
    item.status = next_status
    item.reviewer_note = note
    item.reviewed_by = "administrator"
    item.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return db.scalar(draft_query().where(DraftExpectation.id == item.id))


@router.post("/drafts/{draft_id}/publish", response_model=WorkflowResponse, dependencies=[Depends(require_admin)])
def publish_draft(draft_id: int, db: Session = Depends(get_db)) -> WorkflowResponse:
    item = db.scalar(draft_query().where(DraftExpectation.id == draft_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Draft expectation was not found")
    if item.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved expectations can be published")
    published = published_expectation(db, item)
    if published is None:
        published = DomainLevelExpectation(
            domain_id=item.domain_id, career_level_id=item.career_level_id, competency_id=item.competency_id,
            technical_knowledge=item.technical_knowledge, practical_capability=item.practical_capability,
            qualifications=item.qualifications, tools_technologies=item.tools_technologies,
            expectation_description=item.expectation_description, proficiency_level=item.proficiency_level,
            importance=item.importance, responsibility_type=item.responsibility_type,
            experience_years_min=item.experience_years_min, experience_years_max=item.experience_years_max,
        )
        db.add(published)
        db.flush()
        for evidence in item.evidence:
            db.add(ExpectationSource(expectation_id=published.id, source_id=evidence.source_id, supporting_excerpt=evidence.supporting_excerpt))
    item.published_expectation_id = published.id
    item.status = "published"
    db.commit()
    return WorkflowResponse(status=item.status, draft=draft_response(db.scalar(draft_query().where(DraftExpectation.id == item.id))))
