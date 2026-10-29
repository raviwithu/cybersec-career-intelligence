from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class IntelligenceRef(BaseModel):
    id: int
    name: str
    slug: str


class EvidenceReference(BaseModel):
    expectation_id: int
    source_id: int
    source_title: str
    source_url: str
    research_date: datetime
    excerpt: str
    publication_version: int | None = None


class DistributionItem(BaseModel):
    item: IntelligenceRef
    source_count: int
    mention_rate: float | None = None


class CompetencyFrequency(BaseModel):
    competency: IntelligenceRef
    category: IntelligenceRef
    source_count: int
    relevant_source_count: int
    mention_rate: float | None
    latest_research_date: datetime | None
    industry_distribution: list[DistributionItem] = Field(default_factory=list)
    domain_distribution: list[DistributionItem] = Field(default_factory=list)
    career_level_distribution: list[DistributionItem] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class IntelligenceFilterState(BaseModel):
    industry: IntelligenceRef | None = None
    domain: IntelligenceRef | None = None
    career_level: IntelligenceRef | None = None
    category: IntelligenceRef | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class IntelligenceDashboardResponse(BaseModel):
    filters: IntelligenceFilterState
    relevant_source_count: int
    distinct_competency_count: int
    evidence_count: int
    research_date_min: datetime | None
    research_date_max: datetime | None
    coverage: dict[str, int | float | str | bool]
    competency_frequency: list[CompetencyFrequency]
    data_quality: list[str]


class TrendPoint(BaseModel):
    period: str
    period_start: datetime
    relevant_source_count: int
    source_mention_count: int
    normalized_mention_rate: float | None
    competency_count: int


class SkillTrend(BaseModel):
    competency: IntelligenceRef
    category: IntelligenceRef
    points: list[TrendPoint]
    direction: Literal["emerging", "increasing", "stable", "decreasing", "insufficient_data"]
    sample_size: int
    coverage_source_count: int
    warning: str | None = None


class SkillTrendsResponse(BaseModel):
    window: Literal["monthly", "quarterly", "rolling_6m", "rolling_12m"]
    minimum_sample_size: int
    minimum_coverage: int
    relevant_source_count: int
    trends: list[SkillTrend]
    data_quality: list[str]


class ProgressionExpectation(BaseModel):
    competency: IntelligenceRef
    category: IntelligenceRef
    expectations: list[dict]
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)


class CareerProgressionResponse(BaseModel):
    industry: IntelligenceRef | None
    domain: IntelligenceRef
    starting_level: IntelligenceRef
    target_level: IntelligenceRef
    technical_track: str
    shared_expectations: list[ProgressionExpectation]
    starting_only_expectations: list[ProgressionExpectation]
    target_additional_expectations: list[ProgressionExpectation]
    responsibility_changes: list[str]
    evidence_source_count: int
    warnings: list[str]


class IndustryComparisonItem(BaseModel):
    competency: IntelligenceRef
    category: IntelligenceRef
    industry_source_counts: dict[str, int]
    industry_mention_rates: dict[str, float | None]
    shared: bool
    evidence: list[EvidenceReference] = Field(default_factory=list)


class IndustryComparisonResponse(BaseModel):
    domain: IntelligenceRef
    career_level: IntelligenceRef
    industries: list[IntelligenceRef]
    shared_competencies: list[IndustryComparisonItem]
    industry_specific_competencies: dict[str, list[IndustryComparisonItem]]
    coverage: dict[str, int]
    warnings: list[str]


class EvidenceExplorerResponse(BaseModel):
    competency: IntelligenceRef | None = None
    evidence: list[EvidenceReference]
    total: int
    data_quality: list[str]


class HistoricalExpectation(BaseModel):
    expectation_id: int
    competency: IntelligenceRef
    domain: IntelligenceRef
    career_level: IntelligenceRef
    industry: IntelligenceRef | None
    version: int
    recorded_at: datetime
    snapshot: dict
    evidence: list[EvidenceReference] = Field(default_factory=list)


class HistoricalResponse(BaseModel):
    available: bool
    expectations: list[HistoricalExpectation]
    warnings: list[str]


class ProfileCreateRequest(BaseModel):
    target_industry_id: int | None = Field(default=None, ge=1)
    target_domain_id: int | None = Field(default=None, ge=1)
    target_career_level_id: int | None = Field(default=None, ge=1)


class ProfileCreateResponse(BaseModel):
    profile_id: int
    profile_key: str
    message: str


class AssessmentItem(BaseModel):
    competency_id: int = Field(ge=1)
    proficiency: Literal["not_familiar", "basic", "proficient", "intermediate", "advanced", "expert"]


class ProfileAssessmentRequest(BaseModel):
    assessments: list[AssessmentItem] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def reject_duplicate_competencies(self):
        ids = [item.competency_id for item in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("Each competency may be assessed only once")
        return self


class ProfileResponse(BaseModel):
    profile_id: int
    target_industry: IntelligenceRef | None
    target_domain: IntelligenceRef | None
    target_career_level: IntelligenceRef | None
    assessments: list[dict]
    updated_at: datetime


class GapItem(BaseModel):
    competency: IntelligenceRef
    category: IntelligenceRef
    self_assessment: str | None
    expected_proficiency: list[str]
    expectation_count: int
    evidence_source_count: int
    gap_type: Literal["match", "development_area", "unassessed"]
    evidence: list[EvidenceReference] = Field(default_factory=list)


class CompetencyGapResponse(BaseModel):
    target: IntelligenceFilterState
    assessed_competency_count: int
    expected_competency_count: int
    matching: list[GapItem]
    development_areas: list[GapItem]
    unassessed: list[GapItem]
    warnings: list[str]


class RoadmapRecommendation(BaseModel):
    section: Literal["Foundational Knowledge", "Technical Skills", "Practical Experience", "Security Architecture", "Standards and Regulations", "Leadership and Responsibilities"]
    competency: IntelligenceRef | None
    why_it_matters: str
    published_expectation: str | None
    knowledge_to_develop: str
    practical_activity: str
    evidence: list[EvidenceReference] = Field(default_factory=list)
    ai_generated: bool = False


class CareerRoadmapResponse(BaseModel):
    target: IntelligenceFilterState
    recommendations: list[RoadmapRecommendation]
    warnings: list[str]


class AskCareerRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    industry: str | None = Field(default=None, max_length=160)
    domain: str | None = Field(default=None, max_length=160)
    career_level: str | None = Field(default=None, max_length=80)


class AskCareerResponse(BaseModel):
    answer: str
    evidence: list[EvidenceReference]
    retrieved_context_count: int
    model_provider: str | None
    model_id: str | None
    uncertainty: list[str]
    insufficient_evidence: bool
    warnings: list[str]
