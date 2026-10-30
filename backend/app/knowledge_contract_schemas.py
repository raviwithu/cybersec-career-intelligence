from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .phase6_schemas import validate_http_url

SECTION_TYPES = (
    "overview",
    "how_it_works",
    "attack_surfaces",
    "mitigations",
    "real_world_examples",
    "references",
    "career_level_guidance",
    "code_examples",
    "architecture",
)
# Coverage reports the core sections only; code examples and architecture diagrams are optional for a topic.
CORE_SECTION_TYPES = SECTION_TYPES[:7]
SectionType = Literal["overview", "how_it_works", "attack_surfaces", "mitigations", "real_world_examples", "references", "career_level_guidance", "code_examples", "architecture"]
# Stored relationship types (D4). Inverses such as "used by" are display labels only, never stored.
RELATIONSHIP_TYPES = ("prerequisite", "related", "specialization", "dependency", "mitigated_by", "tested_by")
ProposalAction = Literal[
    "CREATE_TOPIC", "UPDATE_TOPIC", "ADD_SECTION", "UPDATE_SECTION", "ADD_ATTACK_SURFACE", "ADD_MITIGATION",
    "ADD_DIAGRAM", "ADD_REFERENCE", "ADD_VULNERABILITY_EXAMPLE", "ADD_TOPIC_RELATIONSHIP", "UPDATE_CAREER_LEVEL_GUIDANCE",
    # Knowledge map actions (KM-4); payloads are validated in knowledge_map_proposals.py.
    "PLACE_TOPIC", "UNPLACE_TOPIC", "MOVE_TOPIC", "REORDER_TOPICS", "SET_PARENT_TOPIC", "REMOVE_TOPIC_RELATIONSHIP",
    "DEACTIVATE_TOPIC", "UPDATE_CAREER_LEVELS", "RESTORE_VERSION",
]
ProposalSourceType = Literal["manual", "jsearch", "ai", "rag", "connector"]
ReviewAction = Literal["approve", "modify", "merge", "reject", "defer"]
ProposalStatus = Literal["draft", "review", "approved", "published", "rejected", "deferred"]
VerificationStatus = Literal["unverified", "verified", "rejected", "restricted", "ai_derived", "authoritative"]


def _clean_text(value: str) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    if re.search(r"<\s*(script|iframe|object|embed)\b", value, re.I):
        raise ValueError("HTML executable elements are not permitted in knowledge content")
    return value.strip()


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, dict):
        return {_clean_text(str(key)): _clean_value(child) for key, child in value.items()}
    return value


