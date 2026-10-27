from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=160)
    description: str = ""
    parent_id: int | None = None
    display_order: int = 0


class DomainResponse(DomainCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CareerLevelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=80)
    career_track: str = Field(pattern="^(technical|management|shared)$")
    description: str = ""
    display_order: int = 0


class CareerLevelResponse(CareerLevelCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120)
    description: str = ""


class CategoryResponse(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CompetencyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    description: str = ""
    category_id: int


class CompetencyResponse(CompetencyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    category_name: str


class RelationshipCreate(BaseModel):
    source_competency_id: int
    target_competency_id: int
    relationship_type: str = Field(pattern="^(prerequisite|related|specialization|dependency)$")


class RelationshipResponse(RelationshipCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ExpectationCreate(BaseModel):
    domain_id: int
    career_level_id: int
    competency_id: int
    technical_knowledge: str = ""
    practical_capability: str = ""
    qualifications: str = ""
    tools_technologies: str = ""
    expectation_description: str = Field(min_length=1)
    proficiency_level: str = Field(min_length=1, max_length=40)
    importance: str = Field(min_length=1, max_length=40)
    responsibility_type: str = Field(min_length=1, max_length=80)
    experience_years_min: int | None = Field(default=None, ge=0)
    experience_years_max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.experience_years_min is not None and self.experience_years_max is not None and self.experience_years_min > self.experience_years_max:
            raise ValueError("experience_years_min cannot exceed experience_years_max")
        return self


class ExpectationResponse(ExpectationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_name: str
    career_level_name: str
    competency_name: str
    source_count: int
    created_at: datetime
    updated_at: datetime


class ResearchSourceCreate(BaseModel):
    source_type: str = Field(min_length=1, max_length=60)
    source_url: str = Field(min_length=1, max_length=1000)
    source_title: str = Field(min_length=1, max_length=300)
    collected_at: datetime | None = None
    notes: str | None = None


class ResearchSourceResponse(ResearchSourceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    collected_at: datetime


class ExpectationSourceCreate(BaseModel):
    supporting_excerpt: str = Field(min_length=1)


class AnalysisVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    analysis_date: datetime
    description: str
    methodology: str


class AnalysisVersionResponse(AnalysisVersionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
