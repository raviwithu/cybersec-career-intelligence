from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ReviewActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reviewer_note: str | None = Field(default=None, max_length=2000)
    publish: bool = False


class ReviewModifyRequest(BaseModel):
    expected_version: int = Field(ge=1)
    competency_name: str | None = Field(default=None, min_length=1, max_length=200)
    competency_description: str | None = Field(default=None, max_length=4000)
    domain_ids: list[int] | None = Field(default=None, min_length=1, max_length=8)
    career_level_id: int | None = Field(default=None, ge=1)
    category_id: int | None = Field(default=None, ge=1)
    technical_knowledge: str | None = Field(default=None, max_length=4000)
    practical_capability: str | None = Field(default=None, max_length=4000)
    qualifications: str | None = Field(default=None, max_length=4000)
    tools_technologies: str | None = Field(default=None, max_length=4000)
    expectation_description: str | None = Field(default=None, min_length=1, max_length=4000)
    responsibilities: str | None = Field(default=None, max_length=4000)
    proficiency_level: str | None = Field(default=None, max_length=40)
    importance: str | None = Field(default=None, max_length=40)
    experience_years_min: int | None = Field(default=None, ge=0, le=80)
    experience_years_max: int | None = Field(default=None, ge=0, le=80)
    supporting_evidence: list[str] | None = Field(default=None, min_length=1, max_length=20)
    reviewer_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.experience_years_min is not None and self.experience_years_max is not None and self.experience_years_min > self.experience_years_max:
            raise ValueError("experience_years_min cannot exceed experience_years_max")
        return self


class ReviewMergeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    target_competency_id: int = Field(ge=1)
    merged: ReviewModifyRequest | None = None
    reviewer_note: str | None = Field(default=None, max_length=2000)


class PublicationRequest(BaseModel):
    confirm: bool = False
    change_ids: list[int] | None = Field(default=None, max_length=500)
    expected_versions: dict[int, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirm:
            raise ValueError("confirm must be true to publish approved changes")
        return self


class ReviewFindingResponse(BaseModel):
    id: int
    finding_type: str
    candidate_name: str
    normalized_name: str | None
    technical_knowledge: str
    practical_capability: str
    qualifications: str
    tools_technologies: str
    responsibilities: str
    proficiency_level: str
    importance: str
    experience_years_min: int | None
    experience_years_max: int | None
    evidence_excerpt: str
    confidence: float | None
    confidence_meaningful: bool
    status: str
    classification_gaps: list[str]
    domains: list[dict[str, Any]]
    career_level: dict[str, Any] | None
    category: dict[str, Any] | None
    competency: dict[str, Any] | None
    existing_matches: list[dict[str, Any]]
    review_change: dict[str, Any] | None


class ReviewSubmissionSummary(BaseModel):
    id: int
    source_id: int
    source_title: str
    source_url: str
    source_type: str
    submitted_at: datetime
    completed_at: datetime | None
    model_provider: str | None
    model_id: str | None
    model_name: str | None
    evaluation_version: str | None
    status: str
    finding_count: int
    proposed_new_competencies: int
    proposed_updates: int
    potential_duplicates: int
    manual_classification_count: int
    review_status: str


class ReviewDashboardResponse(BaseModel):
    pending_reviews: list[ReviewSubmissionSummary]
    approved_changes: list[dict[str, Any]]
    rejected_findings: list[dict[str, Any]]
    change_history: list[dict[str, Any]]
    filters: dict[str, list[dict[str, Any]]]


class ReviewSubmissionDetail(BaseModel):
    submission: ReviewSubmissionSummary
    source: dict[str, Any]
    findings: list[ReviewFindingResponse]
    domain_impact: list[dict[str, Any]]


class ReviewComparisonResponse(BaseModel):
    change: dict[str, Any]
    existing: dict[str, Any]
    incoming: dict[str, Any]
    proposed: dict[str, Any]
    differences: dict[str, list[Any]]
    evidence: list[dict[str, Any]]


class PublicationPreviewResponse(BaseModel):
    new_competencies: int
    updated_expectations: int
    merged_findings: int
    rejected_findings: int
    affected_domains: list[dict[str, Any]]
    affected_career_levels: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    ready: bool
    blockers: list[str]


class ReviewMutationResponse(BaseModel):
    status: str
    change: dict[str, Any]


class PublicationResponse(BaseModel):
    status: str
    batch_id: int
    published_change_ids: list[int]
    published_expectation_ids: list[int]
    published_competency_ids: list[int]


class HistoryResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
