from __future__ import annotations

import difflib
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_providers import AIProviderRegistry
from .config import Settings
from .models import (
    AutomatedResearchSource,
    ResearchAutomationAnalysis,
    ResearchAutomationAudit,
    ResearchChangeEvent,
    ResearchCollectionAttempt,
    ResearchContentVersion,
    ResearchRun,
    ResearchSchedule,
    ResearchSource,
    ResearchSubmission,
)
from .model_selection import ModelSelectionService
from .phase5_api import providers
from .phase5_service import content_digest, process_submission
from .phase6_collectors import CollectionError, CollectedItem, ResearchCollector, normalize_content, normalize_url, with_retries

UTC = timezone.utc
_local_locks: dict[str, threading.Lock] = {}
_local_locks_guard = threading.Lock()


def now() -> datetime:
    return datetime.now(UTC)


def schedule_delta(frequency: str, interval_minutes: int) -> timedelta | None:
    if frequency == "daily":
        return timedelta(days=1)
    if frequency == "weekly":
        return timedelta(days=7)
    if frequency == "interval":
        return timedelta(minutes=interval_minutes)
    return None


class SourceLock:
    def __init__(self, settings: Settings, key: str):
        self.settings = settings
        self.key = key
        self.token = hashlib.sha256(f"{key}:{id(self)}".encode()).hexdigest()
        redis_url = getattr(settings, "redis_url", None)
        self.client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True) if redis_url else None
        self.local_lock: threading.Lock | None = None
        self.redis_acquired = False

    def acquire(self) -> bool:
        try:
            if self.client is not None:
                self.redis_acquired = bool(self.client.set(self.key, self.token, nx=True, ex=self.settings.research_lock_ttl_seconds))
                return self.redis_acquired
        except redis.RedisError:
            pass
        with _local_locks_guard:
            self.local_lock = _local_locks.setdefault(self.key, threading.Lock())
        return self.local_lock.acquire(blocking=False)

    def release(self) -> None:
        if self.redis_acquired:
            try:
                script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
                self.client.eval(script, 1, self.key, self.token)
            except redis.RedisError:
                pass
        elif self.local_lock is not None and self.local_lock.locked():
            self.local_lock.release()


def _source_matches(source: AutomatedResearchSource, filters: dict[str, Any]) -> bool:
    for field in ("industry", "domain", "career_level"):
        value = filters.get(field)
        allowed = getattr(source, f"applicable_{field}s", [])
        if value and allowed and value not in allowed:
            return False
    keywords = [str(value).casefold() for value in filters.get("keywords", []) if value]
    configured = [str(value).casefold() for value in source.keywords or []]
    return not keywords or not configured or bool(set(keywords).intersection(configured))


def select_sources(db: Session, source_ids: list[int] | None, filters: dict[str, Any], *, due_only: bool = False) -> list[AutomatedResearchSource]:
    query = select(AutomatedResearchSource).where(AutomatedResearchSource.enabled.is_(True)).order_by(AutomatedResearchSource.name)
    if source_ids:
        query = query.where(AutomatedResearchSource.id.in_(source_ids))
    if due_only:
        query = query.join(ResearchSchedule).where(
            ResearchSchedule.enabled.is_(True), ResearchSchedule.paused.is_(False),
            ResearchSchedule.next_run_at.is_not(None), ResearchSchedule.next_run_at <= now(),
        )
    return [source for source in db.scalars(query).unique().all() if _source_matches(source, filters)]


