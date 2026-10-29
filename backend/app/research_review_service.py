from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from .models import (
    CareerLevel,
    Competency,
    CompetencyCategory,
    DomainLevelExpectation,
    ExpectationRevision,
    ExpectationSource,
    Industry,
    PublicationBatch,
    ResearchFinding,
    ResearchFindingDomain,
    ResearchFindingIndustry,
    ResearchSource,
    ResearchSubmission,
    ReviewAudit,
    ReviewChange,
    SecurityDomain,
)
from .research_review_schemas import ReviewMergeRequest, ReviewModifyRequest

APPROVED_STATUSES = {"accepted", "modified", "merged"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _ref(item: Any | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"id": item.id, "name": item.name, "slug": item.slug}


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result or "competency"


def _unique_text(*values: str | None) -> str:
    result: list[str] = []
    for value in values:
        if value and value.strip() and value.strip() not in result:
            result.append(value.strip())
    return "; ".join(result)


def _domain_items(finding: ResearchFinding) -> list[SecurityDomain]:
    linked = [link.domain for link in finding.domains if link.domain is not None]
    if linked:
        return linked
    return [finding.domain] if finding.domain is not None else []


def _expectation_snapshot(item: DomainLevelExpectation) -> dict[str, Any]:
    return {
        "id": item.id,
        "domain_id": item.domain_id,
        "career_level_id": item.career_level_id,
        "competency_id": item.competency_id,
        "industry_id": item.industry_id,
        "technical_knowledge": item.technical_knowledge,
        "practical_capability": item.practical_capability,
        "qualifications": item.qualifications,
        "tools_technologies": item.tools_technologies,
        "expectation_description": item.expectation_description,
        "proficiency_level": item.proficiency_level,
        "importance": item.importance,
        "responsibility_type": item.responsibility_type,
        "experience_years_min": item.experience_years_min,
        "experience_years_max": item.experience_years_max,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _competency_snapshot(item: Competency | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "id": item.id,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "category_id": item.category_id,
        "category": _ref(item.category),
    }


def _find_expectations(db: Session, finding: ResearchFinding) -> list[DomainLevelExpectation]:
    domain_ids = [item.id for item in _domain_items(finding)]
    if finding.competency_id is None or finding.career_level_id is None or not domain_ids:
        return []
    return list(db.scalars(select(DomainLevelExpectation).where(
        DomainLevelExpectation.competency_id == finding.competency_id,
        DomainLevelExpectation.career_level_id == finding.career_level_id,
        DomainLevelExpectation.industry_id == finding.primary_industry_id,
        DomainLevelExpectation.domain_id.in_(domain_ids),
    ).options(selectinload(DomainLevelExpectation.domain))).all())


def _incoming_snapshot(finding: ResearchFinding, domains: list[SecurityDomain]) -> dict[str, Any]:
    details = finding.details or {}
    return {
        "competency_name": finding.normalized_name or finding.candidate_name,
        "competency_description": finding.technical_knowledge or finding.practical_capability,
        "domain_ids": [domain.id for domain in domains],
        "domains": [_ref(domain) for domain in domains],
        "career_level_id": finding.career_level_id,
        "career_level": _ref(finding.career_level),
        "category_id": finding.category_id,
        "category": _ref(finding.category),
        "industry_id": finding.primary_industry_id,
        "industry": _ref(finding.primary_industry),
        "industry_classification_status": finding.industry_classification_status,
        "industry_classification_evidence": finding.industry_classification_evidence,
        "secondary_industries": [_ref(link.industry) for link in finding.industries if link.classification_role == "secondary"],
        "technical_knowledge": finding.technical_knowledge,
        "practical_capability": finding.practical_capability,
        "qualifications": details.get("qualifications", ""),
        "tools_technologies": details.get("tools_technologies", ""),
        "expectation_description": finding.practical_capability or finding.responsibilities or finding.technical_knowledge,
        "responsibilities": finding.responsibilities,
        "proficiency_level": finding.proficiency_level,
        "importance": finding.importance,
        "experience_years_min": finding.experience_years_min,
        "experience_years_max": finding.experience_years_max,
        "evidence": [{"source_id": finding.submission.source_id, "excerpt": finding.evidence_excerpt}],
        "finding_type": finding.finding_type,
    }


def _initial_change_type(finding: ResearchFinding, expectations: list[DomainLevelExpectation]) -> str:
    if finding.competency_id is None:
        return "new_competency"
    return "update_expectation" if expectations else "new_expectation"


def ensure_review_change(db: Session, finding: ResearchFinding) -> ReviewChange:
    existing = db.scalar(select(ReviewChange).where(ReviewChange.finding_id == finding.id))
    if existing is not None:
        return existing
    domains = _domain_items(finding)
    expectations = _find_expectations(db, finding)
    incoming = _incoming_snapshot(finding, domains)
    original = {
        "competency": _competency_snapshot(finding.competency),
        "expectations": [_expectation_snapshot(item) for item in expectations],
    }
    change = ReviewChange(
        submission_id=finding.submission_id,
        finding_id=finding.id,
        draft_id=None,
        target_competency_id=finding.competency_id,
        target_expectation_id=expectations[0].id if expectations else None,
        change_type=_initial_change_type(finding, expectations),
        status="pending",
        original_snapshot=original,
        proposed_snapshot=incoming,
        version=1,
        created_at=now(),
        updated_at=now(),
    )
    db.add(change)
    db.flush()
    db.add(ReviewAudit(change_id=change.id, action="created", actor="system", after_snapshot=incoming, note="Review proposal created from extracted finding."))
    return change


def ensure_submission_changes(db: Session, submission_id: int) -> list[ReviewChange]:
    findings = list(db.scalars(select(ResearchFinding).where(ResearchFinding.submission_id == submission_id).options(
        selectinload(ResearchFinding.domains).selectinload(ResearchFindingDomain.domain),
        selectinload(ResearchFinding.domain), selectinload(ResearchFinding.career_level),
        selectinload(ResearchFinding.category), selectinload(ResearchFinding.primary_industry),
        selectinload(ResearchFinding.industries).selectinload(ResearchFindingIndustry.industry),
        selectinload(ResearchFinding.competency).selectinload(Competency.category),
        selectinload(ResearchFinding.submission).selectinload(ResearchSubmission.source),
    )).all())
    return [ensure_review_change(db, finding) for finding in findings]


def ensure_all_changes(db: Session) -> list[ReviewChange]:
    findings = list(db.scalars(select(ResearchFinding).order_by(ResearchFinding.id).options(
        selectinload(ResearchFinding.domains).selectinload(ResearchFindingDomain.domain),
        selectinload(ResearchFinding.domain), selectinload(ResearchFinding.career_level),
        selectinload(ResearchFinding.category), selectinload(ResearchFinding.primary_industry),
        selectinload(ResearchFinding.industries).selectinload(ResearchFindingIndustry.industry),
        selectinload(ResearchFinding.competency).selectinload(Competency.category),
        selectinload(ResearchFinding.submission).selectinload(ResearchSubmission.source),
    )).all())
    changes = [ensure_review_change(db, finding) for finding in findings]
    db.commit()
    return changes


def snapshot_gaps(snapshot: dict[str, Any]) -> list[str]:
    gaps = []
    if not snapshot.get("domain_ids"):
        gaps.append("domain")
    if snapshot.get("career_level_id") is None:
        gaps.append("career_level")
    if snapshot.get("category_id") is None:
        gaps.append("category")
    if not (snapshot.get("competency_name") or "").strip():
        gaps.append("competency_name")
    if not (snapshot.get("expectation_description") or "").strip():
        gaps.append("expectation_description")
    return gaps


def review_gaps(finding: ResearchFinding, change: ReviewChange | None) -> list[str]:
    stored = (finding.details or {}).get("classification_gaps", [])
    if change is None:
        return stored
    # Gaps that would block acceptance come from the current proposal; extraction-time gaps (e.g. a fallback
    # category) still apply until a reviewer saves the proposal. "competency" only means no existing match.
    gaps = snapshot_gaps(change.proposed_snapshot)
    if change.reviewer_snapshot is None:
        gaps += [gap for gap in stored if gap not in gaps and gap not in {"domain", "career_level", "competency"}]
    return gaps


def finding_response(finding: ResearchFinding, change: ReviewChange | None = None) -> dict[str, Any]:
    details = finding.details or {}
    domains = _domain_items(finding)
    return {
        "id": finding.id,
        "finding_type": finding.finding_type,
        "candidate_name": finding.candidate_name,
        "normalized_name": finding.normalized_name,
        "technical_knowledge": finding.technical_knowledge,
        "practical_capability": finding.practical_capability,
        "qualifications": details.get("qualifications", ""),
        "tools_technologies": details.get("tools_technologies", ""),
        "responsibilities": finding.responsibilities,
        "proficiency_level": finding.proficiency_level,
        "importance": finding.importance,
        "experience_years_min": finding.experience_years_min,
        "experience_years_max": finding.experience_years_max,
        "evidence_excerpt": finding.evidence_excerpt,
        "confidence": finding.confidence,
        "confidence_meaningful": finding.confidence is not None and 0 <= finding.confidence <= 1,
        "status": finding.status,
        "classification_gaps": review_gaps(finding, change),
        "domains": [_ref(domain) for domain in domains],
        "career_level": _ref(finding.career_level),
        "category": _ref(finding.category),
        "competency": _competency_snapshot(finding.competency),
        "primary_industry": _ref(finding.primary_industry),
        "secondary_industries": [_ref(link.industry) for link in finding.industries if link.classification_role == "secondary"],
        "industry_classification_status": finding.industry_classification_status,
        "industry_classification_evidence": finding.industry_classification_evidence,
        "existing_matches": [_expectation_snapshot(item) for item in []],
        "review_change": change_response(change) if change else None,
    }


def change_response(change: ReviewChange) -> dict[str, Any]:
    return {
        "id": change.id,
        "finding_id": change.finding_id,
        "submission_id": change.submission_id,
        "change_type": change.change_type,
        "status": change.status,
        "version": change.version,
        "target_competency_id": change.target_competency_id,
        "target_expectation_id": change.target_expectation_id,
        "merge_target_competency_id": change.merge_target_competency_id,
        "reviewer_note": change.reviewer_note,
        "reviewed_by": change.reviewed_by,
        "reviewed_at": change.reviewed_at.isoformat() if change.reviewed_at else None,
        "original": change.original_snapshot,
        "proposed": change.proposed_snapshot,
        "reviewer_snapshot": change.reviewer_snapshot,
    }


def submission_summary(db: Session, submission: ResearchSubmission, changes: list[ReviewChange] | None = None) -> dict[str, Any]:
    changes = changes if changes is not None else list(submission.review_changes)
    finding_count = len(submission.findings)
    proposed_new = sum(1 for item in changes if item.change_type == "new_competency")
    proposed_updates = sum(1 for item in changes if item.change_type in {"new_expectation", "update_expectation", "merge"})
    duplicate_count = sum(1 for item in submission.findings if item.competency_id is not None)
    manual_count = sum(1 for item in submission.findings if (item.details or {}).get("classification_gaps"))
    statuses = {item.status for item in changes}
    review_status = "published" if statuses and statuses <= {"published", "rejected"} and "published" in statuses else ("in_review" if changes else "pending")
    return {
        "id": submission.id,
        "source_id": submission.source_id,
        "source_title": submission.source.source_title,
        "source_url": submission.source.source_url,
        "source_type": submission.source_type,
        "submitted_at": submission.submitted_at,
        "completed_at": submission.completed_at,
        "model_provider": submission.model_provider,
        "model_id": submission.model_id,
        "model_name": submission.model_name,
        "evaluation_version": submission.evaluation_version,
        "status": submission.status,
        "finding_count": finding_count,
        "proposed_new_competencies": proposed_new,
        "proposed_updates": proposed_updates,
        "potential_duplicates": duplicate_count,
        "manual_classification_count": manual_count,
        "review_status": review_status,
    }


def domain_impact(db: Session, changes: list[ReviewChange]) -> list[dict[str, Any]]:
    domain_ids: set[int] = set()
    grouped: dict[int, list[ReviewChange]] = defaultdict(list)
    for change in changes:
        for domain_id in change.proposed_snapshot.get("domain_ids", []):
            domain_ids.add(domain_id)
            grouped[domain_id].append(change)
    domains = {item.id: item for item in db.scalars(select(SecurityDomain).where(SecurityDomain.id.in_(domain_ids))).all()} if domain_ids else {}
    result = []
    for domain_id in sorted(domain_ids, key=lambda item: (domains.get(item).display_order if domains.get(item) else 0, item)):
        domain = domains.get(domain_id)
        if domain is None:
            continue
        rows = grouped[domain_id]
        existing_competencies = sorted({item.original_snapshot.get("competency", {}).get("name") for item in rows if item.original_snapshot.get("competency")})
        new_competencies = sorted({item.proposed_snapshot.get("competency_name") for item in rows if item.change_type == "new_competency"})
        modified = sorted({item.proposed_snapshot.get("competency_name") for item in rows if item.change_type in {"update_expectation", "modified"}})
        merged = sorted({item.proposed_snapshot.get("competency_name") for item in rows if item.status == "merged" or item.change_type == "merge"})
        levels = sorted({item.proposed_snapshot.get("career_level", {}).get("name") for item in rows if item.proposed_snapshot.get("career_level")})
        categories = sorted({item.proposed_snapshot.get("category", {}).get("name") for item in rows if item.proposed_snapshot.get("category")})
        result.append({
            "domain": _ref(domain),
            "subdomain": _ref(domain) if domain.parent_id else None,
            "change_count": len(rows),
            "existing_competencies": existing_competencies,
            "new_competencies": new_competencies,
            "modified_competencies": modified,
            "merged_competencies": merged,
            "career_levels": levels,
            "categories": categories,
            "evidence_changes": sum(1 for item in rows if item.proposed_snapshot.get("evidence")),
            "changes": [change_response(item) for item in rows],
        })
    return result


def _require_change(db: Session, change_id: int) -> ReviewChange:
    change = db.scalar(select(ReviewChange).where(ReviewChange.id == change_id).options(selectinload(ReviewChange.finding)))
    if change is None:
        raise HTTPException(status_code=404, detail="Review change was not found")
    return change


def _check_version(change: ReviewChange, expected_version: int) -> None:
    if change.version != expected_version:
        raise HTTPException(status_code=409, detail="Review change has been modified; reload it before continuing")
    if change.status in {"published", "rejected"}:
        raise HTTPException(status_code=409, detail=f"Review change is already {change.status}")


def _validate_snapshot(db: Session, snapshot: dict[str, Any]) -> None:
    domain_ids = snapshot.get("domain_ids") or []
    requested_domain_ids = set(domain_ids)
    found_domain_ids = set(db.scalars(select(SecurityDomain.id).where(SecurityDomain.id.in_(requested_domain_ids), SecurityDomain.is_active.is_(True))).all()) if requested_domain_ids else set()
    missing_domain_ids = sorted(requested_domain_ids - found_domain_ids)
    if not requested_domain_ids:
        raise HTTPException(status_code=422, detail="At least one security domain is required")
    if missing_domain_ids:
        raise HTTPException(status_code=422, detail=f"Security domain ids were not found: {missing_domain_ids}")
    for model, key, label in ((CareerLevel, "career_level_id", "career level"), (CompetencyCategory, "category_id", "competency category")):
        value = snapshot.get(key)
        item = db.get(model, value) if value is not None else None
        if item is None or not item.is_active:
            raise HTTPException(status_code=422, detail=f"A valid active {label} is required")
    if snapshot.get("industry_id") is not None:
        industry = db.get(Industry, snapshot["industry_id"])
        if industry is None or not industry.is_active:
            raise HTTPException(status_code=422, detail="A valid active industry is required")
    if snapshot.get("industry_classification_status") == "classified" and (snapshot.get("industry_id") is None or not snapshot.get("industry_classification_evidence", "").strip()):
        raise HTTPException(status_code=422, detail="Classified industry findings require an industry and supporting evidence")
    if not snapshot.get("competency_name", "").strip():
        raise HTTPException(status_code=422, detail="Competency name is required")
    if not snapshot.get("expectation_description", "").strip():
        raise HTTPException(status_code=422, detail="Expectation description is required")
    if not snapshot.get("evidence"):
        raise HTTPException(status_code=422, detail="At least one supporting evidence excerpt is required")


def _merge_supporting_evidence(snapshot: dict[str, Any], excerpts: list[str] | None) -> None:
    if not excerpts:
        return
    evidence = list(snapshot.get("evidence") or [])
    source_id = next((item.get("source_id") for item in evidence if item.get("source_id")), None)
    if source_id is None:
        raise HTTPException(status_code=422, detail="Reviewer evidence requires an existing research source")
    seen = {(item.get("source_id"), (item.get("excerpt") or "").strip()) for item in evidence}
    for excerpt in excerpts:
        cleaned = excerpt.strip()
        if cleaned and (source_id, cleaned) not in seen:
            evidence.append({"source_id": source_id, "excerpt": cleaned})
            seen.add((source_id, cleaned))
    snapshot["evidence"] = evidence


def _record(change: ReviewChange, action: str, actor: str, before: dict[str, Any] | None, after: dict[str, Any] | None, note: str | None) -> None:
    change.updated_at = now()
    change.version += 1
    change.reviewed_by = actor
    change.reviewed_at = now()
    change.reviewer_note = note
    change.audits.append(ReviewAudit(action=action, actor=actor, before_snapshot=before, after_snapshot=after, note=note))


def accept_change(db: Session, change_id: int, expected_version: int, actor: str, note: str | None, publish: bool = False) -> ReviewChange:
    change = _require_change(db, change_id)
    _check_version(change, expected_version)
    if change.status in APPROVED_STATUSES and not publish:
        raise HTTPException(status_code=409, detail=f"Review change is already {change.status}")
    if change.status not in APPROVED_STATUSES:
        proposed = deepcopy(change.proposed_snapshot)
        _validate_snapshot(db, proposed)
        change.status = "accepted"
        change.reviewer_snapshot = proposed
        _record(change, "accepted", actor, change.proposed_snapshot, proposed, note)
        if not publish:
            db.commit()
    if publish:
        # Accept-and-merge: publish this single change into the domain knowledge base right away.
        try:
            db.flush()
            publish_changes(db, [change.id], {change.id: change.version}, actor)
        except Exception:
            db.rollback()
            raise
        change = _require_change(db, change_id)
    return change


def modify_change(db: Session, change_id: int, payload: ReviewModifyRequest, actor: str) -> ReviewChange:
    change = _require_change(db, change_id)
    _check_version(change, payload.expected_version)
    before = deepcopy(change.proposed_snapshot)
    proposed = deepcopy(before)
    for key, value in payload.model_dump(exclude={"expected_version", "reviewer_note", "supporting_evidence"}, exclude_none=True).items():
        proposed[key] = value
    _merge_supporting_evidence(proposed, payload.supporting_evidence)
    if payload.domain_ids is not None:
        proposed["domain_ids"] = payload.domain_ids
        proposed["domains"] = [_ref(db.get(SecurityDomain, item)) for item in payload.domain_ids if db.get(SecurityDomain, item) is not None]
    if payload.career_level_id is not None:
        proposed["career_level"] = _ref(db.get(CareerLevel, payload.career_level_id))
    if payload.category_id is not None:
        proposed["category"] = _ref(db.get(CompetencyCategory, payload.category_id))
    if payload.industry_classification_status is not None:
        proposed["industry_classification_status"] = payload.industry_classification_status
        if payload.industry_classification_status in {"unknown", "general"}:
            proposed["industry_id"] = None
            proposed["industry"] = None
        elif payload.industry_id is not None:
            industry = db.get(Industry, payload.industry_id)
            if industry is None or not industry.is_active:
                raise HTTPException(status_code=422, detail="A valid active industry is required")
            proposed["industry_id"] = industry.id
            proposed["industry"] = _ref(industry)
    elif payload.industry_id is not None:
        industry = db.get(Industry, payload.industry_id)
        if industry is None or not industry.is_active:
            raise HTTPException(status_code=422, detail="A valid active industry is required")
        proposed["industry_id"] = industry.id
        proposed["industry"] = _ref(industry)
        proposed["industry_classification_status"] = "classified"
    _validate_snapshot(db, proposed)
    change.proposed_snapshot = proposed
    change.reviewer_snapshot = proposed
    change.status = "modified"
    _record(change, "modified", actor, before, proposed, payload.reviewer_note)
    db.commit()
    return change


def merge_change(db: Session, change_id: int, payload: ReviewMergeRequest, actor: str) -> ReviewChange:
    change = _require_change(db, change_id)
    _check_version(change, payload.expected_version)
    target = db.get(Competency, payload.target_competency_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Merge target competency was not found")
    before = deepcopy(change.proposed_snapshot)
    incoming = deepcopy(before)
    merged_fields = payload.merged.model_dump(exclude={"expected_version", "reviewer_note", "supporting_evidence"}, exclude_none=True) if payload.merged else {}
    incoming.update(merged_fields)
    _merge_supporting_evidence(incoming, payload.merged.supporting_evidence if payload.merged else None)
    incoming["competency_name"] = target.name
    incoming["competency_description"] = _unique_text(target.description, incoming.get("competency_description"))
    incoming["category_id"] = target.category_id
    incoming["category"] = _ref(target.category)
    incoming["domain_ids"] = incoming.get("domain_ids") or [item.get("id") for item in incoming.get("domains", [])]
    incoming["domains"] = [_ref(db.get(SecurityDomain, item)) for item in incoming["domain_ids"]]
    incoming["career_level"] = _ref(db.get(CareerLevel, incoming.get("career_level_id")))
    for field in ("technical_knowledge", "practical_capability", "qualifications", "tools_technologies", "expectation_description", "responsibilities"):
        incoming[field] = _unique_text(before.get(field), incoming.get(field))
    if not incoming.get("evidence"):
        incoming["evidence"] = before.get("evidence", [])
    _validate_snapshot(db, incoming)
    change.merge_target_competency_id = target.id
    change.target_competency_id = target.id
    change.proposed_snapshot = incoming
    change.reviewer_snapshot = incoming
    change.status = "merged"
    change.change_type = "merge"
    _record(change, "merged", actor, before, incoming, payload.reviewer_note or (payload.merged.reviewer_note if payload.merged else None))
    db.commit()
    return change


def reject_change(db: Session, change_id: int, expected_version: int, actor: str, note: str | None) -> ReviewChange:
    change = _require_change(db, change_id)
    _check_version(change, expected_version)
    change.status = "rejected"
    _record(change, "rejected", actor, change.proposed_snapshot, change.proposed_snapshot, note)
    db.commit()
    return change


def compare_change(db: Session, change: ReviewChange) -> dict[str, Any]:
    original = change.original_snapshot
    proposed = change.proposed_snapshot
    fields = (
        "competency_name", "competency_description", "technical_knowledge", "practical_capability",
        "qualifications", "tools_technologies", "expectation_description", "responsibilities",
        "proficiency_level", "importance", "experience_years_min", "experience_years_max",
        "domain_ids", "career_level_id", "category_id",
    )
    additions: list[dict[str, Any]] = []
    modifications: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    existing_expectation = (original.get("expectations") or [None])[0] or {}
    existing_competency = original.get("competency") or {}
    existing = {**existing_competency, **existing_expectation}
    incoming = change.finding
    for field in fields:
        old = existing.get(field)
        new = proposed.get(field)
        if (old in (None, "", [])) and new not in (None, "", []):
            additions.append({"field": field, "value": new})
        elif old not in (None, "", []) and new in (None, "", []):
            removals.append({"field": field, "value": old})
        elif old != new and new not in (None, "", []):
            modifications.append({"field": field, "before": old, "after": new})
    return {
        "change": change_response(change),
        "existing": original,
        "incoming": finding_response(incoming),
        "proposed": proposed,
        "differences": {"additions": additions, "modifications": modifications, "removals": removals},
        "evidence": proposed.get("evidence", []),
    }


def _select_changes(db: Session, change_ids: list[int] | None = None, *, lock: bool = False) -> list[ReviewChange]:
    query = select(ReviewChange).order_by(ReviewChange.id)
    if change_ids:
        query = query.where(ReviewChange.id.in_(change_ids))
    else:
        query = query.where(ReviewChange.status.in_(APPROVED_STATUSES))
    if lock:
        query = query.with_for_update()
    return list(db.scalars(query).all())


def publication_preview(db: Session, change_ids: list[int] | None = None, expected_versions: dict[int, int] | None = None) -> dict[str, Any]:
    changes = _select_changes(db, change_ids)
    blockers: list[str] = []
    expected_versions = expected_versions or {}
    if not changes:
        blockers.append("No approved changes are selected")
    for change in changes:
        if change.status not in APPROVED_STATUSES:
            blockers.append(f"Change {change.id} is not approved")
        if change.id in expected_versions and change.version != expected_versions[change.id]:
            blockers.append(f"Change {change.id} has changed since it was reviewed")
        try:
            _validate_snapshot(db, change.proposed_snapshot)
        except HTTPException as exc:
            blockers.append(f"Change {change.id}: {exc.detail}")
    impact = domain_impact(db, changes)
    levels = {}
    for change in changes:
        level = change.proposed_snapshot.get("career_level")
        if level:
            levels[level["id"]] = level
    return {
        "new_competencies": sum(1 for item in changes if item.change_type == "new_competency"),
        "updated_expectations": sum(1 for item in changes if item.change_type in {"new_expectation", "update_expectation"}),
        "merged_findings": sum(1 for item in changes if item.change_type == "merge"),
        "rejected_findings": sum(1 for item in db.scalars(select(ReviewChange).where(ReviewChange.status == "rejected")).all()),
        "affected_domains": [{"id": item["domain"]["id"], "name": item["domain"]["name"], "change_count": item["change_count"]} for item in impact],
        "affected_career_levels": list(levels.values()),
        "changes": [change_response(item) for item in changes],
        "ready": not blockers,
        "blockers": blockers,
    }


def _make_slug_unique(db: Session, name: str) -> str:
    base = _slug(name)
    slug = base
    index = 2
    while db.scalar(select(Competency).where(Competency.slug == slug)) is not None:
        slug = f"{base}-{index}"
        index += 1
    return slug


def _attach_evidence(db: Session, expectation: DomainLevelExpectation, change: ReviewChange) -> None:
    for evidence in change.proposed_snapshot.get("evidence", []):
        source_id = evidence.get("source_id")
        excerpt = (evidence.get("excerpt") or "").strip()
        if not source_id or not excerpt:
            continue
        exists = db.scalar(select(ExpectationSource).where(
            ExpectationSource.expectation_id == expectation.id,
            ExpectationSource.source_id == source_id,
        ))
        if exists is None:
            db.add(ExpectationSource(expectation_id=expectation.id, source_id=source_id, supporting_excerpt=excerpt))
        elif excerpt not in exists.supporting_excerpt:
            exists.supporting_excerpt = f"{exists.supporting_excerpt}; {excerpt}" if exists.supporting_excerpt else excerpt


def _publish_expectation(db: Session, change: ReviewChange, competency_id: int, domain_id: int, level_id: int, industry_id: int | None) -> DomainLevelExpectation:
    snapshot = change.proposed_snapshot
    expectation = db.scalar(select(DomainLevelExpectation).where(
        DomainLevelExpectation.domain_id == domain_id,
        DomainLevelExpectation.career_level_id == level_id,
        DomainLevelExpectation.competency_id == competency_id,
        DomainLevelExpectation.industry_id == industry_id,
    ))
    if expectation is None:
        expectation = DomainLevelExpectation(
            domain_id=domain_id, career_level_id=level_id, competency_id=competency_id, industry_id=industry_id,
            technical_knowledge=snapshot.get("technical_knowledge") or "",
            practical_capability=snapshot.get("practical_capability") or "",
            qualifications=snapshot.get("qualifications") or "",
            tools_technologies=snapshot.get("tools_technologies") or "",
            expectation_description=snapshot.get("expectation_description") or "Pending reviewer description",
            proficiency_level=snapshot.get("proficiency_level") or "proficient",
            importance=snapshot.get("importance") or "important",
            responsibility_type=snapshot.get("responsibility_type") or "execution",
            experience_years_min=snapshot.get("experience_years_min"),
            experience_years_max=snapshot.get("experience_years_max"),
        )
        db.add(expectation)
        db.flush()
    else:
        current = _expectation_snapshot(expectation)
        current["evidence"] = [
            {"source_id": existing_source_id, "supporting_excerpt": excerpt}
            for existing_source_id, excerpt in db.execute(select(ExpectationSource.source_id, ExpectationSource.supporting_excerpt).where(ExpectationSource.expectation_id == expectation.id)).all()
        ]
        version = (db.scalar(select(func.max(ExpectationRevision.version)).where(ExpectationRevision.expectation_id == expectation.id)) or 0) + 1
        db.add(ExpectationRevision(expectation_id=expectation.id, change_id=change.id, version=version, snapshot=current, created_at=now()))
    text_fields = (
        "technical_knowledge", "practical_capability", "qualifications", "tools_technologies",
        "expectation_description", "proficiency_level", "importance", "responsibility_type",
    )
    for field in text_fields:
        value = snapshot.get(field)
        if isinstance(value, str) and value.strip():
            setattr(expectation, field, value.strip())
    for field in ("experience_years_min", "experience_years_max"):
        value = snapshot.get(field)
        if value is not None:
            setattr(expectation, field, value)
    _attach_evidence(db, expectation, change)
    return expectation


def _lock_publication_transaction(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('cybersec:research-publication'))"))


def publish_changes(db: Session, change_ids: list[int] | None, expected_versions: dict[int, int], actor: str) -> tuple[PublicationBatch, list[int], list[int]]:
    _lock_publication_transaction(db)
    changes = _select_changes(db, change_ids, lock=True)
    if not changes:
        raise HTTPException(status_code=409, detail="No approved changes are selected")
    for change in changes:
        if change.status not in APPROVED_STATUSES:
            raise HTTPException(status_code=409, detail=f"Change {change.id} is not approved")
        if expected_versions.get(change.id) != change.version:
            raise HTTPException(status_code=409, detail=f"Change {change.id} changed; refresh the publication preview")
        _validate_snapshot(db, change.proposed_snapshot)
    batch = PublicationBatch(submission_id=changes[0].submission_id if len({item.submission_id for item in changes}) == 1 else None, status="pending", created_by=actor, created_at=now())
    db.add(batch)
    db.flush()
    expectation_ids: list[int] = []
    competency_ids: list[int] = []
    for change in changes:
        snapshot = change.proposed_snapshot
        if change.change_type == "new_competency":
            # A competency with the same name may already exist (published earlier); merge into it instead of duplicating.
            competency = db.scalar(select(Competency).where(func.lower(Competency.name) == snapshot["competency_name"].strip().lower()))
            if competency is None:
                category = db.get(CompetencyCategory, snapshot["category_id"])
                competency = Competency(name=snapshot["competency_name"].strip(), slug=_make_slug_unique(db, snapshot["competency_name"]), description=snapshot.get("competency_description", ""), category_id=category.id)
                db.add(competency)
                db.flush()
            change.target_competency_id = competency.id
            competency_ids.append(competency.id)
        else:
            competency_id = change.merge_target_competency_id or change.target_competency_id
            competency = db.get(Competency, competency_id)
            if competency is None:
                raise HTTPException(status_code=422, detail=f"Change {change.id} has no valid competency target")
            if change.change_type == "merge" and snapshot.get("competency_description") and snapshot["competency_description"] != competency.description:
                competency.description = snapshot["competency_description"]
            competency_ids.append(competency.id)
        for domain_id in snapshot["domain_ids"]:
            expectation = _publish_expectation(db, change, competency.id, domain_id, snapshot["career_level_id"], snapshot.get("industry_id"))
            expectation_ids.append(expectation.id)
        before = deepcopy(change.original_snapshot)
        change.status = "published"
        change.publication_batch_id = batch.id
        _record(change, "published", actor, before, deepcopy(snapshot), "Published in an administrator-confirmed atomic batch.")
    batch.status = "published"
    batch.published_at = now()
    db.commit()
    return batch, expectation_ids, competency_ids
