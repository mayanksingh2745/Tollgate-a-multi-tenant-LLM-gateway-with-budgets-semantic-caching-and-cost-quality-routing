import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.db import get_db
from gateway.src.services.api_key_service import verify_and_authenticate_key
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("tollgate.auth")


async def get_optional_api_key(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthenticatedContext]:
    """
    FastAPI dependency for optional Bearer API key authentication.
    If no Authorization header is provided, returns None (allowing bootstrap/public operations).
    If an Authorization header is provided, it MUST be valid or raises 401.
    """
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Authentication failed: Malformed Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = parts[1]
    result = await verify_and_authenticate_key(db, raw_key)
    if not result:
        logger.warning("Authentication failed: Secret verification failed or key expired/revoked")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key, project, tenant = result
    return AuthenticatedContext(
        api_key_id=api_key.id, project_id=project.id, tenant_id=tenant.id, role="admin"
    )


async def get_current_api_key(
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key),
) -> AuthenticatedContext:
    """
    FastAPI dependency for required Bearer API key authentication.
    Raises 401 if missing or invalid.
    """
    if not ctx:
        logger.warning("Authentication failed: Required API key missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx
