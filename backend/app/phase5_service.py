import csv
import hashlib
import io
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .models import (
    CareerLevel,
    Competency,
    CompetencyCategory,
    DomainLevelExpectation,
    DraftEvidence,
    DraftExpectation,
    ExpectationSource,
    ResearchFinding,
    ResearchSource,
    ResearchSubmission,
    SecurityDomain,
)
from .ai_providers import AIProviderRegistry
from .ollama_client import OllamaClient
from .phase5_schemas import DraftUpdate, ExtractionResult, ExtractedRequirement

logger = logging.getLogger("cybersec.research")
ALLOWED_EXTENSIONS = {".txt", ".json", ".csv"}
ALIAS_MAP = {
    "k8s": "kubernetes-security",
    "kubernetes": "kubernetes-security",
    "secure boot chain": "secure-boot",
    "verified boot": "secure-boot",
}
LEVEL_ALIASES = {
    "entry": "junior", "entry-level": "junior", "mid": "intermediate", "mid-level": "intermediate",
    "lead": "senior", "staff": "architect", "principal": "architect", "head": "director",
}
CATEGORY_FALLBACK = "technical-skills"


def parse_research_file(filename: str | None, content: bytes, max_bytes: int) -> tuple[str, str]:
    safe_name = PurePath(filename or "research.txt").name
    if safe_name != (filename or "research.txt") or safe_name in {".", ".."}:
        raise ValueError("path traversal is not allowed")
    extension = PurePath(safe_name).suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("only TXT, JSON, and CSV research files are supported")
    if len(content) > max_bytes:
        raise ValueError(f"research input exceeds the {max_bytes}-byte limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("research files must be UTF-8 text") from exc
    if extension == ".txt":
        result = text
    elif extension == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON research file") from exc
        result = _json_text(payload)
    else:
        rows = csv.reader(io.StringIO(text))
        result = "\n".join(" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)
    result = result.strip()
    if not result:
        raise ValueError("research input cannot be empty")
    return safe_name, result


def _json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_json_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(_json_text(item) for item in value)
    return str(value)


def taxonomy(db: Session) -> dict[str, list[dict]]:
    domains = list(db.scalars(select(SecurityDomain).order_by(SecurityDomain.display_order, SecurityDomain.name)).all())
    levels = list(db.scalars(select(CareerLevel).order_by(CareerLevel.display_order)).all())
    categories = list(db.scalars(select(CompetencyCategory).order_by(CompetencyCategory.name)).all())
    return {
        "domains": [{"slug": item.slug, "name": item.name, "parent_id": item.parent_id} for item in domains],
        "career_levels": [{"slug": item.slug, "name": item.name, "track": item.career_track} for item in levels],
        "categories": [{"slug": item.slug, "name": item.name} for item in categories],
        "competencies": [{"slug": item.slug, "name": item.name, "category_slug": item.category.slug if item.category else None} for item in db.scalars(select(Competency).options(selectinload(Competency.category)).order_by(Competency.name)).all()],
    }


def normalize_competency(candidate: str, competencies: list[Competency]) -> tuple[Competency | None, str]:
    cleaned = re.sub(r"\s+", " ", candidate.strip())
    candidate_key = cleaned.casefold()
    lookup = {item.slug.casefold(): item for item in competencies} | {item.name.casefold(): item for item in competencies}
    canonical_key = ALIAS_MAP.get(candidate_key, candidate_key)
    match = lookup.get(canonical_key)
    if match:
        return match, match.name
    for item in competencies:
        if item.name.casefold() == candidate_key or item.slug.casefold() == candidate_key:
            return item, item.name
    return None, cleaned


def classify_domain(requirement: ExtractedRequirement, domains: list[SecurityDomain]) -> SecurityDomain | None:
    lookup = {item.slug.casefold(): item for item in domains} | {item.name.casefold(): item for item in domains}
    for value in [*requirement.domain_slugs, *requirement.security_subdomains]:
        if value.casefold() in lookup:
            return lookup[value.casefold()]
    haystack = f"{requirement.competency_name} {requirement.technical_knowledge} {requirement.practical_capability}".casefold()
    return next((item for item in domains if item.name.casefold() in haystack or item.slug.replace("-", " ") in haystack), None)


def classify_level(requirement: ExtractedRequirement, levels: list[CareerLevel]) -> CareerLevel | None:
    lookup = {item.slug.casefold(): item for item in levels} | {item.name.casefold(): item for item in levels}
    requested = (requirement.career_level or "").strip().casefold()
    requested = LEVEL_ALIASES.get(requested, requested)
    if requested in lookup:
        return lookup[requested]
    haystack = f"{requirement.responsibilities} {requirement.practical_capability} {requirement.technical_knowledge}".casefold()
    if any(word in haystack for word in ("director", "organizational strategy", "executive")):
        requested = "director"
    elif any(word in haystack for word in ("manager", "manage a team", "people leadership")):
        requested = "manager"
    elif any(word in haystack for word in ("architect", "architecture strategy", "technical direction", "principal")):
        requested = "architect"
    elif any(word in haystack for word in ("lead", "mentor", "cross-functional leadership")):
        requested = "senior"
    elif requirement.experience_years_min is not None and requirement.experience_years_min >= 8:
        requested = "architect"
    elif requirement.experience_years_min is not None and requirement.experience_years_min >= 4:
        requested = "senior"
    return lookup.get(requested)


def category_for(requirement: ExtractedRequirement, categories: list[CompetencyCategory]) -> CompetencyCategory | None:
    lookup = {item.slug.casefold(): item for item in categories} | {item.name.casefold(): item for item in categories}
    return lookup.get((requirement.category_slug or CATEGORY_FALLBACK).casefold()) or lookup.get(CATEGORY_FALLBACK)


def consolidate(db: Session, submission: ResearchSubmission, extraction: ExtractionResult, settings: Settings) -> None:
    domains = list(db.scalars(select(SecurityDomain)).all())
    levels = list(db.scalars(select(CareerLevel)).all())
    categories = list(db.scalars(select(CompetencyCategory)).all())
    competencies = list(db.scalars(select(Competency).options(selectinload(Competency.category))).all())
    grouped: dict[tuple[int, int, int], list[tuple[ExtractedRequirement, Competency]]] = defaultdict(list)
    for requirement in extraction.requirements:
        domain = classify_domain(requirement, domains)
        level = classify_level(requirement, levels)
        category = category_for(requirement, categories)
        competency, normalized_name = normalize_competency(requirement.competency_name, competencies)
        finding = ResearchFinding(
            submission_id=submission.id, domain_id=domain.id if domain else None, career_level_id=level.id if level else None,
            category_id=category.id if category else None, competency_id=competency.id if competency else None,
            candidate_name=requirement.competency_name, normalized_name=normalized_name, finding_type=requirement.finding_type,
            technical_knowledge=requirement.technical_knowledge, practical_capability=requirement.practical_capability,
            responsibilities=requirement.responsibilities, proficiency_level=requirement.proficiency_level,
            importance=requirement.importance, experience_years_min=requirement.experience_years_min,
            experience_years_max=requirement.experience_years_max, evidence_excerpt=requirement.evidence_excerpt,
            confidence=requirement.confidence, status="normalized" if domain and level and competency else "unmapped",
            details={"security_subdomains": requirement.security_subdomains},
        )
        db.add(finding)
        if domain and level and competency:
            grouped[(domain.id, level.id, competency.id)].append((requirement, competency))
    db.flush()
    for (domain_id, level_id, competency_id), items in grouped.items():
        description = _consolidated_description(items)
        existing = db.scalar(select(DomainLevelExpectation).where(
            DomainLevelExpectation.domain_id == domain_id,
            DomainLevelExpectation.career_level_id == level_id,
            DomainLevelExpectation.competency_id == competency_id,
            DomainLevelExpectation.expectation_description == description,
        ))
        if existing is not None:
            for requirement, _ in items:
                if not db.scalar(select(ExpectationSource).where(ExpectationSource.expectation_id == existing.id, ExpectationSource.source_id == submission.source_id)):
                    db.add(ExpectationSource(expectation_id=existing.id, source_id=submission.source_id, supporting_excerpt=requirement.evidence_excerpt))
            continue
        existing_draft = db.scalar(select(DraftExpectation).where(
            DraftExpectation.domain_id == domain_id, DraftExpectation.career_level_id == level_id,
            DraftExpectation.competency_id == competency_id, DraftExpectation.expectation_description == description,
            DraftExpectation.status.in_(["draft", "approved", "published"]),
        ))
        if existing_draft is not None:
            for requirement, _ in items:
                db.add(DraftEvidence(draft_id=existing_draft.id, source_id=submission.source_id, supporting_excerpt=requirement.evidence_excerpt))
            continue
        draft = DraftExpectation(
            submission_id=submission.id, domain_id=domain_id, career_level_id=level_id, competency_id=competency_id,
            expectation_description=description, proficiency_level=_highest(items, "proficiency_level", ("basic", "proficient", "advanced", "expert")),
            importance=_highest(items, "importance", ("optional", "important", "essential")),
            responsibility_type=_responsibility(items),
            experience_years_min=_min_year(items, "experience_years_min"), experience_years_max=_max_year(items, "experience_years_max"),
            status="draft",
        )
        db.add(draft)
        db.flush()
        for requirement, _ in items:
            db.add(DraftEvidence(draft_id=draft.id, source_id=submission.source_id, supporting_excerpt=requirement.evidence_excerpt))


def _consolidated_description(items: list[tuple[ExtractedRequirement, Competency]]) -> str:
    statements = []
    for requirement, _ in items:
        statement = requirement.practical_capability or requirement.responsibilities or requirement.technical_knowledge
        if statement and statement.strip() not in statements:
            statements.append(statement.strip())
    return "; ".join(statements) if statements else f"Demonstrate practical capability in {items[0][1].name}."


def _highest(items, field: str, order: tuple[str, ...]) -> str:
    values = {getattr(item, field) for item, _ in items}
    return max(values, key=lambda value: order.index(value) if value in order else -1)


def _responsibility(items) -> str:
    values = [item.responsibilities.strip() for item, _ in items if item.responsibilities.strip()]
    return "consolidated" if len(values) != 1 else values[0][:80]


def _min_year(items, field: str) -> int | None:
    values = [getattr(item, field) for item, _ in items if getattr(item, field) is not None]
    return min(values) if values else None


def _max_year(items, field: str) -> int | None:
    values = [getattr(item, field) for item, _ in items if getattr(item, field) is not None]
    return max(values) if values else None


def process_submission(db: Session, submission: ResearchSubmission, content: str, client: OllamaClient | AIProviderRegistry, settings: Settings) -> None:
    submission.status = "processing"
    db.commit()
    try:
        provider = submission.model_provider or "ollama"
        selected_model = submission.model_id or submission.model_name or getattr(client, "model", settings.ollama_model)
        if isinstance(client, AIProviderRegistry):
            result = client.extract_selected(provider, selected_model, content, taxonomy(db))
        elif selected_model == client.model:
            result = client.extract(content, taxonomy(db))
        else:
            result = client.extract(content, taxonomy(db), model=selected_model)
        submission.extraction_payload = result.model_dump(mode="json")
        consolidate(db, submission, result, settings)
        submission.status = "draft_ready"
        submission.completed_at = datetime.now(timezone.utc)
        submission.error_message = None
        db.commit()
        logger.info("research_submission_completed submission_id=%d findings=%d", submission.id, len(result.requirements))
    except Exception as exc:
        db.rollback()
        submission = db.get(ResearchSubmission, submission.id)
        submission.status = "failed"
        submission.error_message = str(exc)[:500]
        submission.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.warning("research_submission_failed submission_id=%d error_type=%s", submission.id, type(exc).__name__)
        raise


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def published_expectation(db: Session, draft: DraftExpectation) -> DomainLevelExpectation | None:
    return db.scalar(select(DomainLevelExpectation).where(
        DomainLevelExpectation.domain_id == draft.domain_id,
        DomainLevelExpectation.career_level_id == draft.career_level_id,
        DomainLevelExpectation.competency_id == draft.competency_id,
        DomainLevelExpectation.expectation_description == draft.expectation_description,
    ))
