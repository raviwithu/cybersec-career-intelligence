from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .ai_providers import AIProviderRegistry
from .config import Settings
from .database import SessionLocal
from .job_search_providers import CollectionError, JobSearchCriteria, JSearchProvider
from .models import (
    AutomatedResearchSource,
    JobSearchResult,
    ResearchAutomationAnalysis,
    ResearchContentVersion,
    YahooAlertEmail,
    YahooAlertSource,
    YahooJobCandidate,
    YahooJobProvenance,
    YahooJobReview,
    YahooMailConnection,
    YahooMailSyncRun,
)
from .phase5_api import providers
from .phase6_collectors import CollectedItem, normalize_content
from .phase6_pipeline import SourceLock, _analyze_version, _create_version, now
from .url_importer import UrlImportError, UrlImporter
from .yahoo_mail import ALLOWED_SENDER, YahooImapClient, YahooMailError, canonical_job_url, parse_alert
from .yahoo_mail_schemas import (
    AlertSourceUpdate,
    BulkReview,
    CandidateReview,
    CandidateUpdate,
    MailConnectionCreate,
    MailConnectionTest,
    MailConnectionUpdate,
    MailSyncRequest,
)


class MailConfigurationError(RuntimeError):
    pass


def _fernet(settings: Settings) -> Fernet:
    if not settings.mail_encryption_key:
        raise MailConfigurationError("MAIL_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(settings.mail_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise MailConfigurationError("MAIL_ENCRYPTION_KEY is invalid") from exc


def encrypt_app_password(settings: Settings, value: str) -> str:
    return _fernet(settings).encrypt(value.encode()).decode()


def decrypt_app_password(settings: Settings, value: str) -> str:
    try:
        return _fernet(settings).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise MailConfigurationError("Stored Yahoo credential could not be decrypted") from exc


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _ensure_alert_source(db: Session, connection: YahooMailConnection) -> YahooAlertSource:
    source = db.scalar(select(YahooAlertSource).where(YahooAlertSource.connection_id == connection.id, YahooAlertSource.sender_address == ALLOWED_SENDER))
    if source is None:
        source = YahooAlertSource(connection_id=connection.id, sender_address=ALLOWED_SENDER, name="LinkedIn Job Alerts", extraction_adapter="linkedin_job_alert")
        db.add(source)
        db.flush()
    return source


def connection_response(connection: YahooMailConnection) -> dict[str, Any]:
    return {
        "id": connection.id, "email_address": connection.email_address, "auth_method": connection.auth_method,
        "folder": connection.folder, "initial_sync_from": connection.initial_sync_from,
        "automatic_sync_enabled": connection.automatic_sync_enabled, "sync_interval_minutes": connection.sync_interval_minutes,
        "next_sync_at": connection.next_sync_at, "status": connection.status,
        "last_successful_sync": connection.last_successful_sync, "last_sync_error": connection.last_sync_error,
        "messages_scanned": connection.messages_scanned, "alerts_detected": connection.alerts_detected,
        "jobs_extracted": connection.jobs_extracted, "credentials_configured": bool(connection.encrypted_app_password),
    }


def create_or_update_connection(db: Session, payload: MailConnectionCreate, settings: Settings, actor: str) -> YahooMailConnection:
    connection = db.scalar(select(YahooMailConnection).where(YahooMailConnection.email_address == payload.email_address))
    values = payload.model_dump(exclude={"app_password"})
    values["initial_sync_from"] = _utc(values.get("initial_sync_from"))
    values["encrypted_app_password"] = encrypt_app_password(settings, payload.app_password)
    values["next_sync_at"] = now() if payload.automatic_sync_enabled else None
    if connection is None:
        connection = YahooMailConnection(**values)
        db.add(connection)
        db.flush()
    else:
        for key, value in values.items():
            setattr(connection, key, value)
        connection.enabled = True
        connection.status = "disconnected"
        connection.last_sync_error = None
    _ensure_alert_source(db, connection)
    db.commit()
    db.refresh(connection)
    return connection


def update_connection(db: Session, connection: YahooMailConnection, payload: MailConnectionUpdate) -> YahooMailConnection:
    values = payload.model_dump(exclude_none=True)
    if "initial_sync_from" in values:
        values["initial_sync_from"] = _utc(values["initial_sync_from"])
    if "folder" in values and values["folder"] != connection.folder:
        # UIDs are only meaningful within one mailbox, so a new folder starts a fresh checkpoint.
        connection.last_uid = 0
        connection.uidvalidity = None
    for key, value in values.items():
        setattr(connection, key, value)
    if payload.automatic_sync_enabled is True:
        connection.next_sync_at = now()
    elif payload.automatic_sync_enabled is False:
        connection.next_sync_at = None
    db.commit()
    db.refresh(connection)
    return connection


def test_connection(payload: MailConnectionTest, settings: Settings) -> None:
    secret = payload.app_password
    with YahooImapClient(settings) as client:
        client.login(payload.email_address, secret, payload.folder)


def _candidate_duplicate(db: Session, job_url: str, title: str, employer: str, location: str) -> tuple[str, str | None]:
    existing = db.scalar(select(YahooJobCandidate).where(YahooJobCandidate.job_url == job_url).order_by(YahooJobCandidate.id))
    if existing is not None:
        return "duplicate", f"Already discovered in Yahoo alert candidate #{existing.id}"
    job_result = db.scalar(select(JobSearchResult).where(JobSearchResult.canonical_url == job_url).order_by(JobSearchResult.id))
    if job_result is not None:
        return "duplicate", f"Already discovered through JSearch result #{job_result.id}"
    existing_version = db.scalar(select(ResearchContentVersion).where(ResearchContentVersion.canonical_url == job_url, ResearchContentVersion.status != "duplicate").order_by(ResearchContentVersion.id))
    if existing_version is not None:
        return "duplicate", f"Already present in research content version #{existing_version.id}"
    return "unique", None


def _insert_candidate(db: Session, email: YahooAlertEmail, item: dict[str, Any], settings: Settings) -> tuple[YahooJobCandidate, bool]:
    url = canonical_job_url(item["job_url"])
    if not url:
        raise ValueError("extracted job URL is invalid")
    existing = db.scalar(select(YahooJobCandidate).where(YahooJobCandidate.alert_email_id == email.id, YahooJobCandidate.job_url == url))
    if existing is not None:
        return existing, True
    duplicate_status, duplicate_reason = _candidate_duplicate(db, url, item.get("title", ""), item.get("employer", ""), item.get("location", ""))
    description = normalize_content(item.get("description", ""))[:settings.max_research_bytes]
    description_complete = bool(item.get("description_complete")) and len(description) >= 240
    candidate = YahooJobCandidate(
        alert_email_id=email.id, title=item.get("title", "")[:300] or "Untitled LinkedIn job",
        employer=item.get("employer", "")[:300], location=item.get("location", "")[:300], work_mode=item.get("work_mode", "")[:40],
        job_url=url, source_provider="LinkedIn Job Alerts", received_at=email.received_at,
        description_text=description, description_complete=description_complete, description_status="complete" if description_complete else "partial",
        extraction_method=item.get("extraction_method", "linkedin_job_alert"), duplicate_status=duplicate_status,
        duplicate_reason=duplicate_reason, metadata_payload={"email_content_hash": email.content_hash}, first_seen_at=now(),
    )
    db.add(candidate)
    db.flush()
    db.add(YahooJobProvenance(candidate_id=candidate.id, provenance_type="yahoo_mail", source_url=url, source_label="LinkedIn Job Alerts", details={"alert_email_id": email.id, "message_id": email.message_id}))
    if duplicate_status == "duplicate":
        job_result = db.scalar(select(JobSearchResult).where(JobSearchResult.canonical_url == url).order_by(JobSearchResult.id))
        if job_result is not None:
            db.add(YahooJobProvenance(candidate_id=candidate.id, provenance_type="jsearch", provider_job_id=job_result.external_id, source_url=url, source_label="JSearch", details={"job_search_result_id": job_result.id}))
    return candidate, False


def _date_range(connection: YahooMailConnection, request: MailSyncRequest) -> tuple[datetime | None, datetime | None]:
    date_to = _utc(request.date_to) or now()
    if request.last_days:
        date_from = date_to - timedelta(days=request.last_days)
    else:
        date_from = _utc(request.date_from)
    if request.mode == "initial" and date_from is None:
        date_from = connection.initial_sync_from
    return date_from, date_to


def _record_message_error(db: Session, run: YahooMailSyncRun, uid: int, message: str) -> None:
    scanned = run.messages_scanned
    db.rollback()
    db.refresh(run)
    run.messages_scanned = scanned
    run.errors += 1
    run.summary = {**(run.summary or {}), f"uid_{uid}": message[:300]}
    db.commit()


def sync_connection(db: Session, connection: YahooMailConnection, settings: Settings, request: MailSyncRequest, actor: str) -> YahooMailSyncRun:
    lock = SourceLock(settings, f"cybersec:yahoo-mail:{connection.id}")
    if not lock.acquire():
        raise YahooMailError("Another Yahoo Mail synchronization is already running")
    try:
        return _sync_locked(db, connection, settings, request, actor)
    finally:
        lock.release()


def _sync_locked(db: Session, connection: YahooMailConnection, settings: Settings, request: MailSyncRequest, actor: str) -> YahooMailSyncRun:
    date_from, date_to = _date_range(connection, request)
    run = YahooMailSyncRun(connection_id=connection.id, mode=request.mode, mailbox=connection.folder, date_from=date_from, date_to=date_to, uidvalidity_before=connection.uidvalidity, last_uid_before=connection.last_uid, created_by=actor)
    db.add(run)
    connection.status = "syncing"
    connection.last_sync_error = None
    db.commit()
    db.refresh(run)
    try:
        with YahooImapClient(settings) as client:
            client.login(connection.email_address, decrypt_app_password(settings, connection.encrypted_app_password), connection.folder)
            uidvalidity_reset = bool(connection.uidvalidity) and connection.uidvalidity != client.uidvalidity
            if uidvalidity_reset:
                minimum_uid = 0
            else:
                minimum_uid = 0 if request.mode == "initial" else connection.last_uid
            uids = client.search_uids(date_from=date_from, date_to=date_to, minimum_uid=minimum_uid)
            run.uidvalidity_after = client.uidvalidity
            for uid in uids:
                run.messages_scanned += 1
                try:
                    message = client.fetch_message(uid)
                    parsed = parse_alert(message.raw, uid=uid, uidvalidity=message.uidvalidity, max_jobs=settings.mail_max_candidates_per_message)
                    if parsed is None:
                        continue
                    source = _ensure_alert_source(db, connection)
                    if not source.enabled:
                        continue
                    if source.subject_pattern and source.subject_pattern.casefold() not in parsed.subject.casefold():
                        continue
                    email = db.scalar(select(YahooAlertEmail).where(YahooAlertEmail.connection_id == connection.id, YahooAlertEmail.mailbox == connection.folder, YahooAlertEmail.uidvalidity == message.uidvalidity, YahooAlertEmail.uid == uid))
                    if email is not None:
                        continue
                    email = YahooAlertEmail(connection_id=connection.id, sync_run_id=run.id, alert_source_id=source.id, mailbox=connection.folder, uidvalidity=message.uidvalidity, uid=uid, message_id=parsed.message_id, sender_address=parsed.sender, subject=parsed.subject, received_at=parsed.received_at, authentication_headers=parsed.authentication_headers, content_hash=parsed.content_hash)
                    db.add(email)
                    db.flush()
                    run.alerts_detected += 1
                    source.detection_count += 1
                    source.last_detected_at = now()
                    for item in parsed.jobs:
                        candidate, existed = _insert_candidate(db, email, item, settings)
                        if candidate.duplicate_status == "duplicate":
                            run.duplicates += 1
                        if not existed:
                            run.jobs_extracted += 1
                    db.commit()
                except YahooMailError as exc:
                    if exc.retryable:
                        # Connection-level failure: abort without advancing the checkpoint so these UIDs are retried.
                        raise
                    _record_message_error(db, run, uid, str(exc))
                except Exception as exc:
                    # A malformed or unexpected message is recorded and skipped so it cannot block every later sync.
                    _record_message_error(db, run, uid, f"{type(exc).__name__}: {exc}")
            connection.uidvalidity = client.uidvalidity
            connection.last_uid = max(uids, default=0) if uidvalidity_reset else max([connection.last_uid, *uids])
            connection.last_successful_sync = now()
            connection.status = "connected"
            connection.messages_scanned += run.messages_scanned
            connection.alerts_detected += run.alerts_detected
            connection.jobs_extracted += run.jobs_extracted
            connection.last_sync_error = None
            connection.next_sync_at = now() + timedelta(minutes=connection.sync_interval_minutes) if connection.automatic_sync_enabled else None
            run.status = "completed_with_errors" if run.errors else "completed"
    except (YahooMailError, MailConfigurationError) as exc:
        db.rollback()
        run = db.get(YahooMailSyncRun, run.id)
        connection = db.get(YahooMailConnection, connection.id)
        run.status = "failed"
        run.error_message = str(exc)
        connection.status = "error"
        connection.last_sync_error = str(exc)
    except Exception as exc:
        db.rollback()
        run = db.get(YahooMailSyncRun, run.id)
        connection = db.get(YahooMailConnection, connection.id)
        run.status = "failed"
        run.error_message = "Yahoo synchronization failed"
        connection.status = "error"
        connection.last_sync_error = type(exc).__name__
    finally:
        run = db.get(YahooMailSyncRun, run.id)
        run.completed_at = now()
        run.uidvalidity_after = run.uidvalidity_after or connection.uidvalidity
        run.last_uid_after = connection.last_uid
        run.summary = {**(run.summary or {}), "messages_scanned": run.messages_scanned, "alerts_detected": run.alerts_detected, "jobs_extracted": run.jobs_extracted, "duplicates": run.duplicates, "errors": run.errors}
        db.commit()
    return run


def retry_description(db: Session, candidate: YahooJobCandidate, settings: Settings) -> YahooJobCandidate:
    if not candidate.job_url:
        raise ValueError("Candidate has no job URL")
    description = ""
    method = ""
    if settings.jsearch_api_key:
        try:
            provider = JSearchProvider(settings)
            criteria = JobSearchCriteria(keywords=[candidate.title], location=candidate.location, experience_level="", date_posted="any", employment_type="", work_mode="", max_results=10, country="us", max_pages=1)
            page = provider.search(criteria, limit=10)
            match = next((item for item in page.items if canonical_job_url(item.url) == candidate.job_url), None)
            if match is not None:
                description = provider.retrieve_description(match)
                method = "jsearch"
        except (CollectionError, ValueError):
            description = ""
    if not description:
        imported = UrlImporter(settings).import_job(candidate.job_url)
        description = imported.job_description
        method = imported.extraction_method
    candidate.description_text = description[:settings.max_research_bytes]
    candidate.description_complete = len(candidate.description_text.strip()) >= 240
    candidate.description_status = "complete" if candidate.description_complete else "partial"
    candidate.metadata_payload = {**(candidate.metadata_payload or {}), "description_retrieval": method}
    db.commit()
    db.refresh(candidate)
    return candidate


def _registry_source(db: Session, actor: str) -> AutomatedResearchSource:
    source = db.scalar(select(AutomatedResearchSource).where(AutomatedResearchSource.name == "Yahoo LinkedIn Job Alerts"))
    if source is None:
        source = AutomatedResearchSource(name="Yahoo LinkedIn Job Alerts", source_type="yahoo_mail", endpoint_url="imap://imap.mail.yahoo.com:993", enabled=True, collection_frequency="manual", configuration={"allowed_sender": ALLOWED_SENDER}, created_by=actor)
        db.add(source)
        db.flush()
    return source


def ingest_candidate(db: Session, candidate: YahooJobCandidate, settings: Settings, actor: str) -> YahooJobCandidate:
    if candidate.review_status != "approved":
        raise ValueError("Only approved candidates can enter research ingestion")
    allow_partial = bool((candidate.metadata_payload or {}).get("allow_partial_source"))
    if not candidate.description_complete and not allow_partial:
        raise ValueError("A complete job description is required before ingestion")
    if not candidate.description_text.strip():
        raise ValueError("The candidate has no description text to ingest")
    source = _registry_source(db, actor)
    version, duplicate, duplicate_version = _create_version(db, source, CollectedItem(title=candidate.title, url=candidate.job_url, content=candidate.description_text, published_at=candidate.posted_at or candidate.received_at, metadata={"yahoo_candidate_id": candidate.id, "source_provider": candidate.source_provider, "incomplete_source": not candidate.description_complete}))
    db.flush()
    candidate.research_content_version_id = (duplicate_version or version).id if (duplicate_version or version) else None
    if duplicate:
        candidate.duplicate_status = "duplicate"
        candidate.duplicate_reason = "The approved description matches existing research content"
        candidate.ingestion_status = "duplicate_existing"
        db.commit()
        return candidate
    candidate.ingestion_status = "processing"
    db.commit()
    if _analyze_version(db, version, source, settings, providers):
        analysis = db.scalar(select(ResearchAutomationAnalysis).where(ResearchAutomationAnalysis.content_version_id == version.id))
        candidate.research_submission_id = analysis.submission_id if analysis else None
        candidate.ingestion_status = "analyzed"
    else:
        candidate.ingestion_status = "failed"
    db.commit()
    return candidate


def review_candidate(db: Session, candidate: YahooJobCandidate, action: str, payload: CandidateReview, actor: str) -> YahooJobCandidate:
    if action == "approve":
        if not candidate.description_complete and not payload.allow_partial:
            raise ValueError("Only complete descriptions can be approved; use the explicit partial-source override")
        candidate.review_status = "approved"
        candidate.ingestion_status = "queued"
        candidate.metadata_payload = {**(candidate.metadata_payload or {}), "allow_partial_source": bool(payload.allow_partial)}
        candidate.approved_by = actor
        candidate.approved_at = now()
    else:
        candidate.review_status = action
        candidate.ingestion_status = "not_approved"
    candidate.review_note = payload.note
    db.add(YahooJobReview(candidate_id=candidate.id, action=action, actor=actor, note=payload.note))
    db.commit()
    db.refresh(candidate)
    return candidate


BULK_REVIEW_STATUSES = {"approve": "approve", "reject": "rejected", "defer": "deferred"}


def bulk_review(db: Session, payload: BulkReview, actor: str) -> list[YahooJobCandidate]:
    candidates = list(db.scalars(select(YahooJobCandidate).where(YahooJobCandidate.id.in_(payload.candidate_ids))).all())
    if len(candidates) != len(set(payload.candidate_ids)):
        raise ValueError("One or more candidates were not found")
    action = BULK_REVIEW_STATUSES[payload.action]
    if action == "approve" and not payload.allow_partial:
        partial = [candidate.id for candidate in candidates if not candidate.description_complete]
        if partial:
            raise ValueError(f"Candidates {', '.join(map(str, sorted(partial)))} have partial descriptions; nothing was changed")
    for candidate in candidates:
        review_candidate(db, candidate, action, CandidateReview(note=payload.note, allow_partial=payload.allow_partial), actor)
    return candidates


def process_pending_candidates(settings: Settings, *, limit: int = 5) -> int:
    processed = 0
    with SessionLocal() as db:
        ids = list(db.scalars(select(YahooJobCandidate.id).where(YahooJobCandidate.review_status == "approved", YahooJobCandidate.ingestion_status == "queued").order_by(YahooJobCandidate.id).limit(limit)).all())
        for candidate_id in ids:
            candidate = db.get(YahooJobCandidate, candidate_id)
            if candidate is None:
                continue
            try:
                ingest_candidate(db, candidate, settings, "scheduler")
                processed += 1
            except Exception as exc:
                db.rollback()
                candidate = db.get(YahooJobCandidate, candidate_id)
                if candidate:
                    candidate.ingestion_status = "failed"
                    candidate.review_note = str(exc)[:2000]
                    db.commit()
    return processed


def run_due_yahoo_mail(settings: Settings) -> int:
    lock = SourceLock(settings, "cybersec:yahoo-mail:scheduler")
    if not lock.acquire():
        return 0
    count = 0
    try:
        with SessionLocal() as db:
            connections = list(db.scalars(select(YahooMailConnection).where(YahooMailConnection.enabled.is_(True), YahooMailConnection.automatic_sync_enabled.is_(True), YahooMailConnection.next_sync_at.is_not(None), YahooMailConnection.next_sync_at <= now())).all())
            for connection in connections:
                try:
                    sync_connection(db, connection, settings, MailSyncRequest(mode="incremental"), "scheduler")
                    count += 1
                except Exception:
                    db.rollback()
        count += process_pending_candidates(settings)
    finally:
        lock.release()
    return count


def sync_run_response(run: YahooMailSyncRun) -> dict[str, Any]:
    return {"id": run.id, "connection_id": run.connection_id, "mode": run.mode, "status": run.status, "mailbox": run.mailbox, "started_at": run.started_at, "completed_at": run.completed_at, "date_from": run.date_from, "date_to": run.date_to, "messages_scanned": run.messages_scanned, "alerts_detected": run.alerts_detected, "jobs_extracted": run.jobs_extracted, "duplicates": run.duplicates, "errors": run.errors, "error_message": run.error_message, "summary": run.summary or {}}


def candidate_response(candidate: YahooJobCandidate) -> dict[str, Any]:
    email = candidate.alert_email
    return {"id": candidate.id, "title": candidate.title, "employer": candidate.employer, "location": candidate.location, "work_mode": candidate.work_mode, "job_url": candidate.job_url, "source_provider": candidate.source_provider, "received_at": candidate.received_at, "posted_at": candidate.posted_at, "description_text": candidate.description_text, "description_complete": candidate.description_complete, "description_status": candidate.description_status, "extraction_method": candidate.extraction_method, "review_status": candidate.review_status, "duplicate_status": candidate.duplicate_status, "duplicate_reason": candidate.duplicate_reason, "ingestion_status": candidate.ingestion_status, "approved_by": candidate.approved_by, "approved_at": candidate.approved_at, "review_note": candidate.review_note, "alert_email_id": candidate.alert_email_id, "alert_subject": email.subject if email else "", "alert_sender": email.sender_address if email else ALLOWED_SENDER, "alert_received_at": email.received_at if email else candidate.received_at, "provenance": [{"type": item.provenance_type, "provider_job_id": item.provider_job_id, "source_url": item.source_url, "source_label": item.source_label, "details": item.details} for item in candidate.provenance], "research_submission_id": candidate.research_submission_id, "first_seen_at": candidate.first_seen_at, "metadata": candidate.metadata_payload or {}}
