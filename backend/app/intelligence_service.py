from __future__ import annotations

import hashlib
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .industry_service import expectation_scope_clause, resolve_industry
from .models import (
    CareerLevel,
    Competency,
    CompetencyAssessment,
    CompetencyCategory,
    CompetencyProfile,
    DomainLevelExpectation,
    ExpectationRevision,
    ExpectationSource,
    Industry,
    ResearchSource,
    SecurityDomain,
)
from .phase5_api import model_selection, providers
from .intelligence_schemas import (
    CareerProgressionResponse,
    CompetencyFrequency,
    CompetencyGapResponse,
    DistributionItem,
    EvidenceExplorerResponse,
    EvidenceReference,
    GapItem,
    IndustryComparisonItem,
    IndustryComparisonResponse,
    IntelligenceFilterState,
    IntelligenceRef,
    IntelligenceDashboardResponse,
    HistoricalExpectation,
    HistoricalResponse,
    RoadmapRecommendation,
    CareerRoadmapResponse,
    SkillTrend,
    SkillTrendsResponse,
    TrendPoint,
)

PROFICIENCY_RANK = {"not_familiar": 0, "basic": 1, "intermediate": 2, "advanced": 3, "expert": 4}


@dataclass(frozen=True)
class EvidenceRow:
    expectation: DomainLevelExpectation
    link: ExpectationSource
    source: ResearchSource
    competency: Competency
    category: CompetencyCategory
    domain: SecurityDomain
    level: CareerLevel
    industry: Industry | None


def _ref(item) -> IntelligenceRef:
    return IntelligenceRef(id=item.id, name=item.name, slug=item.slug)


def _normalize_ids(db: Session, *, industry: str | None, domain: str | None, career_level: str | None, category: str | None):
    industry_item = resolve_industry(db, industry) if industry else None
    domain_ids: list[int] | None = None
    domain_item = None
    if domain:
        domains = list(db.scalars(select(SecurityDomain).order_by(SecurityDomain.display_order)).all())
        matches = [item for item in domains if item.slug.casefold() == domain.casefold() or item.name.casefold() == domain.casefold()]
        if not matches:
            raise HTTPException(status_code=404, detail=f"Security domain '{domain}' was not found")
        domain_item = matches[0]
        children = defaultdict(list)
        for item in domains:
            children[item.parent_id].append(item.id)
        domain_ids = []
        pending = [domain_item.id]
        while pending:
            current = pending.pop()
            if current in domain_ids:
                continue
            domain_ids.append(current)
            pending.extend(children[current])
    level_item = None
    if career_level:
        level_item = db.scalar(select(CareerLevel).where(or_(CareerLevel.slug == career_level, func.lower(CareerLevel.name) == career_level.casefold())))
        if level_item is None:
            raise HTTPException(status_code=404, detail=f"Career level '{career_level}' was not found")
    category_item = None
    if category:
        category_item = db.scalar(select(CompetencyCategory).where(or_(CompetencyCategory.slug == category, func.lower(CompetencyCategory.name) == category.casefold())))
        if category_item is None:
            raise HTTPException(status_code=404, detail=f"Competency category '{category}' was not found")
    return industry_item, domain_item, domain_ids, level_item, category_item


def _rows(
    db: Session,
    *,
    industry: str | None = None,
    domain: str | None = None,
    career_level: str | None = None,
    category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[EvidenceRow], tuple[Industry | None, SecurityDomain | None, CareerLevel | None, CompetencyCategory | None]]:
    industry_item, domain_item, domain_ids, level_item, category_item = _normalize_ids(
        db, industry=industry, domain=domain, career_level=career_level, category=category
    )
    query = (
        select(DomainLevelExpectation, ExpectationSource, ResearchSource, Competency, CompetencyCategory, SecurityDomain, CareerLevel, Industry)
        .join(ExpectationSource, ExpectationSource.expectation_id == DomainLevelExpectation.id)
        .join(ResearchSource, ResearchSource.id == ExpectationSource.source_id)
        .join(Competency, Competency.id == DomainLevelExpectation.competency_id)
        .join(CompetencyCategory, CompetencyCategory.id == Competency.category_id)
        .join(SecurityDomain, SecurityDomain.id == DomainLevelExpectation.domain_id)
        .join(CareerLevel, CareerLevel.id == DomainLevelExpectation.career_level_id)
        .outerjoin(Industry, Industry.id == DomainLevelExpectation.industry_id)
    )
    if industry_item:
        query = query.where(expectation_scope_clause(industry_item.id))
    if domain_ids:
        query = query.where(DomainLevelExpectation.domain_id.in_(domain_ids))
    if level_item:
        query = query.where(DomainLevelExpectation.career_level_id == level_item.id)
    if category_item:
        query = query.where(Competency.category_id == category_item.id)
    if date_from:
        query = query.where(ResearchSource.collected_at >= date_from)
    if date_to:
        query = query.where(ResearchSource.collected_at <= date_to)
    result = db.execute(query.order_by(ResearchSource.collected_at.desc(), ResearchSource.id.desc())).all()
    rows = [EvidenceRow(*row) for row in result]
    return rows, (industry_item, domain_item, level_item, category_item)


def _distinct_source_ids(rows: Iterable[EvidenceRow]) -> set[int]:
    return {row.source.id for row in rows}


def _evidence_reference(row: EvidenceRow, revision_versions: dict[int, int] | None = None) -> EvidenceReference:
    return EvidenceReference(
        expectation_id=row.expectation.id,
        source_id=row.source.id,
        source_title=row.source.source_title,
        source_url=row.source.source_url,
        research_date=row.source.collected_at,
        excerpt=row.link.supporting_excerpt,
        publication_version=(revision_versions or {}).get(row.expectation.id, 1),
    )


def _revision_versions(db: Session, expectation_ids: set[int]) -> dict[int, int]:
    if not expectation_ids:
        return {}
    rows = db.execute(select(ExpectationRevision.expectation_id, func.max(ExpectationRevision.version)).where(ExpectationRevision.expectation_id.in_(expectation_ids)).group_by(ExpectationRevision.expectation_id)).all()
    return {expectation_id: int(version) for expectation_id, version in rows}


def _distribution(rows: list[EvidenceRow], attribute: str, denominator: int) -> list[DistributionItem]:
    sources: dict[int, set[int]] = defaultdict(set)
    refs = {}
    for row in rows:
        item = getattr(row, attribute)
        if item is None:
            continue
        refs[item.id] = item
        sources[item.id].add(row.source.id)
    return [DistributionItem(item=_ref(refs[item_id]), source_count=len(source_ids), mention_rate=round(len(source_ids) / denominator * 100, 2) if denominator else None) for item_id, source_ids in sorted(sources.items(), key=lambda value: (-len(value[1]), refs[value[0]].name))]


def _group_rows(rows: list[EvidenceRow]) -> dict[int, list[EvidenceRow]]:
    grouped: dict[int, list[EvidenceRow]] = defaultdict(list)
    for row in rows:
        grouped[row.competency.id].append(row)
    return grouped


def _unique_competency_source_rows(rows: list[EvidenceRow]) -> list[EvidenceRow]:
    seen: set[tuple[int, int]] = set()
    result = []
    for row in rows:
        key = (row.competency.id, row.source.id)
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def dashboard(
    db: Session,
    *,
    industry: str | None = None,
    domain: str | None = None,
    career_level: str | None = None,
    category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: str = "frequency",
    limit: int = 100,
) -> IntelligenceDashboardResponse:
    rows, (industry_item, domain_item, level_item, category_item) = _rows(db, industry=industry, domain=domain, career_level=career_level, category=category, date_from=date_from, date_to=date_to)
    relevant_sources = _distinct_source_ids(rows)
    denominator = len(relevant_sources)
    grouped = _group_rows(rows)
    versions = _revision_versions(db, {row.expectation.id for row in rows})
    frequencies: list[CompetencyFrequency] = []
    for competency_id, competency_rows in grouped.items():
        unique_rows = _unique_competency_source_rows(competency_rows)
        source_ids = {row.source.id for row in unique_rows}
        evidence_seen: set[tuple[int, int]] = set()
        evidence = []
        for row in competency_rows:
            key = (row.expectation.id, row.source.id)
            if key not in evidence_seen:
                evidence_seen.add(key)
                evidence.append(_evidence_reference(row, versions))
        frequencies.append(CompetencyFrequency(
            competency=_ref(unique_rows[0].competency), category=_ref(unique_rows[0].category), source_count=len(source_ids),
            relevant_source_count=denominator, mention_rate=round(len(source_ids) / denominator * 100, 2) if denominator else None,
            latest_research_date=max((row.source.collected_at for row in unique_rows), default=None),
            industry_distribution=_distribution(unique_rows, "industry", denominator),
            domain_distribution=_distribution(unique_rows, "domain", denominator),
            career_level_distribution=_distribution(unique_rows, "level", denominator), evidence=evidence[:25],
        ))
    if sort_by == "recency":
        frequencies.sort(key=lambda item: item.latest_research_date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif sort_by == "category":
        frequencies.sort(key=lambda item: (item.category.name.casefold(), item.competency.name.casefold()))
    else:
        frequencies.sort(key=lambda item: (item.source_count, item.competency.name.casefold()), reverse=True)
    data_quality = ["Frequency is the percentage of distinct relevant research sources mentioning the competency; repeated mentions within one source count once.", "Frequency is descriptive evidence coverage, not competency importance or market-wide demand."]
    if not rows:
        data_quality.append("No published research evidence matches these filters. Source-less illustrative seed expectations are excluded.")
    elif denominator < 3:
        data_quality.append(f"Limited evidence: only {denominator} distinct published research source(s) match these filters.")
    coverage_label = "adequate" if denominator >= 3 and len(grouped) >= 3 else "limited" if denominator else "none"
    return IntelligenceDashboardResponse(
        filters=IntelligenceFilterState(industry=_ref(industry_item) if industry_item else None, domain=_ref(domain_item) if domain_item else None, career_level=_ref(level_item) if level_item else None, category=_ref(category_item) if category_item else None, date_from=date_from, date_to=date_to),
        relevant_source_count=denominator, distinct_competency_count=len(grouped), evidence_count=len(rows),
        research_date_min=min((row.source.collected_at for row in rows), default=None), research_date_max=max((row.source.collected_at for row in rows), default=None),
        coverage={"label": coverage_label, "source_count": denominator, "competency_count": len(grouped), "sufficient": denominator >= 3},
        competency_frequency=frequencies[:limit], data_quality=data_quality,
    )


def _expectation_payload(row: EvidenceRow) -> dict:
    item = row.expectation
    return {"id": item.id, "domain": _ref(row.domain).model_dump(), "career_level": _ref(row.level).model_dump(), "description": item.expectation_description, "technical_knowledge": item.technical_knowledge, "practical_capability": item.practical_capability, "qualifications": item.qualifications, "tools_technologies": item.tools_technologies, "proficiency_level": item.proficiency_level, "importance": item.importance, "responsibility_type": item.responsibility_type, "experience_years_min": item.experience_years_min, "experience_years_max": item.experience_years_max}


def _progression_bucket(db: Session, rows: list[EvidenceRow], versions: dict[int, int]) -> list:
    buckets: dict[int, list[EvidenceRow]] = defaultdict(list)
    for row in rows:
        buckets[row.competency.id].append(row)
    output = []
    for item_rows in buckets.values():
        unique_expectations = {row.expectation.id: row for row in item_rows}
        evidence = []
        seen = set()
        for row in item_rows:
            key = (row.expectation.id, row.source.id)
            if key not in seen:
                seen.add(key)
                evidence.append(_evidence_reference(row, versions))
        first = item_rows[0]
        output.append({"competency": _ref(first.competency), "category": _ref(first.category), "expectations": [_expectation_payload(row) for row in unique_expectations.values()], "supporting_evidence": evidence})
    return output


def progression(db: Session, *, industry: str | None, domain: str, starting_level: str, target_level: str) -> CareerProgressionResponse:
    industry_item, domain_item, domain_ids, start_item, _ = _normalize_ids(db, industry=industry, domain=domain, career_level=starting_level, category=None)
    _, _, _, target_item, _ = _normalize_ids(db, industry=industry, domain=None, career_level=target_level, category=None)
    rows, _ = _rows(db, industry=industry, domain=domain, date_from=None, date_to=None)
    rows = [row for row in rows if row.level.id in {start_item.id, target_item.id}]
    by_level = {start_item.id: [], target_item.id: []}
    for row in rows:
        by_level[row.level.id].append(row)
    start_ids = {row.competency.id for row in by_level[start_item.id]}
    target_ids = {row.competency.id for row in by_level[target_item.id]}
    versions = _revision_versions(db, {row.expectation.id for row in rows})
    shared_ids = start_ids & target_ids
    shared = _progression_bucket(db, [row for row in rows if row.competency.id in shared_ids], versions)
    starting = _progression_bucket(db, [row for row in by_level[start_item.id] if row.competency.id not in target_ids], versions)
    starting_signatures = defaultdict(set)
    for row in by_level[start_item.id]:
        starting_signatures[row.competency.id].add((row.expectation.expectation_description, row.expectation.proficiency_level, row.expectation.responsibility_type))
    changed_target_ids = {
        row.competency.id for row in by_level[target_item.id]
        if row.competency.id in shared_ids and (row.expectation.expectation_description, row.expectation.proficiency_level, row.expectation.responsibility_type) not in starting_signatures[row.competency.id]
    }
    additional = _progression_bucket(db, [row for row in by_level[target_item.id] if row.competency.id not in start_ids or row.competency.id in changed_target_ids], versions)
    responsibilities = sorted({f"{start_item.name}: {row.expectation.responsibility_type} → {target_item.name}: {target_row.expectation.responsibility_type}" for row in by_level[start_item.id] for target_row in by_level[target_item.id] if row.competency.id == target_row.competency.id and row.expectation.responsibility_type != target_row.expectation.responsibility_type})
    warnings = ["Missing evidence is not evidence that a competency is absent.", "Career levels are compared as selected; the platform does not assume a single linear hierarchy."]
    if start_item.career_track != target_item.career_track and "shared" not in {start_item.career_track, target_item.career_track}:
        warnings.append("The selected levels belong to different technical and management tracks; interpret differences cautiously.")
    source_count = len(_distinct_source_ids(rows))
    if source_count < 3:
        warnings.append(f"Only {source_count} distinct published source(s) support this comparison.")
    return CareerProgressionResponse(industry=_ref(industry_item) if industry_item else None, domain=_ref(domain_item), starting_level=_ref(start_item), target_level=_ref(target_item), technical_track=f"{start_item.career_track} → {target_item.career_track}", shared_expectations=shared, starting_only_expectations=starting, target_additional_expectations=additional, responsibility_changes=responsibilities, evidence_source_count=source_count, warnings=warnings)


def industry_comparison(db: Session, *, domain: str, career_level: str, industries: list[str]) -> IndustryComparisonResponse:
    if len(industries) < 2 or len(industries) > 6:
        raise HTTPException(status_code=422, detail="Select between two and six industries")
    _, domain_item, _, level_item, _ = _normalize_ids(db, industry=None, domain=domain, career_level=career_level, category=None)
    industry_items = [resolve_industry(db, value) for value in industries]
    rows, _ = _rows(db, domain=domain, career_level=career_level)
    versions = _revision_versions(db, {row.expectation.id for row in rows})
    by_industry: dict[int, list[EvidenceRow]] = {}
    coverage: dict[str, int] = {}
    for industry_item in industry_items:
        matching = [row for row in rows if row.industry is None or row.industry.id == industry_item.id]
        by_industry[industry_item.id] = _unique_competency_source_rows(matching)
        coverage[industry_item.slug] = len(_distinct_source_ids(matching))
    competency_ids = set().union(*({row.competency.id for row in item_rows} for item_rows in by_industry.values())) if by_industry else set()
    shared: list[IndustryComparisonItem] = []
    specific: dict[str, list[IndustryComparisonItem]] = {item.slug: [] for item in industry_items}
    for competency_id in sorted(competency_ids):
        first = next(row for item_rows in by_industry.values() for row in item_rows if row.competency.id == competency_id)
        counts = {item.slug: len({row.source.id for row in by_industry[item.id] if row.competency.id == competency_id}) for item in industry_items}
        rates = {item.slug: round(counts[item.slug] / coverage[item.slug] * 100, 2) if coverage[item.slug] else None for item in industry_items}
        evidence = [_evidence_reference(row, versions) for item_rows in by_industry.values() for row in item_rows if row.competency.id == competency_id][:25]
        card = IndustryComparisonItem(competency=_ref(first.competency), category=_ref(first.category), industry_source_counts=counts, industry_mention_rates=rates, shared=all(counts[item.slug] > 0 for item in industry_items), evidence=evidence)
        if card.shared:
            shared.append(card)
        else:
            for item in industry_items:
                if counts[item.slug] > 0:
                    specific[item.slug].append(card)
    warnings = ["Generic cross-industry expectations are included for each selected industry.", "Missing evidence is not evidence of absence; coverage varies by industry and source availability."]
    if min(coverage.values(), default=0) < 3:
        warnings.append("At least one selected industry has fewer than three distinct published sources.")
    return IndustryComparisonResponse(domain=_ref(domain_item), career_level=_ref(level_item), industries=[_ref(item) for item in industry_items], shared_competencies=shared, industry_specific_competencies=specific, coverage=coverage, warnings=warnings)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _period_start(value: datetime, window: str) -> datetime:
    value = _utc(value)
    if window == "quarterly":
        return datetime(value.year, ((value.month - 1) // 3) * 3 + 1, 1, tzinfo=timezone.utc)
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def trends(db: Session, *, window: str, industry: str | None, domain: str | None, career_level: str | None, date_from: datetime | None, date_to: datetime | None, minimum_sample_size: int, minimum_coverage: int) -> SkillTrendsResponse:
    rows, _ = _rows(db, industry=industry, domain=domain, career_level=career_level, date_from=date_from, date_to=date_to)
    unique_rows = []
    seen = set()
    for row in rows:
        key = (row.competency.id, row.source.id)
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)
    source_dates = {row.source.id: _utc(row.source.collected_at) for row in unique_rows}
    if not source_dates:
        return SkillTrendsResponse(window=window, minimum_sample_size=minimum_sample_size, minimum_coverage=minimum_coverage, relevant_source_count=0, trends=[], data_quality=["No published research evidence matches these filters."])
    periods = sorted({_period_start(value, "quarterly" if window == "quarterly" else "monthly") for value in source_dates.values()})
    if window.startswith("rolling"):
        months = 6 if window == "rolling_6m" else 12
        periods = sorted({_period_start(value, "monthly") for value in source_dates.values()})
    grouped = _group_rows(unique_rows)
    output = []
    for competency_id, competency_rows in grouped.items():
        first = competency_rows[0]
        points = []
        for period in periods:
            if window.startswith("rolling"):
                months = 6 if window == "rolling_6m" else 12
                start = period - timedelta(days=months * 31)
                period_rows = [row for row in unique_rows if row.competency.id == competency_id and start <= _utc(row.source.collected_at) < period + timedelta(days=32)]
                relevant_period_sources = {row.source.id for row in unique_rows if start <= _utc(row.source.collected_at) < period + timedelta(days=32)}
            else:
                next_period = (period.replace(day=28) + timedelta(days=4)).replace(day=1) if window != "quarterly" else (period + timedelta(days=92)).replace(day=1)
                period_rows = [row for row in competency_rows if period <= _utc(row.source.collected_at) < next_period]
                relevant_period_sources = {row.source.id for row in unique_rows if period <= _utc(row.source.collected_at) < next_period}
            period_label = f"{period.year}-Q{(period.month - 1) // 3 + 1}" if window == "quarterly" else period.strftime("%Y-%m")
            points.append(TrendPoint(period=period_label, period_start=period, relevant_source_count=len(relevant_period_sources), source_mention_count=len({row.source.id for row in period_rows}), normalized_mention_rate=round(len({row.source.id for row in period_rows}) / len(relevant_period_sources) * 100, 2) if relevant_period_sources else None, competency_count=1 if period_rows else 0))
        sample_size = len({row.source.id for row in competency_rows})
        coverage = len({row.source.id for row in unique_rows})
        if sample_size < minimum_sample_size or coverage < minimum_coverage:
            direction = "insufficient_data"
            warning = f"Requires at least {minimum_sample_size} source mentions and {minimum_coverage} relevant sources."
        else:
            values = [point.normalized_mention_rate for point in points if point.normalized_mention_rate is not None]
            delta = values[-1] - values[0] if len(values) >= 2 else 0
            direction = "emerging" if delta >= 20 else "increasing" if delta >= 5 else "decreasing" if delta <= -5 else "stable"
            warning = None
        output.append(SkillTrend(competency=_ref(first.competency), category=_ref(first.category), points=points, direction=direction, sample_size=sample_size, coverage_source_count=coverage, warning=warning))
    output.sort(key=lambda item: (item.direction == "insufficient_data", item.competency.name.casefold()))
    return SkillTrendsResponse(window=window, minimum_sample_size=minimum_sample_size, minimum_coverage=minimum_coverage, relevant_source_count=len(source_dates), trends=output, data_quality=["Trend rates are normalized by distinct sources in each period, not total mentions.", "Trends are descriptive of this evidence set and are not representative of the broader market."])


def evidence(db: Session, *, competency_id: int | None, industry: str | None, domain: str | None, career_level: str | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> EvidenceExplorerResponse:
    rows, _ = _rows(db, industry=industry, domain=domain, career_level=career_level, date_from=date_from, date_to=date_to)
    competency_item = None
    if competency_id:
        rows = [row for row in rows if row.competency.id == competency_id]
        competency_item = db.get(Competency, competency_id)
        if competency_item is None:
            raise HTTPException(status_code=404, detail="Competency was not found")
    versions = _revision_versions(db, {row.expectation.id for row in rows})
    refs = []
    seen = set()
    for row in rows:
        key = (row.expectation.id, row.source.id)
        if key not in seen:
            seen.add(key)
            refs.append(_evidence_reference(row, versions))
    return EvidenceExplorerResponse(competency=_ref(competency_item) if competency_item else None, evidence=refs[:limit], total=len(refs), data_quality=["Only administrator-published expectation evidence is shown.", "Source excerpts are retained evidence; they are not AI-generated citations."] + (["No published evidence matches these filters."] if not refs else []))


def historical(db: Session, *, competency_id: int | None, domain: str | None, career_level: str | None, industry: str | None, limit: int) -> HistoricalResponse:
    query = select(ExpectationRevision, DomainLevelExpectation, Competency, SecurityDomain, CareerLevel, Industry).join(DomainLevelExpectation, DomainLevelExpectation.id == ExpectationRevision.expectation_id).join(Competency, Competency.id == DomainLevelExpectation.competency_id).join(SecurityDomain, SecurityDomain.id == DomainLevelExpectation.domain_id).join(CareerLevel, CareerLevel.id == DomainLevelExpectation.career_level_id).outerjoin(Industry, Industry.id == DomainLevelExpectation.industry_id)
    if competency_id:
        query = query.where(DomainLevelExpectation.competency_id == competency_id)
    if domain:
        _, _, ids, _, _ = _normalize_ids(db, industry=None, domain=domain, career_level=None, category=None)
        query = query.where(DomainLevelExpectation.domain_id.in_(ids or []))
    if career_level:
        _, _, _, level, _ = _normalize_ids(db, industry=None, domain=None, career_level=career_level, category=None)
        query = query.where(DomainLevelExpectation.career_level_id == level.id)
    if industry:
        selected = resolve_industry(db, industry)
        query = query.where(expectation_scope_clause(selected.id))
    result = db.execute(query.order_by(ExpectationRevision.created_at.desc()).limit(limit)).all()
    if not result:
        return HistoricalResponse(available=False, expectations=[], warnings=["Historical revisions are not available for the selected evidence. Current expectations are not used as invented historical snapshots."])
    outputs = []
    for revision, expectation, competency, domain_item, level, industry_item in result:
        current_rows, _ = _rows(db, domain=domain_item.slug, career_level=level.slug, industry=industry_item.slug if industry_item else None)
        refs = [_evidence_reference(row) for row in current_rows if row.expectation.id == expectation.id][:10]
        outputs.append(HistoricalExpectation(expectation_id=expectation.id, competency=_ref(competency), domain=_ref(domain_item), career_level=_ref(level), industry=_ref(industry_item) if industry_item else None, version=revision.version, recorded_at=revision.created_at, snapshot=revision.snapshot, evidence=refs))
    return HistoricalResponse(available=True, expectations=outputs, warnings=["Historical records represent explicit published revisions only; evidence links shown are current associations and may have changed."])


def _profile_key_hash(profile_key: str) -> str:
    return hashlib.sha256(profile_key.encode("utf-8")).hexdigest()


def new_profile(db: Session, *, target_industry_id: int | None, target_domain_id: int | None, target_career_level_id: int | None) -> tuple[CompetencyProfile, str]:
    profile_key = secrets.token_urlsafe(32)
    profile = CompetencyProfile(profile_token_hash=_profile_key_hash(profile_key), target_industry_id=target_industry_id, target_domain_id=target_domain_id, target_career_level_id=target_career_level_id)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile, profile_key


def get_profile(db: Session, profile_key: str) -> CompetencyProfile:
    if not profile_key or len(profile_key) > 200:
        raise HTTPException(status_code=401, detail="A valid private profile key is required")
    profile = db.scalar(select(CompetencyProfile).where(CompetencyProfile.profile_token_hash == _profile_key_hash(profile_key)))
    if profile is None:
        raise HTTPException(status_code=401, detail="A valid private profile key is required")
    return profile


def profile_response(profile: CompetencyProfile) -> dict:
    return {"profile_id": profile.id, "target_industry": _ref(profile.target_industry) if profile.target_industry else None, "target_domain": _ref(profile.target_domain) if profile.target_domain else None, "target_career_level": _ref(profile.target_career_level) if profile.target_career_level else None, "assessments": [{"competency_id": item.competency_id, "competency": _ref(item.competency), "proficiency": item.proficiency, "updated_at": item.updated_at} for item in profile.assessments], "updated_at": profile.updated_at}


def save_assessments(db: Session, profile: CompetencyProfile, assessments: list[dict]) -> CompetencyProfile:
    for item in assessments:
        if db.get(Competency, item["competency_id"]) is None:
            raise HTTPException(status_code=404, detail=f"Competency {item['competency_id']} was not found")
        existing = db.scalar(select(CompetencyAssessment).where(CompetencyAssessment.profile_id == profile.id, CompetencyAssessment.competency_id == item["competency_id"]))
        if existing is None:
            existing = CompetencyAssessment(profile_id=profile.id, competency_id=item["competency_id"])
            db.add(existing)
        existing.proficiency = item["proficiency"]
    db.commit()
    return db.scalar(select(CompetencyProfile).where(CompetencyProfile.id == profile.id))


def gap_analysis(db: Session, profile: CompetencyProfile) -> CompetencyGapResponse:
    industry = profile.target_industry.slug if profile.target_industry else None
    domain = profile.target_domain.slug if profile.target_domain else None
    level = profile.target_career_level.slug if profile.target_career_level else None
    rows, (industry_item, domain_item, level_item, _) = _rows(db, industry=industry, domain=domain, career_level=level)
    grouped = _group_rows(rows)
    assessments = {item.competency_id: item.proficiency for item in profile.assessments}
    versions = _revision_versions(db, {row.expectation.id for row in rows})
    matching, development, unassessed = [], [], []
    for competency_id, item_rows in grouped.items():
        first = item_rows[0]
        expected = sorted({row.expectation.proficiency_level for row in item_rows}, key=lambda value: PROFICIENCY_RANK.get(value, 0), reverse=True)
        source_count = len({row.source.id for row in item_rows})
        refs = [_evidence_reference(row, versions) for row in item_rows][:10]
        self_level = assessments.get(competency_id)
        if self_level is None:
            kind = "unassessed"
        elif PROFICIENCY_RANK.get(self_level, 0) >= max((PROFICIENCY_RANK.get(value, 0) for value in expected), default=0):
            kind = "match"
        else:
            kind = "development_area"
        item = GapItem(competency=_ref(first.competency), category=_ref(first.category), self_assessment=self_level, expected_proficiency=expected, expectation_count=len({row.expectation.id for row in item_rows}), evidence_source_count=source_count, gap_type=kind, evidence=refs)
        {"match": matching, "development_area": development, "unassessed": unassessed}[kind].append(item)
    warnings = ["An unassessed competency is not treated as a missing skill.", "Gap results are limited to published expectations with source evidence."]
    if not rows:
        warnings.append("No published expectations match this target; no development gap is inferred.")
    return CompetencyGapResponse(target=IntelligenceFilterState(industry=_ref(industry_item) if industry_item else None, domain=_ref(domain_item) if domain_item else None, career_level=_ref(level_item) if level_item else None), assessed_competency_count=len(assessments), expected_competency_count=len(grouped), matching=matching, development_areas=development, unassessed=unassessed, warnings=warnings)


def roadmap(db: Session, profile: CompetencyProfile) -> CareerRoadmapResponse:
    gap = gap_analysis(db, profile)
    recommendations = []
    section_by_category = {"technical-knowledge": "Foundational Knowledge", "technical-skills": "Technical Skills", "tools-technologies": "Technical Skills", "security-architecture": "Security Architecture", "security-testing": "Practical Experience", "security-standards": "Standards and Regulations", "leadership": "Leadership and Responsibilities", "responsibilities": "Leadership and Responsibilities"}
    for item in [*gap.development_areas, *gap.unassessed]:
        evidence = item.evidence[:3]
        expectation = evidence[0].excerpt if evidence else None
        section = section_by_category.get(item.category.slug, "Practical Experience")
        recommendations.append(RoadmapRecommendation(section=section, competency=item.competency, why_it_matters=f"Published research connects {item.competency.name} with the selected target.", published_expectation=expectation, knowledge_to_develop=f"Build toward the published {', '.join(item.expected_proficiency)} expectation for {item.competency.name}.", practical_activity=f"Create a bounded, reviewable exercise demonstrating {item.competency.name}; adapt it to the target domain and industry.", evidence=evidence, ai_generated=False))
    if not recommendations:
        gap.warnings.append("No evidence-backed development recommendations can be generated for this profile yet.")
    return CareerRoadmapResponse(target=gap.target, recommendations=recommendations[:50], warnings=gap.warnings)


def retrieve_for_question(db: Session, *, question: str, industry: str | None, domain: str | None, career_level: str | None, limit: int = 8) -> list[EvidenceRow]:
    rows, _ = _rows(db, industry=industry, domain=domain, career_level=career_level)
    terms = [term for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9-]{2,}", question.casefold()) if term not in {"what", "how", "does", "with", "from", "skills", "expected", "compare", "between", "career"}]
    scored = []
    for row in rows:
        haystack = " ".join((row.competency.name, row.competency.description, row.expectation.expectation_description, row.expectation.technical_knowledge, row.expectation.practical_capability, row.domain.name, row.level.name, row.industry.name if row.industry else "")).casefold()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda value: (-value[0], -value[1].source.collected_at.timestamp()))
    output, seen = [], set()
    for _, row in scored:
        key = (row.expectation.id, row.source.id)
        if key not in seen:
            seen.add(key)
            output.append(row)
        if len(output) >= limit:
            break
    return output
