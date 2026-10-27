from collections import defaultdict
from math import ceil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .database import get_db
from .knowledge_schemas import ExpectationResponse
from .models import (
    CareerLevel,
    Competency,
    CompetencyCategory,
    CompetencyRelationship,
    DomainLevelExpectation,
    ExpectationSource,
    ResearchSource,
    SecurityDomain,
)
from .read_schemas import (
    CareerComparisonResponse,
    CareerMatrixResponse,
    CategoryRead,
    ComparisonCompetency,
    ComparisonLevel,
    CompetencyDetail,
    CompetencyListItem,
    CompetencyPage,
    DomainRead,
    DomainRef,
    ExpectationPage,
    ExpectationRead,
    ExpectationSourceRead,
    ExpectationSummary,
    LevelRead,
    MatrixCell,
    MatrixDomain,
    PageMeta,
    ResearchSourcePage,
    ResearchSourceRead,
    SearchPage,
    SearchResult,
)

router = APIRouter()


def not_found(resource: str, identifier: str | int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} '{identifier}' was not found")


def page_meta(page: int, page_size: int, total: int) -> PageMeta:
    return PageMeta(page=page, page_size=page_size, total=total, pages=ceil(total / page_size) if total else 0)


def page_slice(query, page: int, page_size: int):
    return query.offset((page - 1) * page_size).limit(page_size)


def ref_domain(item: SecurityDomain) -> DomainRef:
    return DomainRef(id=item.id, name=item.name, slug=item.slug)


def ref_level(item: CareerLevel) -> LevelRead:
    return LevelRead.model_validate(item)


def ref_level_short(item: CareerLevel) -> dict[str, Any]:
    return {"id": item.id, "name": item.name, "slug": item.slug, "career_track": item.career_track}


def category_ref(item: CompetencyCategory) -> dict[str, Any]:
    return {"id": item.id, "name": item.name, "slug": item.slug}


def domain_tree(items: list[SecurityDomain], selected_id: int | None = None) -> list[DomainRead]:
    by_parent: dict[int | None, list[SecurityDomain]] = defaultdict(list)
    for item in items:
        by_parent[item.parent_id].append(item)

    def build(item: SecurityDomain) -> DomainRead:
        return DomainRead(
            id=item.id,
            name=item.name,
            slug=item.slug,
            description=item.description,
            parent_id=item.parent_id,
            display_order=item.display_order,
            created_at=item.created_at,
            updated_at=item.updated_at,
            children=[build(child) for child in sorted(by_parent[item.id], key=lambda value: (value.display_order, value.name))],
        )

    roots = sorted(by_parent[None], key=lambda value: (value.display_order, value.name))
    return [build(item) for item in roots] if selected_id is None else [build(item) for item in items if item.id == selected_id]


def competency_options(detail: bool = False):
    options = [
        selectinload(Competency.category),
        selectinload(Competency.expectations).selectinload(DomainLevelExpectation.domain),
        selectinload(Competency.expectations).selectinload(DomainLevelExpectation.career_level),
        selectinload(Competency.source_relationships).selectinload(CompetencyRelationship.target_competency),
        selectinload(Competency.target_relationships).selectinload(CompetencyRelationship.source_competency),
    ]
    return options


def expectation_options():
    return (
        selectinload(DomainLevelExpectation.domain),
        selectinload(DomainLevelExpectation.career_level),
        selectinload(DomainLevelExpectation.competency).selectinload(Competency.category),
        selectinload(DomainLevelExpectation.competency).selectinload(Competency.expectations).selectinload(DomainLevelExpectation.domain),
        selectinload(DomainLevelExpectation.competency).selectinload(Competency.expectations).selectinload(DomainLevelExpectation.career_level),
        selectinload(DomainLevelExpectation.sources).selectinload(ExpectationSource.source),
        selectinload(DomainLevelExpectation.sources).selectinload(ExpectationSource.source).selectinload(ResearchSource.expectations),
    )


