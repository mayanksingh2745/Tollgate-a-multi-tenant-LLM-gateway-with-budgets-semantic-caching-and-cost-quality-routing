"""Authentication endpoints for Tollgate Dashboard."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from gateway.src.db import get_db
from gateway.src.schemas.dashboard import (
    CurrentUserProfile,
    LoginRequest,
    LoginResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import APIKey, Project, Tenant, User
from tollgate_core.security import generate_api_key, verify_password

logger = logging.getLogger("tollgate.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Dashboard User Login",
    responses={
        200: {"description": "Authentication successful"},
        401: {"description": "Invalid credentials"},
        403: {"description": "Account suspended"},
    },
)
async def login_endpoint(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticates a tenant user via email and password.
    Returns a secure session bearer token backed by the existing API key architecture.
    """
    stmt = (
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.email == data.email)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        logger.warning(f"Login failed: User not found for email {data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user, tenant = row

    if user.status != "active" or tenant.status != "active":
        logger.warning(f"Login rejected: Inactive user or tenant: user={user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account or tenant is inactive or suspended.",
        )

    if not verify_password(data.password, user.password_hash):
        logger.warning(f"Login failed: Invalid password for user {user.id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Find an active project for this tenant to bind session key to
    p_stmt = (
        select(Project).where(Project.tenant_id == tenant.id).order_by(Project.created_at.asc())
    )
    projects = (await db.execute(p_stmt)).scalars().all()
    if not projects:
        # Create a default project if none exists
        default_proj = Project(
            tenant_id=tenant.id,
            name="Default Project",
            slug=f"default-{tenant.slug}",
            status="active",
        )
        db.add(default_proj)
        await db.commit()
        await db.refresh(default_proj)
        projects = [default_proj]

    primary_project = projects[0]

    # Generate a session key for dashboard usage
    raw_key, key_prefix, key_hash = generate_api_key()
    session_key = APIKey(
        project_id=primary_project.id,
        tenant_id=tenant.id,
        user_id=user.id,
        name=f"Dashboard Session ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')})",
        key_prefix=key_prefix,
        key_hash=key_hash,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(session_key)
    await db.commit()

    logger.info(
        f"User logged in successfully: user_id={user.id} tenant_id={tenant.id} role={user.role}"
    )

    return LoginResponse(
        token=raw_key,
        token_type="bearer",
        user=CurrentUserProfile(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            project_id=None,
            projects=[{"id": p.id, "name": p.name, "slug": p.slug} for p in projects],
        ),
    )
