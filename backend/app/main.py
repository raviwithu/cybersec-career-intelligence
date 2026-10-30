from contextlib import asynccontextmanager
import logging
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, get_db, init_db
from .admin_auth import require_admin
from .health import service_status
from .intelligence_api import router as intelligence_router
from .job_search_api import router as job_search_router
from .yahoo_mail_api import router as yahoo_mail_router
from .knowledge import router as knowledge_router
from .knowledge_contract_api import router as knowledge_contract_router
from .knowledge_map_api import router as knowledge_map_router
from .knowledge_topic_api import admin_router as knowledge_topic_admin_router, public_router as knowledge_topic_public_router
from .phase5_api import router as phase5_router
from .phase6_api import router as phase6_router
from .taxonomy_api import router as taxonomy_router
from .research_review_api import router as research_review_router
from .logging_config import configure_logging
from .models import CareerProfile
from .read_api import router as read_router
from .schemas import ProfileCreate, ProfileResponse, ReadinessResponse
from .seed import seed_reference_data

settings = get_settings()
configure_logging()
logger = logging.getLogger("cybersec.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Read-only consolidated cybersecurity competency and career-expectations APIs.",
    lifespan=lifespan,
)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(knowledge_contract_router, prefix=settings.api_prefix)
app.include_router(knowledge_map_router, prefix=settings.api_prefix)
app.include_router(knowledge_topic_public_router, prefix=settings.api_prefix)
app.include_router(knowledge_topic_admin_router, prefix=settings.api_prefix)
app.include_router(read_router, prefix=settings.api_prefix)
app.include_router(phase5_router, prefix=settings.api_prefix)
app.include_router(phase6_router, prefix=settings.api_prefix)
app.include_router(taxonomy_router, prefix=settings.api_prefix)
app.include_router(job_search_router, prefix=settings.api_prefix)
app.include_router(yahoo_mail_router, prefix=settings.api_prefix)
app.include_router(research_review_router, prefix=settings.api_prefix)
app.include_router(intelligence_router, prefix=settings.api_prefix)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
        response = JSONResponse(status_code=413, content={"detail": "Request body is too large", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        return response

    body = bytearray()
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            break
        body.extend(message.get("body", b""))
        if len(body) > settings.max_request_bytes:
            response = JSONResponse(status_code=413, content={"detail": "Request body is too large", "request_id": request_id})
            response.headers["X-Request-ID"] = request_id
            return response
        if not message.get("more_body", False):
            break

    async def replay_body():
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    request._receive = replay_body
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "unhandled_request_error",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        raise
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "api_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    logger.exception(
        "internal_server_error",
        exc_info=exc,
        extra={"request_id": request_id, "method": request.method, "path": request.url.path},
    )
    response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "backend"}


@app.get("/health/ready", response_model=ReadinessResponse)
def readiness(db: Session = Depends(get_db)) -> ReadinessResponse:
    result = service_status(db, settings, include_ollama=False)
    if result["status"] != "healthy":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result)
    return result


@app.get(f"{settings.api_prefix}/health", response_model=ReadinessResponse)
def health(db: Session = Depends(get_db)) -> ReadinessResponse:
    return service_status(db, settings)


@app.get(f"{settings.api_prefix}/profiles", response_model=list[ProfileResponse], dependencies=[Depends(require_admin)])
def list_profiles(db: Session = Depends(get_db)) -> list[CareerProfile]:
    return list(db.scalars(select(CareerProfile).order_by(CareerProfile.created_at.desc())).all())


@app.post(f"{settings.api_prefix}/profiles", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_profile(payload: ProfileCreate, db: Session = Depends(get_db)) -> CareerProfile:
    profile = CareerProfile(**payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile
