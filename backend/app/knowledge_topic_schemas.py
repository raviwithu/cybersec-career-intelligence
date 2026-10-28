from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


EvidenceStatus = Literal["explicitly_supported", "ai-derived", "curated_foundational"]
ProposalAction = Literal["accept", "modify", "merge", "reject", "defer"]
TopicStatus = Literal["draft", "review", "approved", "published", "rejected", "deferred"]


class TopicLevelExpectationInput(BaseModel):
    career_level_id: int = Field(ge=1)
    industry_id: int | None = Field(default=None, ge=1)
    expectation: str = Field(default="", max_length=4000)
    practical_capability: str = Field(default="", max_length=4000)
    display_order: int = Field(default=0, ge=0, le=100000)


class KnowledgeTopicDraft(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=1, max_length=240)
    description: str = Field(default="", max_length=6000)
    category_id: int | None = Field(default=None, ge=1)
    parent_topic_id: int | None = Field(default=None, ge=1)
    domain_ids: list[int] = Field(default_factory=list, max_length=20)
    industry_ids: list[int] = Field(default_factory=list, max_length=20)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    related_competency_ids: list[int] = Field(default_factory=list, max_length=50)
    level_expectations: list[TopicLevelExpectationInput] = Field(default_factory=list, max_length=100)
    display_order: int = Field(default=0, ge=0, le=100000)


class KnowledgeTopicCreate(KnowledgeTopicDraft):
    publication_status: Literal["draft", "published"] = "draft"


class KnowledgeTopicUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=6000)
    category_id: int | None = Field(default=None, ge=1)
    parent_topic_id: int | None = Field(default=None, ge=1)
    domain_ids: list[int] | None = Field(default=None, max_length=20)
    industry_ids: list[int] | None = Field(default=None, max_length=20)
    aliases: list[str] | None = Field(default=None, max_length=50)
    related_competency_ids: list[int] | None = Field(default=None, max_length=50)
    level_expectations: list[TopicLevelExpectationInput] | None = Field(default=None, max_length=100)
    display_order: int | None = Field(default=None, ge=0, le=100000)
    change_reason: str = Field(default="", max_length=500)


class KnowledgeTopicResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    category: dict[str, Any] | None
    parent: dict[str, Any] | None
    domains: list[dict[str, Any]]
    industries: list[dict[str, Any]]
    level_expectations: list[dict[str, Any]]
    related_competencies: list[dict[str, Any]]
    aliases: list[str]
    publication_status: str
    is_active: bool
    version: int
    display_order: int
    evidence_count: int
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class TopicProposalReview(BaseModel):
    expected_version: int = Field(ge=1)
    action: ProposalAction
    reviewer_note: str | None = Field(default=None, max_length=2000)
    target_topic_id: int | None = Field(default=None, ge=1)
    proposal: KnowledgeTopicDraft | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "merge" and self.target_topic_id is None:
            raise ValueError("target_topic_id is required when merging a topic proposal")
        if self.action == "modify" and self.proposal is None:
            raise ValueError("proposal is required when modifying a topic proposal")
        return self


class TopicProposalResponse(BaseModel):
    id: int
    finding_id: int | None
    topic_id: int | None
    proposal_type: str
    status: str
    version: int
    original: dict[str, Any] | None
    proposed: dict[str, Any]
    ai_interpretation: str
    confidence: float | None
    evidence_status: str
    review_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_references: list[dict[str, Any]]
    potential_duplicates: list[dict[str, Any]]


class TopicProposalPage(BaseModel):
    items: list[TopicProposalResponse]
    total: int
    counts: dict[str, int]
    filters: dict[str, list[dict[str, Any]]]


class TopicPublishRequest(BaseModel):
    confirm: bool = False
    proposal_ids: list[int] | None = Field(default=None, max_length=500)
    expected_versions: dict[int, int] = Field(default_factory=dict)
    change_reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirm:
            raise ValueError("confirm must be true to publish topic changes")
        return self


class TopicPublishResponse(BaseModel):
    status: str
    published_topic_ids: list[int]
    published_proposal_ids: list[int]
    versions: dict[int, int]


class TopicHistoryResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class TopicImpactResponse(BaseModel):
    topic: KnowledgeTopicResponse
    dependencies: dict[str, int]
    potential_duplicates: list[KnowledgeTopicResponse]