def competency_item(item: Competency) -> CompetencyListItem:
    domains = {expectation.domain.id: expectation.domain for expectation in item.expectations}
    levels = {expectation.career_level.id: expectation.career_level for expectation in item.expectations}
    return CompetencyListItem(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        category=category_ref(item.category),
        domains=[ref_domain(domain) for domain in sorted(domains.values(), key=lambda value: (value.display_order, value.name))],
        career_levels=[ref_level_short(level) for level in sorted(levels.values(), key=lambda value: value.display_order)],
    )


def expectation_summary(item: DomainLevelExpectation) -> ExpectationSummary:
    return ExpectationSummary(
        id=item.id,
        domain=ref_domain(item.domain),
        career_level=ref_level_short(item.career_level),
        technical_knowledge=item.technical_knowledge,
        practical_capability=item.practical_capability,
        qualifications=item.qualifications,
        tools_technologies=item.tools_technologies,
        expectation_description=item.expectation_description,
        proficiency_level=item.proficiency_level,
        importance=item.importance,
        responsibility_type=item.responsibility_type,
        experience_years_min=item.experience_years_min,
        experience_years_max=item.experience_years_max,
    )


def source_read(item: ResearchSource) -> ResearchSourceRead:
    return ResearchSourceRead(
        id=item.id,
        source_type=item.source_type,
        source_url=item.source_url,
        source_title=item.source_title,
        collected_at=item.collected_at,
        notes=item.notes,
        expectation_ids=sorted(link.expectation_id for link in item.expectations),
    )


def expectation_read(item: DomainLevelExpectation) -> ExpectationRead:
    sources = [
        ExpectationSourceRead(source=source_read(link.source), supporting_excerpt=link.supporting_excerpt)
        for link in item.sources
    ]
    return ExpectationRead(
        id=item.id,
        domain=ref_domain(item.domain),
        career_level=ref_level_short(item.career_level),
        competency=competency_item(item.competency),
        technical_knowledge=item.technical_knowledge,
        practical_capability=item.practical_capability,
        qualifications=item.qualifications,
        tools_technologies=item.tools_technologies,
        expectation_description=item.expectation_description,
        proficiency_level=item.proficiency_level,
        importance=item.importance,
        responsibility_type=item.responsibility_type,
        experience_years_min=item.experience_years_min,
        experience_years_max=item.experience_years_max,
        created_at=item.created_at,
        updated_at=item.updated_at,
        supporting_sources=sources,
    )


def matches(value: str, requested: str) -> bool:
    return value.casefold() == requested.casefold()


def domain_filter(column, requested: str):
    return or_(column.slug == requested, func.lower(column.name) == requested.casefold())


@router.get("/domains", response_model=list[DomainRead], tags=["domains"])
def list_domains(db: Session = Depends(get_db)) -> list[DomainRead]:
    items = list(db.scalars(select(SecurityDomain).order_by(SecurityDomain.display_order, SecurityDomain.name)).all())
    return domain_tree(items)


@router.get("/domains/{domain_id}", response_model=DomainRead, tags=["domains"])
def get_domain(domain_id: int, db: Session = Depends(get_db)) -> DomainRead:
    items = list(db.scalars(select(SecurityDomain).order_by(SecurityDomain.display_order, SecurityDomain.name)).all())
    if not any(item.id == domain_id for item in items):
        raise not_found("Security domain", domain_id)
    return domain_tree(items, selected_id=domain_id)[0]


@router.get("/levels", response_model=list[LevelRead], tags=["career-levels"])
def list_levels(db: Session = Depends(get_db)) -> list[LevelRead]:
    return [LevelRead.model_validate(item) for item in db.scalars(select(CareerLevel).order_by(CareerLevel.display_order)).all()]


