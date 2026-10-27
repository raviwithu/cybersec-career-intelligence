from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExtractedRequirement(BaseModel):
    domain_slugs: list[str] = Field(default_factory=list, max_length=8)
    security_subdomains: list[str] = Field(default_factory=list, max_length=8)
    career_level: str | None = Field(default=None, max_length=80)
    competency_name: str = Field(min_length=1, max_length=200)
    category_slug: str | None = Field(default=None, max_length=120)
    technical_knowledge: str = Field(default="", max_length=4000)
    practical_capability: str = Field(default="", max_length=4000)
    responsibilities: str = Field(default="", max_length=4000)
    finding_type: str = Field(default="technical-skills", max_length=60)
    proficiency_level: str = Field(default="proficient", max_length=40)
    importance: str = Field(default="important", max_length=40)
    experience_years_min: int | None = Field(default=None, ge=0, le=80)
    experience_years_max: int | None = Field(default=None, ge=0, le=80)
    evidence_excerpt: str = Field(min_length=1, max_length=3000)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("experience_years_max")
    @classmethod
    def max_years_is_reasonable(cls, value: int | None) -> int | None:
        return value


class ExtractionResult(BaseModel):
    requirements: list[ExtractedRequirement] = Field(default_factory=list, max_length=100)
    unclassified_notes: list[str] = Field(default_factory=list, max_length=20)


class SubmissionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)
    source_title: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=1000)
    research_date: datetime | None = None
    source_type: Literal["pasted_text", "url_imported"] = "pasted_text"


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=1000)


class ModelSelectRequest(BaseModel):
    provider: Literal["ollama", "openwebui"] = "ollama"
    model_id: str | None = Field(default=None, min_length=1, max_length=255)
    model_name: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def require_model_identifier(self):
        if not self.model_id and not self.model_name:
            raise ValueError("model_id is required")
        if not self.model_id:
            self.model_id = self.model_name
        return self


class UrlImportResponse(BaseModel):
    source_url: str
    job_title: str
    job_description: str
    extraction_method: Literal["json_ld", "html"]
    date_posted: str | None = None
    status: Literal["success"] = "success"


class ResearchSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    source_title: str
    source_url: str
    source_type: str
    original_filename: str | None
    content_size: int
    status: str
    model_provider: str | None
    model_id: str | None
    model_name: str | None
    evaluation_version: str | None
    error_message: str | None
    submitted_at: datetime
    completed_at: datetime | None
    finding_count: int = 0
    draft_count: int = 0


class SubmissionPage(BaseModel):
    items: list[ResearchSubmissionResponse]
    total: int


class DraftEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_title: str
    source_url: str
    collected_at: datetime
    supporting_excerpt: str


class DraftExpectationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_id: int
    domain_id: int
    domain_name: str
    career_level_id: int
    career_level_name: str
    competency_id: int
    competency_name: str
    expectation_description: str
    proficiency_level: str
    importance: str
    responsibility_type: str
    experience_years_min: int | None
    experience_years_max: int | None
    status: str
    reviewer_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    published_expectation_id: int | None
    evidence: list[DraftEvidenceResponse] = Field(default_factory=list)


class DraftPage(BaseModel):
    items: list[DraftExpectationResponse]
    total: int


class DraftUpdate(BaseModel):
    expectation_description: str = Field(min_length=1, max_length=4000)
    proficiency_level: str = Field(min_length=1, max_length=40)
    importance: str = Field(min_length=1, max_length=40)
    responsibility_type: str = Field(min_length=1, max_length=80)
    experience_years_min: int | None = Field(default=None, ge=0, le=80)
    experience_years_max: int | None = Field(default=None, ge=0, le=80)
    reviewer_note: str | None = Field(default=None, max_length=2000)


class ReviewAction(BaseModel):
    reviewer_note: str | None = Field(default=None, max_length=2000)


class WorkflowResponse(BaseModel):
    status: str
    draft: DraftExpectationResponse


class ModelEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str = "ollama"
    model_id: str = ""
    model_name: str
    evaluation_version: str
    extraction_accuracy: float
    classification_accuracy: float
    json_validity: float
    hallucination_rate: float
    average_processing_ms: float
    overall_score: float
    error_message: str | None
    evaluated_at: datetime


class OllamaStatusResponse(BaseModel):
    status: Literal["configured", "unavailable", "unconfigured"]
    model: str | None = None
    active_model: str | None = None
    mode: Literal["automatic", "manual", "fallback"] = "fallback"
    evaluation_version: str | None = None
    available_models: list[str] = Field(default_factory=list)
    evaluations: list[ModelEvaluationResponse] = Field(default_factory=list)
    detail: str | None = None


class AIModelResponse(BaseModel):
    provider: Literal["ollama", "openwebui"]
    id: str
    name: str
    size: int | None = None
    details: dict = Field(default_factory=dict)
    provider_info: str | None = None
    metadata: dict = Field(default_factory=dict)
    possible_duplicate: bool = False
    duplicate_with: list[str] = Field(default_factory=list)


class ProviderModelsResponse(BaseModel):
    provider: Literal["ollama", "openwebui"]
    status: Literal["connected", "unavailable", "unconfigured"]
    models: list[AIModelResponse] = Field(default_factory=list)
    error: str | None = None


class UnifiedModelsResponse(BaseModel):
    providers: list[ProviderModelsResponse]
    active_provider: str
    active_model_id: str
    active_model_name: str
    mode: Literal["automatic", "manual", "fallback"]
    evaluation_version: str | None = None
    evaluations: list[ModelEvaluationResponse] = Field(default_factory=list)


class ModelTestResponse(BaseModel):
    provider: str
    model_id: str
    reachable: bool
    latency_ms: float | None = None
    detail: str


class UnifiedSelectionResponse(UnifiedModelsResponse):
    pass
