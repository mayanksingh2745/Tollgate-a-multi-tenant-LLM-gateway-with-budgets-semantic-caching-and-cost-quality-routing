import logging
from typing import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from gateway.src.schemas.user import UserCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Tenant, User
from tollgate_core.security import hash_password

logger = logging.getLogger("tollgate.user_service")


async def create_user(db: AsyncSession, tenant_id: UUID, data: UserCreate) -> User:
    # Verify tenant exists
    t_query = select(Tenant).where(Tenant.id == tenant_id)
    t_res = await db.execute(t_query)
    tenant = t_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    # Check unique constraint (tenant_id, email)
    u_query = select(User).where(User.tenant_id == tenant_id, User.email == data.email)
    u_res = await db.execute(u_query)
    if u_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists in the tenant.",
        )

    pwd_hash = hash_password(data.password)
    user = User(
        tenant_id=tenant_id,
        email=data.email,
        name=data.name,
        password_hash=pwd_hash,
        role=data.role,
        status="active",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(
        f"Audit Log: event=user.created tenant_id={tenant_id} user_id={user.id} role={user.role}"
    )
    return user


async def list_users(db: AsyncSession, tenant_id: UUID) -> Sequence[User]:
    query = select(User).where(User.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().all()
