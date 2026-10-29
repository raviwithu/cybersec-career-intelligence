from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .yahoo_mail import ALLOWED_SENDER, canonical_job_url


class MailConnectionCreate(BaseModel):
    email_address: str = Field(min_length=5, max_length=320)
    auth_method: Literal["app_password"] = "app_password"
    app_password: str = Field(min_length=1, max_length=300)
    folder: str = Field(default="Inbox", min_length=1, max_length=255)
    initial_sync_from: datetime | None = None
    automatic_sync_enabled: bool = False
    sync_interval_minutes: int = Field(default=360, ge=15, le=10080)

    @field_validator("email_address")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email_address must be a valid email address")
        return value


class MailConnectionUpdate(BaseModel):
    app_password: str | None = Field(default=None, min_length=1, max_length=300)
    folder: str | None = Field(default=None, min_length=1, max_length=255)
    initial_sync_from: datetime | None = None
    automatic_sync_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=15, le=10080)


class MailConnectionTest(BaseModel):
    email_address: str = Field(min_length=5, max_length=320)
    auth_method: Literal["app_password"] = "app_password"
    app_password: str = Field(min_length=1, max_length=300)
    folder: str = Field(default="Inbox", min_length=1, max_length=255)


class MailSyncRequest(BaseModel):
    mode: Literal["initial", "incremental", "manual"] = "manual"
    date_from: datetime | None = None
    date_to: datetime | None = None
    last_days: Literal[7, 30, 90] | None = None


class AlertSourceUpdate(BaseModel):
    subject_pattern: str = Field(default="", max_length=300)
    enabled: bool = True


class CandidateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    employer: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    work_mode: str | None = Field(default=None, max_length=40)
    job_url: str | None = Field(default=None, max_length=1000)
    description_text: str | None = Field(default=None, max_length=500_000)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("job_url")
    @classmethod
    def valid_job_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        canonical = canonical_job_url(value)
        if canonical is None:
            raise ValueError("job_url must be an HTTP or HTTPS URL without credentials")
        return canonical


class CandidateReview(BaseModel):
    note: str = Field(default="", max_length=2000)
    allow_partial: bool = False


class BulkReview(BaseModel):
    candidate_ids: list[int] = Field(min_length=1, max_length=100)
    action: Literal["approve", "reject", "defer"]
    note: str = Field(default="", max_length=2000)
    allow_partial: bool = False


class MailConnectionResponse(BaseModel):
    id: int
    email_address: str
    auth_method: str
    folder: str
    initial_sync_from: datetime | None
    automatic_sync_enabled: bool
    sync_interval_minutes: int
    next_sync_at: datetime | None
    status: str
    last_successful_sync: datetime | None
    last_sync_error: str | None
    messages_scanned: int
    alerts_detected: int
    jobs_extracted: int
    credentials_configured: bool = True


class MailConnectionTestResponse(BaseModel):
    connected: bool
    detail: str


class SyncRunResponse(BaseModel):
    id: int
    connection_id: int
    mode: str
    status: str
    mailbox: str
    started_at: datetime
    completed_at: datetime | None
    date_from: datetime | None
    date_to: datetime | None
    messages_scanned: int
    alerts_detected: int
    jobs_extracted: int
    duplicates: int
    errors: int
    error_message: str | None
    summary: dict


class CandidateResponse(BaseModel):
    id: int
    title: str
    employer: str
    location: str
    work_mode: str
    job_url: str
    source_provider: str
    received_at: datetime | None
    posted_at: datetime | None
    description_text: str
    description_complete: bool
    description_status: str
    extraction_method: str
    review_status: str
    duplicate_status: str
    duplicate_reason: str | None
    ingestion_status: str
    approved_by: str | None
    approved_at: datetime | None
    review_note: str | None
    alert_email_id: int
    alert_subject: str
    alert_sender: str
    alert_received_at: datetime | None
    provenance: list[dict]
    research_submission_id: int | None
    first_seen_at: datetime
    metadata: dict


class CandidatePage(BaseModel):
    items: list[CandidateResponse]
    total: int
    counts: dict[str, int]


class AlertSourceResponse(BaseModel):
    id: int
    name: str
    sender_address: Literal[ALLOWED_SENDER]
    subject_pattern: str
    enabled: bool
    extraction_adapter: str
    detection_count: int
    last_detected_at: datetime | None
