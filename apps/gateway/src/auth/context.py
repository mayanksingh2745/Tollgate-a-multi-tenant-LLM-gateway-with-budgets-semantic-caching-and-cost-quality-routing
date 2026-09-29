from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AuthenticatedContext(BaseModel):
    api_key_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    tenant_id: UUID
    project_id: Optional[UUID] = None
    role: str = "admin"  # "owner" | "admin" | "viewer"
