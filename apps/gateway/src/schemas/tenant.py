from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Name of the tenant")
    slug: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern="^[a-z0-9-]+$",
        description="Unique URL-friendly slug",
    )


class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
