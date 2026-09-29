from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.db import get_db
from gateway.src.schemas.tenant import TenantCreate, TenantResponse
from gateway.src.services.tenant_service import create_tenant, get_tenant
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/tenants", tags=["Tenants"])


@router.post(
    "", response_model=TenantResponse, status_code=status.HTTP_201_CREATED, summary="Create Tenant"
)
async def create_tenant_endpoint(data: TenantCreate, db: AsyncSession = Depends(get_db)):
    """Create a new tenant entity (Bootstrap operation)."""
    return await create_tenant(db, data)


@router.get("/{tenant_id}", response_model=TenantResponse, summary="Get Tenant Details")
async def get_tenant_endpoint(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """Retrieve tenant metadata by ID with tenant isolation check."""
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return await get_tenant(db, tenant_id)
