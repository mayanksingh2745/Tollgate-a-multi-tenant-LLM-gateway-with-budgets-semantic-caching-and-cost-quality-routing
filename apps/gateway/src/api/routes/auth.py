"""Authentication endpoints for Tollgate Dashboard."""

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from gateway.src.db import get_db
from gateway.src.schemas.dashboard import (
    CurrentUserProfile,
    LoginRequest,
    LoginResponse,
    SignupRequest,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import APIKey, Project, Tenant, User
from tollgate_core.security import generate_api_key, hash_password, verify_password


def _tenant_slug(name: str) -> str:
    """Create a safe, compact tenant slug from the tenant name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    slug = slug[:46].rstrip("-")
    return slug or "tenant"


logger = logging.getLogger("tollgate.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Tenant Account",
    responses={
        201: {"description": "Account created and authenticated"},
        409: {"description": "Account already exists"},
    },
)
async def signup_endpoint(data: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Create a new tenant and its first owner user."""
    email = data.email.strip().lower()

    existing_user = await db.execute(select(User).where(User.email == email).limit(1))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    tenant_slug = _tenant_slug(data.tenant_name)

    slug_result = await db.execute(select(Tenant.slug).where(Tenant.slug == tenant_slug).limit(1))
    if slug_result.scalar_one_or_none():
        from uuid import uuid4

        tenant_slug = f"{tenant_slug[:37].rstrip('-')}-{uuid4().hex[:8]}"

    tenant = Tenant(
        name=data.tenant_name.strip(),
        slug=tenant_slug,
        status="active",
    )
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        name=data.name.strip(),
        email=email,
        password_hash=hash_password(data.password),
        role="owner",
        status="active",
    )
    db.add(user)

    default_project = Project(
        tenant_id=tenant.id,
        name="Default Project",
        slug=f"default-{tenant.slug}",
        status="active",
    )
    db.add(default_project)
    await db.flush()

    raw_key, key_prefix, key_hash = generate_api_key()
    session_key = APIKey(
        project_id=default_project.id,
        tenant_id=tenant.id,
        user_id=user.id,
        name=f"Dashboard Session ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')})",
        key_prefix=key_prefix,
        key_hash=key_hash,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(session_key)

    try:
        await db.commit()
    except IntegrityError as err:
        await db.rollback()
        logger.exception("Signup failed due to a database integrity error.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to create the account because the requested details already exist.",
        ) from err

    logger.info(f"Tenant signup successful: user_id={user.id} tenant_id={tenant.id}")

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
            project_id=default_project.id,
            projects=[
                {
                    "id": default_project.id,
                    "name": default_project.name,
                    "slug": default_project.slug,
                }
            ],
        ),
    )


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