def create_run(db: Session, *, source_ids: list[int] | None, filters: dict[str, Any], trigger: str, actor: str) -> ResearchRun:
    sources = select_sources(db, source_ids, filters)
    if source_ids and len(sources) != len(set(source_ids)):
        raise ValueError("One or more requested research sources are missing, disabled, or outside the selected target filters")
    run = ResearchRun(
        trigger=trigger, status="queued", requested_source_ids=[source.id for source in sources],
        target_filters=filters, created_by=actor, summary={"source_count": len(sources)},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _version_for(db: Session, source_id: int, canonical_url: str) -> ResearchContentVersion | None:
    return db.scalar(select(ResearchContentVersion).where(
        ResearchContentVersion.registry_source_id == source_id,
        ResearchContentVersion.canonical_url == canonical_url,
        ResearchContentVersion.status != "duplicate",
    ).order_by(ResearchContentVersion.version_number.desc()))


def _global_hash_match(db: Session, content_hash: str) -> ResearchContentVersion | None:
    return db.scalar(select(ResearchContentVersion).where(
        ResearchContentVersion.content_hash == content_hash,
        ResearchContentVersion.status.in_(["analyzed", "collected"]),
    ).order_by(ResearchContentVersion.id.asc()))


def _diff_summary(previous: ResearchContentVersion | None, current: ResearchContentVersion) -> dict[str, Any]:
    if previous is None:
        return {"change_type": "new_source", "added": current.normalized_content[:500], "removed": ""}
    previous_words = previous.normalized_content.split()
    current_words = current.normalized_content.split()
    additions: list[str] = []
    removals: list[str] = []
    for opcode, start_a, end_a, start_b, end_b in difflib.SequenceMatcher(None, previous_words, current_words).get_opcodes():
        if opcode in {"replace", "insert"}:
            additions.extend(current_words[start_b:end_b])
        if opcode in {"replace", "delete"}:
            removals.extend(previous_words[start_a:end_a])
    return {"change_type": "content_changed", "added": " ".join(additions)[:1000], "removed": " ".join(removals)[:1000], "previous_hash": previous.content_hash, "current_hash": current.content_hash}


def _create_version(db: Session, registry_source: AutomatedResearchSource, item: CollectedItem) -> tuple[ResearchContentVersion | None, bool, ResearchContentVersion | None]:
    canonical_url = normalize_url(item.url)
    normalized = normalize_content(item.content)
    digest = content_digest(normalized)
    current = _version_for(db, registry_source.id, canonical_url)
    if current is not None and current.content_hash == digest:
        current.last_seen_at = now()
        db.flush()
        return current, True, current
    duplicate = _global_hash_match(db, digest)
    if duplicate is not None and duplicate.registry_source_id != registry_source.id:
        version = ResearchContentVersion(
            registry_source_id=registry_source.id, research_source_id=None, canonical_url=canonical_url,
            title=item.title[:300], normalized_content=normalized, content_hash=digest, content_size=len(normalized.encode()),
            version_number=(current.version_number + 1 if current else 1), status="duplicate", duplicate_of_id=duplicate.id,
            metadata_payload=item.metadata or {}, first_seen_at=now(), last_seen_at=now(),
        )
        db.add(version)
        db.flush()
        return version, True, duplicate
    version_number = current.version_number + 1 if current else 1
    research_source = ResearchSource(
        source_type=f"automated_{registry_source.source_type}", source_url=canonical_url,
        source_title=item.title[:300] or "Automated cybersecurity research", collected_at=getattr(item, "published_at", None) or now(),
        notes=f"Collected by approved source registry '{registry_source.name}'. Automated content is untrusted research input.",
    )
    db.add(research_source)
    db.flush()
    version = ResearchContentVersion(
        registry_source_id=registry_source.id, research_source_id=research_source.id, canonical_url=canonical_url,
        title=item.title[:300] or "Automated cybersecurity research", normalized_content=normalized,
        content_hash=digest, content_size=len(normalized.encode()), version_number=version_number,
        status="collected", metadata_payload=item.metadata or {}, first_seen_at=now(), last_seen_at=now(),
    )
    db.add(version)
    db.flush()
    if current is not None:
        event = ResearchChangeEvent(
            registry_source_id=registry_source.id, previous_version_id=current.id, current_version_id=version.id,
            change_type="content_changed", summary=_diff_summary(current, version), status="detected", detected_at=now(),
        )
        db.add(event)
    return version, False, current


def _analyze_version(db: Session, version: ResearchContentVersion, registry_source: AutomatedResearchSource, settings: Settings, provider_registry: AIProviderRegistry) -> bool:
    selection = ModelSelectionService(provider_registry, settings)
    provider, model_id, _ = selection.active_selection(db)
    submission = ResearchSubmission(
        source_id=version.research_source_id, source_type=f"automated_{registry_source.source_type}",
        content_sha256=version.content_hash, content_size=version.content_size, status="received",
        model_provider=provider, model_id=model_id, model_name=model_id, evaluation_version="phase6-v1",
        submitted_at=version.first_seen_at,
    )
    db.add(submission)
    db.flush()
    analysis = ResearchAutomationAnalysis(
        content_version_id=version.id, submission_id=submission.id, provider=provider, model_id=model_id,
        prompt_version="phase6-v1", analysis_version="phase6-v1", status="processing", started_at=now(),
    )
    db.add(analysis)
    db.flush()
    try:
        process_submission(db, submission, version.normalized_content, provider_registry, settings)
        analysis.status = "completed"
        analysis.finding_count = len((submission.extraction_payload or {}).get("requirements", []))
        analysis.result_payload = submission.extraction_payload
        analysis.completed_at = now()
        version.status = "analyzed"
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        analysis = db.get(ResearchAutomationAnalysis, analysis.id)
        version = db.get(ResearchContentVersion, version.id)
        if analysis is not None:
            analysis.status = "failed"
            analysis.error_message = str(exc)[:500]
            analysis.completed_at = now()
        if version is not None:
            version.status = "failed"
        db.commit()
        return False


def _item_matches(item: CollectedItem, filters: dict[str, Any]) -> bool:
    haystack = f"{getattr(item, 'title', '')} {getattr(item, 'content', '')}".casefold()
    keywords = [str(value).casefold() for value in filters.get("keywords", []) if value]
    if keywords and not any(keyword in haystack for keyword in keywords):
        return False
    published_at = getattr(item, "published_at", None)
    for key, before in (("date_from", "min"), ("date_to", "max")):
        value = filters.get(key)
        if value and published_at is not None:
            target = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if before == "min" and published_at < target:
                return False
            if before == "max" and published_at > target:
                return False
    return True


def execute_run(db: Session, run: ResearchRun, settings: Settings, *, collector: ResearchCollector | None = None, provider_registry: AIProviderRegistry | None = None) -> ResearchRun:
    collector = collector or ResearchCollector(settings)
    provider_registry = provider_registry or providers
    run.status = "running"
    run.started_at = now()
    db.commit()
    sources = select_sources(db, run.requested_source_ids, run.target_filters)
    for source in sources:
        lock = SourceLock(settings, f"cybersec:research:source:{source.id}")
        if not lock.acquire():
            continue
        attempt = ResearchCollectionAttempt(run_id=run.id, source_id=source.id, status="running", started_at=now())
        source.last_attempted_collection = now()
        source.collection_status = "running"
        db.add(attempt)
        db.commit()
        try:
            items = [item for item in collector.collect(source) if _item_matches(item, run.target_filters or {})]
            attempt.items_discovered = len(items)
            collected = 0
            analyzed = 0
            duplicates = 0
            for item in items:
                version, duplicate, _ = _create_version(db, source, item)
                db.commit()
                if duplicate:
                    duplicates += 1
                    continue
                collected += 1
                if _analyze_version(db, version, source, settings, provider_registry):
                    analyzed += 1
            attempt.items_collected = collected
            attempt.items_analyzed = analyzed
            attempt.status = "completed"
            attempt.completed_at = now()
            source.collection_status = "success"
            source.last_successful_collection = now()
            source.last_error = None
            run.sources_collected += collected
            run.sources_analyzed += analyzed
            run.duplicates_skipped += duplicates
            db.commit()
        except CollectionError as exc:
            attempt.status = "failed"
            attempt.error_message = str(exc)[:500]
            attempt.completed_at = now()
            attempt.retry_count = settings.research_retry_count if exc.retryable else 0
            source.collection_status = "failed"
            source.last_error = str(exc)[:500]
            run.failed_collections += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            attempt = db.get(ResearchCollectionAttempt, attempt.id)
            source = db.get(AutomatedResearchSource, source.id)
            if attempt is not None:
                attempt.status = "failed"
                attempt.error_message = str(exc)[:500]
                attempt.completed_at = now()
            if source is not None:
                source.collection_status = "failed"
                source.last_error = str(exc)[:500]
            run.failed_collections += 1
            db.commit()
        finally:
            lock.release()
    run.status = "completed" if run.failed_collections == 0 else "completed_with_errors"
    run.completed_at = now()
    run.summary = {
        "sources_collected": run.sources_collected, "sources_analyzed": run.sources_analyzed,
        "duplicates_skipped": run.duplicates_skipped, "failed_collections": run.failed_collections,
    }
    db.add(ResearchAutomationAudit(actor=run.created_by, action="run_completed", run_id=run.id, details=run.summary))
    db.commit()
    return run


def schedule_next(schedule: ResearchSchedule, when: datetime | None = None) -> None:
    delta = schedule_delta(schedule.frequency, schedule.interval_minutes)
    schedule.last_run_at = when or now()
    schedule.next_run_at = (schedule.last_run_at + delta) if delta else None


def run_due_schedules(settings: Settings) -> int:
    from .database import SessionLocal

    lock = SourceLock(settings, "cybersec:research:scheduler")
    if not lock.acquire():
        return 0
    count = 0
    try:
        with SessionLocal() as db:
            sources = select_sources(db, None, {}, due_only=True)
            for source in sources:
                schedule = source.schedule
                if schedule is None:
                    continue
                run = create_run(db, source_ids=[source.id], filters={}, trigger="scheduled", actor="scheduler")
                schedule_next(schedule)
                db.commit()
                execute_run(db, run, settings)
                count += 1
    finally:
        lock.release()
    return count
