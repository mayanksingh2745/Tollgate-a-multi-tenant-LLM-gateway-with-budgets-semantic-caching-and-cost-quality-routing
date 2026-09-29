from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.auth.permissions import verify_role_permissions
from gateway.src.cache import exact_cache, semantic_cache
from gateway.src.db import get_db
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project

router = APIRouter(prefix="/api/v1", tags=["Cache Management"])


class SemanticCacheMetadataResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    provider: str
    model: str
    request_fingerprint: str
    embedding_model: str
    embedding_version: str
    created_at: str
    expires_at: str
    last_hit_at: Optional[str] = None
    hit_count: int


@router.delete(
    "/projects/{project_id}/cache",
    summary="Invalidate Project Exact & Semantic Response Cache",
    responses={
        200: {"description": "Project cache invalidated successfully"},
        401: {"description": "Authentication failure"},
        403: {"description": "Insufficient permissions (requires owner or admin)"},
        404: {"description": "Project not found"},
    },
)
async def invalidate_project_cache(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """
    Atomically clears the exact response cache (via generation counter) and
    purges indexed semantic cache entries for the specified project.
    Strictly isolated to caller's tenant. Requires 'owner' or 'admin' role.
    """
    verify_role_permissions(ctx, ["owner", "admin"])

    if ctx.project_id and ctx.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: API key is scoped to a different project.",
        )

    # Verify project belongs to caller's tenant
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id)
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    new_version = await exact_cache.invalidate_project(
        tenant_id=ctx.tenant_id, project_id=project_id
    )
    semantic_count = await semantic_cache.invalidate_project(
        tenant_id=ctx.tenant_id, project_id=project_id, session=db
    )

    return {
        "status": "success",
        "message": f"Cache invalidated for project {project_id}.",
        "cache_version": new_version,
        "semantic_entries_invalidated": semantic_count,
    }


@router.get(
    "/projects/{project_id}/cache/semantic",
    summary="Inspect Semantic Cache Metadata",
    response_model=List[SemanticCacheMetadataResponse],
    responses={
        200: {"description": "List of semantic cache entries metadata"},
        401: {"description": "Authentication failure"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Project not found"},
    },
)
async def list_project_semantic_cache(
    project_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """
    Read-only inspection of semantic cache entries metadata.
    Never exposes raw prompts, model responses, or embedding vectors.
    """
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])

    if ctx.project_id and ctx.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: API key is scoped to a different project.",
        )

    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id)
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    entries = await semantic_cache.backend.list_entries(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        limit=limit,
        session=db,
    )

    return [SemanticCacheMetadataResponse(**e) for e in entries]
