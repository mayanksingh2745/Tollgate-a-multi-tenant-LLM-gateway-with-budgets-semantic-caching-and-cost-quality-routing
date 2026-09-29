import logging
from typing import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from gateway.src.schemas.project import ProjectCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project, Tenant

logger = logging.getLogger("tollgate.project_service")


async def create_project(db: AsyncSession, tenant_id: UUID, data: ProjectCreate) -> Project:
    # Verify tenant exists
    t_query = select(Tenant).where(Tenant.id == tenant_id)
    t_res = await db.execute(t_query)
    tenant = t_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    # Check unique slug within tenant
    p_query = select(Project).where(Project.tenant_id == tenant_id, Project.slug == data.slug)
    p_res = await db.execute(p_query)
    if p_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project slug '{data.slug}' already exists in tenant.",
        )

    project = Project(tenant_id=tenant_id, name=data.name, slug=data.slug, status="active")
    db.add(project)
    await db.commit()
    await db.refresh(project)

    logger.info(
        f"Audit Log: event=project.created tenant_id={tenant_id} project_id={project.id} slug={project.slug}"
    )
    return project


async def list_projects(db: AsyncSession, tenant_id: UUID) -> Sequence[Project]:
    query = select(Project).where(Project.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().all()


async def get_project(db: AsyncSession, tenant_id: UUID, project_id: UUID) -> Project:
    query = select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    result = await db.execute(query)
    project = result.scalar_one_or_none()

    if not project or project.status == "suspended":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project
