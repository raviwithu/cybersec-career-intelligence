from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


TaxonomyType = Literal["domain", "industry", "career_level", "category"]
CareerTrack = Literal["technical", "management", "shared"]


class TaxonomyAliasInput(BaseModel):
    alias: str = Field(min_length=1, max_length=180)
    requires_context: bool = False
    context_hint: str | None = Field(default=None, max_length=255)


class TaxonomyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    slug: str | None = Field(default=None, max_length=180)
    description: str = Field(default="", max_length=4000)
    parent_id: int | None = Field(default=None, ge=1)
    career_track: CareerTrack = "shared"
    display_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True
    aliases: list[TaxonomyAliasInput] = Field(default_factory=list, max_length=100)


class TaxonomyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    slug: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    parent_id: int | None = Field(default=None, ge=1)
    career_track: CareerTrack | None = None
    display_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    aliases: list[TaxonomyAliasInput] | None = Field(default=None, max_length=100)
    expected_updated_at: datetime | None = None


class TaxonomyMergeRequest(BaseModel):
    target_id: int = Field(ge=1)
    confirm: bool = False
    expected_updated_at: datetime | None = None

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirm:
            raise ValueError("confirm must be true to merge taxonomy entries")
        return self


class TaxonomyEntryResponse(BaseModel):
    id: int
    taxonomy_type: TaxonomyType
    name: str
    slug: str
    description: str
    parent_id: int | None = None
    parent_name: str | None = None
    career_track: str | None = None
    display_order: int
    is_active: bool
    aliases: list[TaxonomyAliasInput] = Field(default_factory=list)
    children: list["TaxonomyEntryResponse"] = Field(default_factory=list)
    dependencies: dict[str, int] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaxonomyManagementResponse(BaseModel):
    items: list[TaxonomyEntryResponse]
    taxonomy_type: TaxonomyType | None = None


class TaxonomyImpactResponse(BaseModel):
    taxonomy_type: TaxonomyType
    entry: TaxonomyEntryResponse
    dependencies: dict[str, int]
    blockers: list[str] = Field(default_factory=list)
    merge_targets: list[TaxonomyEntryResponse] = Field(default_factory=list)


class TaxonomyHistoryResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    taxonomy_type: TaxonomyType
    entry_id: int
    action: str
    previous_values: dict | None = None
    updated_values: dict | None = None
    actor: str
    merge_source_id: int | None = None
    merge_target_id: int | None = None
    created_at: datetime


class TaxonomyHistoryPage(BaseModel):
    items: list[TaxonomyHistoryResponse]
    total: int
