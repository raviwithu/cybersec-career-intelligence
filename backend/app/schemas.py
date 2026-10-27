from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    target_role: str = Field(min_length=1, max_length=160)
    skills: list[str] = Field(default_factory=list, max_length=30)


class ProfileResponse(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ServiceStatus(BaseModel):
    status: str
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    services: dict[str, ServiceStatus]
