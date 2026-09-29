from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable key label")
    expires_at: Optional[datetime] = Field(None, description="Optional ISO expiration timestamp")


class APIKeyCreateResponse(BaseModel):
    id: UUID
    project_id: UUID
    tenant_id: UUID
    name: str
    key: str  # Raw secret key, returned ONLY once upon creation/rotation!
    key_prefix: str
    status: str
    expires_at: Optional[datetime]
    created_at: datetime


class APIKeyResponse(BaseModel):
    id: UUID
    project_id: UUID
    tenant_id: UUID
    name: str
    key_prefix: str
    status: str
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    created_at: datetime
    revoked_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
