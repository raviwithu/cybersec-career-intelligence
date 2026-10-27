from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class DomainRef(BaseModel):
    id: int
    name: str
    slug: str


class LevelRef(BaseModel):
    id: int
    name: str
    slug: str
    career_track: str


class CategoryRef(BaseModel):
    id: int
    name: str
    slug: str


class DomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str
    parent_id: int | None
    display_order: int
    created_at: datetime
    updated_at: datetime
    children: list[DomainRead] = Field(default_factory=list)


class LevelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    career_track: str
    description: str
    display_order: int


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str


class ResearchSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    source_url: str
    source_title: str
    collected_at: datetime
    notes: str | None
    expectation_ids: list[int] = Field(default_factory=list)


class RelationshipRead(BaseModel):
    id: int
    relationship_type: str
    direction: str
    competency_id: int
    competency_name: str
    competency_slug: str


class CompetencyListItem(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    category: CategoryRef
    domains: list[DomainRef]
    career_levels: list[LevelRef]


class ExpectationSummary(BaseModel):
    id: int
    domain: DomainRef
    career_level: LevelRef
    technical_knowledge: str
    practical_capability: str
    qualifications: str
    tools_technologies: str
    expectation_description: str
    proficiency_level: str
    importance: str
    responsibility_type: str
    experience_years_min: int | None
    experience_years_max: int | None


class CompetencyDetail(CompetencyListItem):
    created_at: datetime
    updated_at: datetime
    related_competencies: list[RelationshipRead]
    expectations: list[ExpectationSummary]


class CompetencyPage(BaseModel):
    items: list[CompetencyListItem]
    meta: PageMeta


class ExpectationSourceRead(BaseModel):
    source: ResearchSourceRead
    supporting_excerpt: str


class ExpectationRead(BaseModel):
    id: int
    domain: DomainRef
    career_level: LevelRef
    competency: CompetencyListItem
    technical_knowledge: str
    practical_capability: str
    qualifications: str
    tools_technologies: str
    expectation_description: str
    proficiency_level: str
    importance: str
    responsibility_type: str
    experience_years_min: int | None
    experience_years_max: int | None
    created_at: datetime
    updated_at: datetime
    supporting_sources: list[ExpectationSourceRead]


class ExpectationPage(BaseModel):
    items: list[ExpectationRead]
    meta: PageMeta


class MatrixCell(BaseModel):
    domain_id: int
    career_level_id: int
    expectation_count: int
    competency_count: int
    category_distribution: dict[str, int]


class MatrixDomain(BaseModel):
    domain: DomainRef
    cells: list[MatrixCell]


class CareerMatrixResponse(BaseModel):
    levels: list[LevelRead]
    domains: list[MatrixDomain]


class ComparisonCompetency(BaseModel):
    competency: CompetencyListItem
    expectations_by_level: dict[str, list[ExpectationSummary]]
    proficiency_by_level: dict[str, list[str]]
    responsibilities_by_level: dict[str, list[str]]


class ComparisonLevel(BaseModel):
    level: LevelRead
    competency_ids: list[int]
    competency_count: int


class CareerComparisonResponse(BaseModel):
    domain: DomainRef
    levels: list[ComparisonLevel]
    shared_competencies: list[ComparisonCompetency]
    unique_competencies: dict[str, list[ComparisonCompetency]]
    differences: list[ComparisonCompetency]


class SearchResult(BaseModel):
    result_type: str
    id: int
    name: str
    description: str
    domain: DomainRef | None = None
    career_level: LevelRef | None = None
    competency_id: int | None = None


class SearchPage(BaseModel):
    items: list[SearchResult]
    meta: PageMeta


class ResearchSourcePage(BaseModel):
    items: list[ResearchSourceRead]
    meta: PageMeta
