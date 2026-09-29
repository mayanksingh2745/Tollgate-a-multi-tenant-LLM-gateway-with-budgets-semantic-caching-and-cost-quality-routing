import logging
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from gateway.src.schemas.api_key import APIKeyCreate, APIKeyCreateResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import APIKey, Project, Tenant, User
from tollgate_core.security import (
    API_KEY_PREFIX,
    PREFIX_LENGTH,
    generate_api_key,
    verify_api_key_hash,
)

logger = logging.getLogger("tollgate.api_key_service")


async def create_api_key(
    db: AsyncSession, project_id: UUID, tenant_id: UUID, data: APIKeyCreate
) -> APIKeyCreateResponse:
    # Verify project belongs to tenant
    p_query = select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    p_res = await db.execute(p_query)
    project = p_res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if data.user_id is not None:
        u_query = select(User).where(User.id == data.user_id, User.tenant_id == tenant_id)
        u_res = await db.execute(u_query)
        user = u_res.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        if user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create API key for inactive user.",
            )

    raw_key, key_prefix, key_hash = generate_api_key()

    expires_at_val = data.expires_at
    if isinstance(expires_at_val, str):
        expires_at_val = datetime.fromisoformat(expires_at_val)

    api_key = APIKey(
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=data.user_id,
        name=data.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        status="active",
        expires_at=expires_at_val,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info(
        f"Audit Log: event=api_key.created tenant_id={tenant_id} project_id={project_id} api_key_id={api_key.id} user_id={api_key.user_id}"
    )

    return APIKeyCreateResponse(
        id=api_key.id,
        project_id=api_key.project_id,
        tenant_id=api_key.tenant_id,
        user_id=api_key.user_id,
        name=api_key.name,
        key=raw_key,  # Raw key returned ONLY once!
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


async def list_api_keys(db: AsyncSession, project_id: UUID, tenant_id: UUID) -> Sequence[APIKey]:
    # Verify project belongs to tenant
    p_query = select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    p_res = await db.execute(p_query)
    if not p_res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    query = select(APIKey).where(APIKey.project_id == project_id, APIKey.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().all()


async def revoke_api_key(db: AsyncSession, api_key_id: UUID, tenant_id: UUID) -> APIKey:
    query = select(APIKey).where(APIKey.id == api_key_id, APIKey.tenant_id == tenant_id)
    result = await db.execute(query)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found.")

    if api_key.status != "revoked":
        api_key.status = "revoked"
        api_key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(api_key)

        logger.info(
            f"Audit Log: event=api_key.revoked tenant_id={tenant_id} api_key_id={api_key_id}"
        )

    return api_key


async def rotate_api_key(
    db: AsyncSession, api_key_id: UUID, tenant_id: UUID
) -> APIKeyCreateResponse:
    # Revoke old key
    old_key = await revoke_api_key(db, api_key_id, tenant_id)

    # Generate new key for same project and tenant
    create_data = APIKeyCreate(
        name=f"{old_key.name} (Rotated)",
        expires_at=old_key.expires_at,
        user_id=old_key.user_id,
    )
    new_key_response = await create_api_key(db, old_key.project_id, tenant_id, create_data)

    logger.info(
        f"Audit Log: event=api_key.rotated tenant_id={tenant_id} old_api_key_id={api_key_id} new_api_key_id={new_key_response.id}"
    )

    return new_key_response


async def verify_and_authenticate_key(
    db: AsyncSession, raw_key: str
) -> Optional[Tuple[APIKey, Project, Tenant, Optional[User]]]:
    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        return None

    prefix = raw_key[:PREFIX_LENGTH]

    # Prefix-based index lookup with optional user join
    query = (
        select(APIKey, Project, Tenant, User)
        .join(Project, APIKey.project_id == Project.id)
        .join(Tenant, APIKey.tenant_id == Tenant.id)
        .outerjoin(User, APIKey.user_id == User.id)
        .where(
            APIKey.key_prefix == prefix,
            APIKey.status == "active",
            Project.status == "active",
            Tenant.status == "active",
        )
    )
    result = await db.execute(query)
    records = result.all()

    now = datetime.now(timezone.utc)

    for api_key, project, tenant, user in records:
        if verify_api_key_hash(raw_key, api_key.key_hash):
            # If key is associated with a user, ensure user is valid, belongs to tenant, and is active
            if api_key.user_id is not None:
                if not user or user.tenant_id != tenant.id or user.status != "active":
                    logger.warning(
                        f"Authentication failed: Associated user {api_key.user_id} is inactive, mismatched, or not found"
                    )
                    return None

            # Expiration check
            if api_key.expires_at:
                exp_at = api_key.expires_at
                if exp_at.tzinfo is None:
                    exp_at = exp_at.replace(tzinfo=timezone.utc)
                if exp_at <= now:
                    api_key.status = "expired"
                    await db.commit()
                    logger.info(
                        f"Audit Log: event=api_key.expired tenant_id={tenant.id} api_key_id={api_key.id}"
                    )
                    return None

            # Update last_used_at
            api_key.last_used_at = now
            await db.commit()

            return api_key, project, tenant, user

    return None