def validate_proposed_content_urls(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if isinstance(child, str) and (normalized_key in {"reference", "url", "href", "link"} or normalized_key.endswith("_url")):
                validate_http_url(child)
            validate_proposed_content_urls(child)
    elif isinstance(value, list):
        for child in value:
            validate_proposed_content_urls(child)


class KnowledgeSourceReference(BaseModel):
    source_type: str = Field(min_length=1, max_length=60)
    document_identifier: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    author: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    document_version: str | None = Field(default=None, max_length=120)
    publication_date: date | None = None
    locator: str | None = Field(default=None, max_length=300)
    excerpt: str | None = Field(default=None, max_length=6000)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    verification_status: VerificationStatus = "unverified"
    access_scope: Literal["public", "private", "restricted"] = "public"
    is_private: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return validate_http_url(value) if value else value

    @field_validator("title", "document_identifier", "author", "publisher", "document_version", "locator", "excerpt", mode="before")
    @classmethod
    def clean_fields(cls, value: Any) -> Any:
        return _clean_text(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_access(self):
        if self.is_private and self.access_scope == "public":
            self.access_scope = "private"
        return self


class KnowledgeProposalCreate(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    source_type: ProposalSourceType
    topic_id: int | None = Field(default=None, ge=1)
    topic_key: str | None = Field(default=None, min_length=1, max_length=240)
    topic_name: str | None = Field(default=None, min_length=1, max_length=240)
    action: ProposalAction
    section: SectionType | None = None
    proposed_content: dict[str, Any] = Field(default_factory=dict)
    change_reason: str = Field(default="", max_length=500)
    submit_for_review: bool = True
    references: list[KnowledgeSourceReference] = Field(default_factory=list, max_length=30)

    @field_validator("topic_name", "topic_key", "change_reason", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> Any:
        return _clean_text(value) if isinstance(value, str) else value

    @field_validator("proposed_content", mode="before")
    @classmethod
    def clean_content(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("proposed_content must be an object")
        cleaned = _clean_value(value)
        validate_proposed_content_urls(cleaned)
        if len(json.dumps(cleaned, ensure_ascii=False)) > 200_000:
            raise ValueError("proposed_content exceeds the permitted size")
        return cleaned

    @model_validator(mode="after")
    def validate_target(self):
        if self.action == "CREATE_TOPIC" and self.topic_id is not None:
            raise ValueError("CREATE_TOPIC must not include topic_id")
        if self.action != "CREATE_TOPIC" and self.topic_id is None and not self.topic_key:
            raise ValueError("topic_id or topic_key is required for this proposal action")
        requires_section = self.action in {"ADD_SECTION", "UPDATE_SECTION", "ADD_ATTACK_SURFACE", "ADD_MITIGATION", "ADD_DIAGRAM", "ADD_REFERENCE", "ADD_VULNERABILITY_EXAMPLE", "UPDATE_CAREER_LEVEL_GUIDANCE"}
        if requires_section and not self.section:
            section_map = {
                "ADD_ATTACK_SURFACE": "attack_surfaces", "ADD_MITIGATION": "mitigations", "ADD_DIAGRAM": "how_it_works",
                "ADD_REFERENCE": "references", "ADD_VULNERABILITY_EXAMPLE": "real_world_examples", "UPDATE_CAREER_LEVEL_GUIDANCE": "career_level_guidance",
            }
            self.section = section_map.get(self.action, self.section)
        map_change = self.action in {"PLACE_TOPIC", "UNPLACE_TOPIC", "MOVE_TOPIC", "REORDER_TOPICS", "SET_PARENT_TOPIC", "REMOVE_TOPIC_RELATIONSHIP", "DEACTIVATE_TOPIC", "UPDATE_CAREER_LEVELS", "RESTORE_VERSION"}
        if (map_change or (self.action == "CREATE_TOPIC" and self.proposed_content.get("placements"))) and not self.change_reason.strip():
            raise ValueError("change_reason is required for knowledge map changes")
        if self.action == "ADD_TOPIC_RELATIONSHIP":
            target_id = self.proposed_content.get("target_topic_id")
            if not isinstance(target_id, int) or isinstance(target_id, bool) or target_id < 1:
                raise ValueError("target_topic_id must be a positive integer for topic relationships")
            if self.proposed_content.get("relationship_type", "related") not in RELATIONSHIP_TYPES:
                raise ValueError(f"relationship_type must be one of: {', '.join(RELATIONSHIP_TYPES)}")
            if self.topic_id is not None and target_id == self.topic_id:
                raise ValueError("A topic cannot relate to itself")
        return self


class KnowledgeProposalReview(BaseModel):
    expected_version: int = Field(ge=1)
    action: ReviewAction
    reviewer_note: str = Field(default="", max_length=2000)
    proposed_content: dict[str, Any] | None = None
    verified_source_ids: list[int] = Field(default_factory=list, max_length=30)
    merge_target_topic_id: int | None = Field(default=None, ge=1)

    @field_validator("proposed_content", mode="before")
    @classmethod
    def clean_review_content(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("proposed_content must be an object")
        cleaned = _clean_value(value)
        validate_proposed_content_urls(cleaned)
        if len(json.dumps(cleaned, ensure_ascii=False)) > 200_000:
            raise ValueError("proposed_content exceeds the permitted size")
        return cleaned

    @model_validator(mode="after")
    def validate_review(self):
        if self.action == "modify" and self.proposed_content is None:
            raise ValueError("proposed_content is required when modifying a proposal")
        if self.action == "merge" and self.merge_target_topic_id is None:
            raise ValueError("merge_target_topic_id is required when merging a proposal")
        return self


class KnowledgeProposalPublish(BaseModel):
    confirm: Literal[True]
    expected_version: int = Field(ge=1)
    change_reason: str = Field(default="", max_length=500)


class KnowledgeSectionVersionResponse(BaseModel):
    version: int
    status: str
    content: dict[str, Any]
    reason: str
    actor: str
    created_at: datetime
    published_at: datetime | None


class KnowledgeSectionResponse(BaseModel):
    section_type: str
    status: str
    published_version: int
    content: dict[str, Any]
    updated_at: datetime
    versions: list[KnowledgeSectionVersionResponse] = Field(default_factory=list)


class KnowledgeCoverageItem(BaseModel):
    section_type: str
    status: Literal["missing", "draft", "pending_review", "published"]
    published_version: int = 0


class KnowledgeCoverageResponse(BaseModel):
    topic_id: int
    topic_key: str
    items: list[KnowledgeCoverageItem]
    complete: bool


class KnowledgeTopicLevelResponse(BaseModel):
    career_level: dict[str, Any]
    industry: dict[str, Any] | None = None
    expectation: str
    practical_capability: str


class KnowledgePublicTopicResponse(BaseModel):
    id: int
    topic_key: str
    name: str
    slug: str
    description: str
    sections: list[KnowledgeSectionResponse]
    coverage: KnowledgeCoverageResponse
    related_topics: list[dict[str, Any]] = Field(default_factory=list)
    # Per career level: expectation is the knowledge, practical_capability the practical skills. Active levels only.
    level_expectations: list[KnowledgeTopicLevelResponse] = Field(default_factory=list)
    last_updated: datetime | None
    # Admin responses only (Knowledge Map Management): lifecycle, hierarchy and aliases for duplicate checks.
    is_active: bool | None = None
    publication_status: str | None = None
    parent_topic_id: int | None = None
    aliases: list[str] | None = None


class KnowledgeProposalResponse(BaseModel):
    id: int
    schema_version: str
    source_type: str
    topic_id: int | None
    topic_key: str | None
    action: str
    section: str | None
    status: str
    version: int
    base_section_version: int
    merge_target_topic_id: int | None = None
    original_content: dict[str, Any] | None
    proposed_content: dict[str, Any]
    change_reason: str
    created_at: datetime
    updated_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    published_at: datetime | None
    submitted_by: str | None = None
    references: list[dict[str, Any]] = Field(default_factory=list)
    review_decisions: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeProposalPage(BaseModel):
    items: list[KnowledgeProposalResponse]
    total: int
    counts: dict[str, int]


class KnowledgeReviewFilters(BaseModel):
    source_type: str | None = None
    domain_id: int | None = None
    topic_id: int | None = None
    action: str | None = None
    status: str | None = None
    submitted_after: datetime | None = None
    submitted_before: datetime | None = None


class KnowledgeMapPreviewBranch(BaseModel):
    domain_id: int
    domain_name: str
    map_branch: str
    label: str
    before: list[dict[str, Any]]
    after: list[dict[str, Any]]


class KnowledgeMapPreviewResponse(BaseModel):
    proposal_id: int
    action: str
    status: str
    branches: list[KnowledgeMapPreviewBranch] = Field(default_factory=list)
    message: str | None = None
