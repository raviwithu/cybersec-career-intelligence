from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

SOURCE_TYPES = Literal["public_api", "html", "rss", "url_collection"]
FREQUENCIES = Literal["manual", "daily", "weekly", "interval"]


def validate_http_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("endpoint_url must be a valid HTTP or HTTPS URL without credentials or fragments")
    try:
        address = ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("private, local, reserved, and metadata destinations are not permitted")
    return value.strip()


def reject_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(marker in str(key).casefold() for marker in ("password", "secret", "token", "api_key", "authorization")):
                raise ValueError("source configuration must not contain credentials or secrets")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)


class AutomatedSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: SOURCE_TYPES
    endpoint_url: str = Field(min_length=1, max_length=1000)
    enabled: bool = True
    collection_frequency: FREQUENCIES = "manual"
    interval_minutes: int = Field(default=1440, ge=5, le=10080)
    applicable_industries: list[str] = Field(default_factory=list, max_length=20)
    applicable_domains: list[str] = Field(default_factory=list, max_length=20)
    applicable_career_levels: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_configuration(self):
        self.endpoint_url = validate_http_url(self.endpoint_url)
        reject_secrets(self.configuration)
        if self.source_type == "url_collection":
            urls = self.configuration.get("urls")
            if not isinstance(urls, list) or not 1 <= len(urls) <= 100:
                raise ValueError("url_collection configuration.urls must contain between one and one hundred URLs")
            self.configuration["urls"] = [validate_http_url(str(url)) for url in urls]
        if self.source_type == "public_api" and self.configuration.get("method", "GET").upper() != "GET":
            raise ValueError("public_api currently supports only GET endpoints")
        return self


class AutomatedSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint_url: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
    collection_frequency: FREQUENCIES | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    applicable_industries: list[str] | None = Field(default=None, max_length=20)
    applicable_domains: list[str] | None = Field(default=None, max_length=20)
    applicable_career_levels: list[str] | None = Field(default=None, max_length=20)
    keywords: list[str] | None = Field(default=None, max_length=30)
    configuration: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.endpoint_url is not None:
            self.endpoint_url = validate_http_url(self.endpoint_url)
        if self.configuration is not None:
            reject_secrets(self.configuration)
        if self.configuration is not None and "urls" in self.configuration:
            urls = self.configuration["urls"]
            if not isinstance(urls, list) or not 1 <= len(urls) <= 100:
                raise ValueError("configuration.urls must contain between one and one hundred URLs")
            self.configuration["urls"] = [validate_http_url(str(url)) for url in urls]
        return self


class ScheduleRequest(BaseModel):
    frequency: FREQUENCIES = "daily"
    interval_minutes: int = Field(default=1440, ge=5, le=10080)
    enabled: bool = True
    paused: bool = False


class RunStartRequest(BaseModel):
    source_ids: list[int] | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=160)
    domain: str | None = Field(default=None, max_length=160)
    career_level: str | None = Field(default=None, max_length=80)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    date_from: datetime | None = None
    date_to: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot exceed date_to")
        return self


class AutomatedSourceResponse(BaseModel):
    id: int
    name: str
    source_type: str
    endpoint_url: str
    enabled: bool
    collection_frequency: str
    interval_minutes: int
    applicable_industries: list[str]
    applicable_domains: list[str]
    applicable_career_levels: list[str]
    keywords: list[str]
    configuration: dict[str, Any]
    collection_status: str
    last_successful_collection: datetime | None
    last_attempted_collection: datetime | None
    next_run_at: datetime | None
    last_error: str | None
    schedule: dict[str, Any] | None = None


class ResearchRunResponse(BaseModel):
    id: int
    trigger: str
    status: str
    requested_source_ids: list[int]
    target_filters: dict[str, Any]
    sources_collected: int
    sources_analyzed: int
    duplicates_skipped: int
    failed_collections: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    summary: dict[str, Any]
    created_by: str
    created_at: datetime


class CollectionAttemptResponse(BaseModel):
    id: int
    run_id: int
    source_id: int
    status: str
    retry_count: int
    http_status: int | None
    items_discovered: int
    items_collected: int
    items_analyzed: int
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class AutomatedDashboardResponse(BaseModel):
    overview: dict[str, Any]
    recent_runs: list[ResearchRunResponse]
    pending_findings: int
    change_events: list[dict[str, Any]]


class CoverageCell(BaseModel):
    industry: dict[str, Any]
    domain: dict[str, Any]
    career_level: dict[str, Any]
    evidence_count: int
    source_count: int
    label: Literal["none", "limited", "adequate"]


class CoverageResponse(BaseModel):
    thresholds: dict[str, int]
    cells: list[CoverageCell]
    under_researched: list[CoverageCell]


class AutomatedChangeResponse(BaseModel):
    id: int
    source_id: int
    run_id: int | None
    previous_version_id: int | None
    current_version_id: int
    change_type: str
    summary: dict[str, Any]
    status: str
    detected_at: datetime
    source_name: str | None = None
    source_url: str | None = None