def descendant_domain_ids(db: Session, requested: str) -> list[int]:
    domains = list(db.scalars(select(SecurityDomain)).all())
    matches_for_request = [item for item in domains if matches(item.slug, requested) or matches(item.name, requested)]
    if not matches_for_request:
        return []
    children_by_parent: dict[int | None, list[int]] = defaultdict(list)
    for item in domains:
        children_by_parent[item.parent_id].append(item.id)
    result: set[int] = set()
    pending = [item.id for item in matches_for_request]
    while pending:
        item_id = pending.pop()
        if item_id in result:
            continue
        result.add(item_id)
        pending.extend(children_by_parent[item_id])
    return sorted(result)


@router.get("/categories", response_model=list[CategoryRead], tags=["categories"])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryRead]:
    return [CategoryRead.model_validate(item) for item in db.scalars(select(CompetencyCategory).order_by(CompetencyCategory.name)).all()]


@router.get("/competencies", response_model=CompetencyPage, tags=["competencies"])
def list_competencies(
    category: str | None = Query(default=None, min_length=1, max_length=120),
    domain: str | None = Query(default=None, min_length=1, max_length=160),
    level: str | None = Query(default=None, min_length=1, max_length=80),
    search: str | None = Query(default=None, min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CompetencyPage:
    query = select(Competency).options(*competency_options())
    if category:
        query = query.where(Competency.category.has(or_(CompetencyCategory.slug == category, func.lower(CompetencyCategory.name) == category.casefold())))
    if domain:
        domain_ids = descendant_domain_ids(db, domain)
        query = query.where(Competency.expectations.any(DomainLevelExpectation.domain_id.in_(domain_ids)))
    if level:
        query = query.where(Competency.expectations.any(DomainLevelExpectation.career_level.has(
            or_(CareerLevel.slug == level, func.lower(CareerLevel.name) == level.casefold())
        )))
    if search:
        term = f"%{search}%"
        query = query.where(or_(Competency.name.ilike(term), Competency.description.ilike(term)))
    query = query.distinct().order_by(Competency.name)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = [competency_item(item) for item in db.scalars(page_slice(query, page, page_size)).unique().all()]
    return CompetencyPage(items=items, meta=page_meta(page, page_size, total))


@router.get("/competencies/{competency_id}", response_model=CompetencyDetail, tags=["competencies"])
def get_competency(competency_id: int, db: Session = Depends(get_db)) -> CompetencyDetail:
    query = select(Competency).where(Competency.id == competency_id).options(*competency_options(detail=True))
    item = db.scalar(query)
    if item is None:
        raise not_found("Competency", competency_id)
    related = [
        RelationshipRead(id=link.id, relationship_type=link.relationship_type, direction="outgoing", competency_id=link.target_competency.id, competency_name=link.target_competency.name, competency_slug=link.target_competency.slug)
        for link in item.source_relationships
    ] + [
        RelationshipRead(id=link.id, relationship_type=link.relationship_type, direction="incoming", competency_id=link.source_competency.id, competency_name=link.source_competency.name, competency_slug=link.source_competency.slug)
        for link in item.target_relationships
    ]
    return CompetencyDetail(
        **competency_item(item).model_dump(),
        created_at=item.created_at,
        updated_at=item.updated_at,
        related_competencies=related,
        expectations=[expectation_summary(expectation) for expectation in sorted(item.expectations, key=lambda value: value.id)],
    )


@router.get("/expectations", response_model=ExpectationPage | list[ExpectationResponse], tags=["expectations"])
def list_expectations(
    domain: str | None = Query(default=None, min_length=1, max_length=160),
    level: str | None = Query(default=None, min_length=1, max_length=80),
    domain_id: int | None = Query(default=None, ge=1),
    career_level_id: int | None = Query(default=None, ge=1),
    category: str | None = Query(default=None, min_length=1, max_length=120),
    importance: str | None = Query(default=None, min_length=1, max_length=40),
    proficiency: str | None = Query(default=None, min_length=1, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ExpectationPage | list[ExpectationResponse]:
    legacy_id_filter = (domain_id is not None or career_level_id is not None) and not any((domain, level, category, importance, proficiency)) and page == 1 and page_size == 25
    if legacy_id_filter:
        legacy_query = select(DomainLevelExpectation).options(
            selectinload(DomainLevelExpectation.domain),
            selectinload(DomainLevelExpectation.career_level),
            selectinload(DomainLevelExpectation.competency),
            selectinload(DomainLevelExpectation.sources),
        )
        if domain_id is not None:
            legacy_query = legacy_query.where(DomainLevelExpectation.domain_id == domain_id)
        if career_level_id is not None:
            legacy_query = legacy_query.where(DomainLevelExpectation.career_level_id == career_level_id)
        return [
            ExpectationResponse(
                id=item.id,
                domain_id=item.domain_id,
                career_level_id=item.career_level_id,
                competency_id=item.competency_id,
                expectation_description=item.expectation_description,
                proficiency_level=item.proficiency_level,
                importance=item.importance,
                responsibility_type=item.responsibility_type,
                experience_years_min=item.experience_years_min,
                experience_years_max=item.experience_years_max,
                domain_name=item.domain.name,
                career_level_name=item.career_level.name,
                competency_name=item.competency.name,
                source_count=len(item.sources),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in db.scalars(legacy_query.order_by(DomainLevelExpectation.id)).all()
        ]

    query = select(DomainLevelExpectation).join(DomainLevelExpectation.domain).join(DomainLevelExpectation.career_level).join(DomainLevelExpectation.competency).join(Competency.category).options(*expectation_options())
    if domain_id is not None:
        query = query.where(DomainLevelExpectation.domain_id == domain_id)
    if career_level_id is not None:
        query = query.where(DomainLevelExpectation.career_level_id == career_level_id)
    if domain:
        query = query.where(DomainLevelExpectation.domain_id.in_(descendant_domain_ids(db, domain)))
    if level:
        query = query.where(or_(CareerLevel.slug == level, func.lower(CareerLevel.name) == level.casefold()))

    if category:
        query = query.where(or_(CompetencyCategory.slug == category, func.lower(CompetencyCategory.name) == category.casefold()))
    if importance:
        query = query.where(func.lower(DomainLevelExpectation.importance) == importance.casefold())
    if proficiency:
        query = query.where(func.lower(DomainLevelExpectation.proficiency_level) == proficiency.casefold())
    query = query.order_by(DomainLevelExpectation.id)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = [expectation_read(item) for item in db.scalars(page_slice(query, page, page_size)).unique().all()]
    return ExpectationPage(items=items, meta=page_meta(page, page_size, total))


@router.get("/expectations/{expectation_id}", response_model=ExpectationRead, tags=["expectations"])
def get_expectation(expectation_id: int, db: Session = Depends(get_db)) -> ExpectationRead:
    item = db.scalar(select(DomainLevelExpectation).where(DomainLevelExpectation.id == expectation_id).options(*expectation_options()))
    if item is None:
        raise not_found("Expectation", expectation_id)
    return expectation_read(item)


@router.get("/career-matrix", response_model=CareerMatrixResponse, tags=["career-matrix"])
def career_matrix(db: Session = Depends(get_db)) -> CareerMatrixResponse:
    domains = list(db.scalars(select(SecurityDomain).order_by(SecurityDomain.display_order, SecurityDomain.name)).all())
    levels = list(db.scalars(select(CareerLevel).order_by(CareerLevel.display_order)).all())
    expectations = list(db.scalars(select(DomainLevelExpectation).options(selectinload(DomainLevelExpectation.domain), selectinload(DomainLevelExpectation.career_level), selectinload(DomainLevelExpectation.competency).selectinload(Competency.category))).all())
    grouped: dict[tuple[int, int], list[DomainLevelExpectation]] = defaultdict(list)
    for item in expectations:
        grouped[(item.domain_id, item.career_level_id)].append(item)
    return CareerMatrixResponse(
        levels=[LevelRead.model_validate(level) for level in levels],
        domains=[MatrixDomain(domain=ref_domain(domain), cells=[
            MatrixCell(
                domain_id=domain.id,
                career_level_id=level.id,
                expectation_count=len(grouped[(domain.id, level.id)]),
                competency_count=len({item.competency_id for item in grouped[(domain.id, level.id)]}),
                category_distribution=dict(sorted({category: sum(1 for item in grouped[(domain.id, level.id)] if item.competency.category.slug == category) for category in {item.competency.category.slug for item in grouped[(domain.id, level.id)]}}.items())),
            ) for level in levels
        ]) for domain in domains],
    )


@router.get("/compare", response_model=CareerComparisonResponse, tags=["comparison"])
def compare_levels(
    domain: str = Query(min_length=1, max_length=160),
    levels: str = Query(min_length=1, max_length=400, description="Comma-separated career-level slugs or names."),
    db: Session = Depends(get_db),
) -> CareerComparisonResponse:
    requested_levels = [item.strip() for item in levels.split(",") if item.strip()]
    if len(requested_levels) < 2 or len(requested_levels) > 6 or len(set(item.casefold() for item in requested_levels)) != len(requested_levels):
        raise HTTPException(status_code=422, detail="levels must contain between two and six distinct comma-separated levels")
    domain_item = db.scalar(select(SecurityDomain).where(domain_filter(SecurityDomain, domain)))
    if domain_item is None:
        raise not_found("Security domain", domain)
    all_levels = list(db.scalars(select(CareerLevel).order_by(CareerLevel.display_order)).all())
    chosen_levels = []
    for requested in requested_levels:
        level_item = next((item for item in all_levels if matches(item.slug, requested) or matches(item.name, requested)), None)
        if level_item is None:
            raise not_found("Career level", requested)
        chosen_levels.append(level_item)
    rows = list(db.scalars(select(DomainLevelExpectation).where(
        DomainLevelExpectation.domain_id == domain_item.id,
        DomainLevelExpectation.career_level_id.in_([level.id for level in chosen_levels]),
    ).options(*expectation_options())).all())
    by_level: dict[int, list[DomainLevelExpectation]] = defaultdict(list)
    for row in rows:
        by_level[row.career_level_id].append(row)
    ids_by_level = {level.slug: {row.competency_id for row in by_level[level.id]} for level in chosen_levels}
    all_ids = set().union(*ids_by_level.values()) if ids_by_level else set()
    shared_ids = set.intersection(*ids_by_level.values()) if ids_by_level else set()
    competencies = {row.competency_id: row.competency for row in rows}

    def comparison_item(competency_id: int) -> ComparisonCompetency:
        competency_rows = {level.slug: [row for row in by_level[level.id] if row.competency_id == competency_id] for level in chosen_levels}
        return ComparisonCompetency(
            competency=competency_item(competencies[competency_id]),
            expectations_by_level={key: [expectation_summary(row) for row in value] for key, value in competency_rows.items() if value},
            proficiency_by_level={key: sorted({row.proficiency_level for row in value}) for key, value in competency_rows.items() if value},
            responsibilities_by_level={key: sorted({row.responsibility_type for row in value}) for key, value in competency_rows.items() if value},
        )

    shared = [comparison_item(competency_id) for competency_id in sorted(shared_ids)]
    unique = {}
    for level in chosen_levels:
        own_ids = ids_by_level[level.slug]
        other_ids = set().union(*(ids_by_level[other.slug] for other in chosen_levels if other.id != level.id))
        unique[level.slug] = [comparison_item(competency_id) for competency_id in sorted(own_ids - other_ids)]
    differences = []
    for competency_id in sorted(all_ids):
        item = comparison_item(competency_id)
        if len(set(tuple(values) for values in item.proficiency_by_level.values())) > 1 or len(set(tuple(values) for values in item.responsibilities_by_level.values())) > 1 or len(item.expectations_by_level) > 1 and len({tuple(summary.expectation_description for summary in values) for values in item.expectations_by_level.values()}) > 1:
            differences.append(item)
    return CareerComparisonResponse(
        domain=ref_domain(domain_item),
        levels=[ComparisonLevel(level=level, competency_ids=sorted(ids_by_level[level.slug]), competency_count=len(ids_by_level[level.slug])) for level in chosen_levels],
        shared_competencies=shared,
        unique_competencies=unique,
        differences=differences,
    )


@router.get("/search", response_model=SearchPage, tags=["search"])
def search(
    keyword: str = Query(min_length=1, max_length=120),
    domain: str | None = Query(default=None, min_length=1, max_length=160),
    level: str | None = Query(default=None, min_length=1, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SearchPage:
    term = f"%{keyword}%"
    results: list[SearchResult] = []
    domain_query = select(SecurityDomain).where(or_(SecurityDomain.name.ilike(term), SecurityDomain.description.ilike(term))).order_by(SecurityDomain.name)
    if domain:
        domain_query = domain_query.where(domain_filter(SecurityDomain, domain))
    results.extend(SearchResult(result_type="domain", id=item.id, name=item.name, description=item.description) for item in db.scalars(domain_query).all())

    expectation_query = select(DomainLevelExpectation).join(DomainLevelExpectation.domain).join(DomainLevelExpectation.career_level).join(DomainLevelExpectation.competency).options(*expectation_options()).where(
        or_(Competency.name.ilike(term), Competency.description.ilike(term), DomainLevelExpectation.expectation_description.ilike(term), SecurityDomain.name.ilike(term))
    )
    if domain:
        expectation_query = expectation_query.where(DomainLevelExpectation.domain_id.in_(descendant_domain_ids(db, domain)))
    if level:
        expectation_query = expectation_query.where(or_(CareerLevel.slug == level, func.lower(CareerLevel.name) == level.casefold()))
    for item in db.scalars(expectation_query.order_by(DomainLevelExpectation.id)).unique().all():
        results.append(SearchResult(result_type="expectation", id=item.id, name=item.competency.name, description=item.expectation_description, domain=ref_domain(item.domain), career_level=ref_level_short(item.career_level), competency_id=item.competency_id))

    competency_query = select(Competency).options(*competency_options()).where(or_(Competency.name.ilike(term), Competency.description.ilike(term)))
    if domain:
        competency_query = competency_query.where(Competency.expectations.any(DomainLevelExpectation.domain_id.in_(descendant_domain_ids(db, domain))))
    if level:
        competency_query = competency_query.where(Competency.expectations.any(DomainLevelExpectation.career_level.has(
            or_(CareerLevel.slug == level, func.lower(CareerLevel.name) == level.casefold())
        )))
    for item in db.scalars(competency_query.distinct().order_by(Competency.name)).unique().all():
        results.append(SearchResult(result_type="competency", id=item.id, name=item.name, description=item.description, competency_id=item.id))

    results.sort(key=lambda item: (item.name.casefold(), item.result_type, item.id))
    total = len(results)
    start = (page - 1) * page_size
    return SearchPage(items=results[start:start + page_size], meta=page_meta(page, page_size, total))


@router.get("/research-sources", response_model=ResearchSourcePage, tags=["research-sources"])
def list_research_sources(page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)) -> ResearchSourcePage:
    query = select(ResearchSource).options(selectinload(ResearchSource.expectations)).order_by(ResearchSource.collected_at.desc(), ResearchSource.id.desc())
    total = db.scalar(select(func.count()).select_from(ResearchSource)) or 0
    items = [source_read(item) for item in db.scalars(page_slice(query, page, page_size)).unique().all()]
    return ResearchSourcePage(items=items, meta=page_meta(page, page_size, total))
