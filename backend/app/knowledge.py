from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .database import get_db
from .knowledge_schemas import (
    AnalysisVersionCreate, AnalysisVersionResponse, CareerLevelCreate, CareerLevelResponse,
    CategoryCreate, CategoryResponse, CompetencyCreate, CompetencyResponse, DomainCreate,
    DomainResponse, ExpectationCreate, ExpectationResponse, ExpectationSourceCreate,
    RelationshipCreate, RelationshipResponse, ResearchSourceCreate, ResearchSourceResponse,
)
from .models import (
    AnalysisVersion, CareerLevel, Competency, CompetencyCategory, CompetencyRelationship,
    DomainLevelExpectation, ExpectationSource, ResearchSource, SecurityDomain,
)

router = APIRouter()


def missing(resource: str, identifier: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} {identifier} was not found")



def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="The requested knowledge record conflicts with an existing record or relationship") from exc


def serialize_competency(item: Competency) -> CompetencyResponse:
    return CompetencyResponse(**item.__dict__, category_name=item.category.name)


def serialize_expectation(item: DomainLevelExpectation) -> ExpectationResponse:
    return ExpectationResponse(
        id=item.id, domain_id=item.domain_id, career_level_id=item.career_level_id,
        competency_id=item.competency_id, expectation_description=item.expectation_description,
        proficiency_level=item.proficiency_level, importance=item.importance,
        responsibility_type=item.responsibility_type, experience_years_min=item.experience_years_min,
        experience_years_max=item.experience_years_max, domain_name=item.domain.name,
        career_level_name=item.career_level.name, competency_name=item.competency.name,
        source_count=len(item.sources), created_at=item.created_at, updated_at=item.updated_at,
    )


@router.get("/taxonomy")
def taxonomy(db: Session = Depends(get_db)) -> dict:
    domains = db.scalars(select(SecurityDomain).where(SecurityDomain.parent_id.is_(None)).options(selectinload(SecurityDomain.children)).order_by(SecurityDomain.display_order)).all()
    levels = db.scalars(select(CareerLevel).order_by(CareerLevel.display_order)).all()
    categories = db.scalars(select(CompetencyCategory).order_by(CompetencyCategory.name)).all()
    competencies = db.scalars(select(Competency).options(selectinload(Competency.category)).order_by(Competency.name)).all()
    return {
        "domains": [{
            "id": domain.id, "name": domain.name, "slug": domain.slug, "description": domain.description,
            "display_order": domain.display_order,
            "children": [DomainResponse.model_validate(child).model_dump(mode="json") for child in sorted(domain.children, key=lambda item: item.display_order)],
        } for domain in domains],
        "career_levels": [CareerLevelResponse.model_validate(level).model_dump(mode="json") for level in levels],
        "competency_categories": [CategoryResponse.model_validate(category).model_dump(mode="json") for category in categories],
        "competencies": [serialize_competency(item).model_dump(mode="json") for item in competencies],
    }


@router.post("/domains", response_model=DomainResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_domain(payload: DomainCreate, db: Session = Depends(get_db)) -> SecurityDomain:
    if payload.parent_id is not None and db.get(SecurityDomain, payload.parent_id) is None:
        raise missing("Parent domain", payload.parent_id)
    item = SecurityDomain(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return item


@router.post("/career-levels", response_model=CareerLevelResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_career_level(payload: CareerLevelCreate, db: Session = Depends(get_db)) -> CareerLevel:
    item = CareerLevel(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return item


@router.post("/competency-categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)) -> CompetencyCategory:
    item = CompetencyCategory(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return item


@router.post("/competencies", response_model=CompetencyResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_competency(payload: CompetencyCreate, db: Session = Depends(get_db)) -> CompetencyResponse:
    if db.get(CompetencyCategory, payload.category_id) is None:
        raise missing("Competency category", payload.category_id)
    item = Competency(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return serialize_competency(item)


@router.post("/competency-relationships", response_model=RelationshipResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_relationship(payload: RelationshipCreate, db: Session = Depends(get_db)) -> CompetencyRelationship:
    for label, identifier in (("Source competency", payload.source_competency_id), ("Target competency", payload.target_competency_id)):
        if db.get(Competency, identifier) is None:
            raise missing(label, identifier)
    item = CompetencyRelationship(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return item


@router.post("/expectations", response_model=ExpectationResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_expectation(payload: ExpectationCreate, db: Session = Depends(get_db)) -> ExpectationResponse:
    for model, label, identifier in ((SecurityDomain, "Domain", payload.domain_id), (CareerLevel, "Career level", payload.career_level_id), (Competency, "Competency", payload.competency_id)):
        if db.get(model, identifier) is None:
            raise missing(label, identifier)
    item = DomainLevelExpectation(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    query = select(DomainLevelExpectation).where(DomainLevelExpectation.id == item.id).options(
        selectinload(DomainLevelExpectation.domain), selectinload(DomainLevelExpectation.career_level),
        selectinload(DomainLevelExpectation.competency), selectinload(DomainLevelExpectation.sources),
    )
    return serialize_expectation(db.scalar(query))


@router.post("/research-sources", response_model=ResearchSourceResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_source(payload: ResearchSourceCreate, db: Session = Depends(get_db)) -> ResearchSource:
    item = ResearchSource(**payload.model_dump(exclude_none=True))
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return item


@router.post("/expectations/{expectation_id}/sources/{source_id}", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def link_source(expectation_id: int, source_id: int, payload: ExpectationSourceCreate, db: Session = Depends(get_db)) -> dict:
    if db.get(DomainLevelExpectation, expectation_id) is None:
        raise missing("Expectation", expectation_id)
    if db.get(ResearchSource, source_id) is None:
        raise missing("Research source", source_id)
    link = ExpectationSource(expectation_id=expectation_id, source_id=source_id, supporting_excerpt=payload.supporting_excerpt)
    db.add(link)
    commit_or_conflict(db)
    return {"expectation_id": expectation_id, "source_id": source_id, "supporting_excerpt": link.supporting_excerpt}


@router.post("/analysis-versions", response_model=AnalysisVersionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_analysis_version(payload: AnalysisVersionCreate, db: Session = Depends(get_db)) -> AnalysisVersion:
    item = AnalysisVersion(**payload.model_dump())
    db.add(item)
    commit_or_conflict(db)
    db.refresh(item)
    return item
