import logging
from uuid import UUID

from fastapi import HTTPException, status
from gateway.src.schemas.tenant import TenantCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Tenant

logger = logging.getLogger("tollgate.tenant_service")


async def create_tenant(db: AsyncSession, data: TenantCreate) -> Tenant:
    # Check if slug exists
    query = select(Tenant).where(Tenant.slug == data.slug)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant slug '{data.slug}' already exists.",
        )

    tenant = Tenant(name=data.name, slug=data.slug, status="active")
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    logger.info(f"Audit Log: event=tenant.created tenant_id={tenant.id} slug={tenant.slug}")
    return tenant


async def get_tenant(db: AsyncSession, tenant_id: UUID) -> Tenant:
    query = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(query)
    tenant = result.scalar_one_or_none()

    if not tenant or tenant.status == "suspended":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return tenant
