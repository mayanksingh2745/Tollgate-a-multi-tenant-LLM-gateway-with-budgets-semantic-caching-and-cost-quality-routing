import asyncio
import logging
import math
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from gateway.src.config import settings
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import SemanticCacheEntry

logger = logging.getLogger("tollgate.cache.semantic.backend")


@dataclass
class SemanticCandidate:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    provider: str
    model: str
    request_fingerprint: str
    response_cache_key: str
    distance: float
    similarity: float
    expires_at: datetime


class BaseSemanticCacheBackend(ABC):
    @abstractmethod
    async def search_candidates(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        model: str,
        fingerprint: str,
        query_embedding: List[float],
        top_k: int,
        session: Optional[AsyncSession] = None,
    ) -> List[SemanticCandidate]:
        pass

    @abstractmethod
    async def store_entry(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        model: str,
        fingerprint: str,
        semantic_representation: str,
        embedding: List[float],
        embedding_model: str,
        embedding_version: str,
        response_cache_key: str,
        expires_at: datetime,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        pass

    @abstractmethod
    async def delete_entry(self, entry_id: UUID, session: Optional[AsyncSession] = None) -> bool:
        pass

    @abstractmethod
    async def update_hit(self, entry_id: UUID, session: Optional[AsyncSession] = None) -> None:
        pass

    @abstractmethod
    async def invalidate_project(
        self, tenant_id: UUID, project_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        pass

    @abstractmethod
    async def invalidate_tenant(
        self, tenant_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        pass

    @abstractmethod
    async def list_entries(
        self,
        tenant_id: UUID,
        project_id: UUID,
        limit: int = 50,
        session: Optional[AsyncSession] = None,
    ) -> List[dict]:
        pass


class PgvectorSemanticCacheBackend(BaseSemanticCacheBackend):
    """
    Production backend utilizing PostgreSQL with pgvector for nearest-neighbor search.
    Includes transparent Python-based cosine calculation fallback if SQLite is used in tests.
    """

    @staticmethod
    def _cosine_distance(v1: List[float], v2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2, strict=True))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 1.0
        sim = dot / (norm1 * norm2)
        return max(0.0, min(2.0, 1.0 - sim))

    async def search_candidates(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        model: str,
        fingerprint: str,
        query_embedding: List[float],
        top_k: int,
        session: Optional[AsyncSession] = None,
    ) -> List[SemanticCandidate]:
        if session is None:
            logger.warning("Pgvector backend called without database session; returning empty")
            return []

        now = datetime.now(timezone.utc)
        bounded_top_k = min(top_k, settings.semantic_cache_max_candidates)

        # Attempt PostgreSQL pgvector cosine distance query
        try:
            stmt = (
                select(
                    SemanticCacheEntry.id,
                    SemanticCacheEntry.tenant_id,
                    SemanticCacheEntry.project_id,
                    SemanticCacheEntry.provider,
                    SemanticCacheEntry.model,
                    SemanticCacheEntry.request_fingerprint,
                    SemanticCacheEntry.response_cache_key,
                    SemanticCacheEntry.expires_at,
                    SemanticCacheEntry.embedding.cosine_distance(query_embedding).label("distance"),
                )
                .where(
                    SemanticCacheEntry.tenant_id == tenant_id,
                    SemanticCacheEntry.project_id == project_id,
                    SemanticCacheEntry.provider == provider,
                    SemanticCacheEntry.model == model,
                    SemanticCacheEntry.request_fingerprint == fingerprint,
                    SemanticCacheEntry.expires_at > now,
                )
                .order_by("distance")
                .limit(bounded_top_k)
            )
            result = await session.execute(stmt)
            rows = result.all()

            candidates = []
            for row in rows:
                dist = float(row.distance)
                sim = 1.0 - dist
                candidates.append(
                    SemanticCandidate(
                        id=row.id,
                        tenant_id=row.tenant_id,
                        project_id=row.project_id,
                        provider=row.provider,
                        model=row.model,
                        request_fingerprint=row.request_fingerprint,
                        response_cache_key=row.response_cache_key,
                        distance=dist,
                        similarity=sim,
                        expires_at=row.expires_at,
                    )
                )
            return candidates
        except Exception as pg_err:
            # Fallback for environments without native pgvector operator (e.g. SQLite memory DB in tests)
            logger.debug(f"pgvector query fallback (likely non-pg DB): {pg_err}")
            stmt_fallback = select(SemanticCacheEntry).where(
                SemanticCacheEntry.tenant_id == tenant_id,
                SemanticCacheEntry.project_id == project_id,
                SemanticCacheEntry.provider == provider,
                SemanticCacheEntry.model == model,
                SemanticCacheEntry.request_fingerprint == fingerprint,
                SemanticCacheEntry.expires_at > now,
            )
            res = await session.execute(stmt_fallback)
            entries = res.scalars().all()

            scored = []
            for ent in entries:
                dist = self._cosine_distance(query_embedding, ent.embedding)
                sim = 1.0 - dist
                scored.append(
                    SemanticCandidate(
                        id=ent.id,
                        tenant_id=ent.tenant_id,
                        project_id=ent.project_id,
                        provider=ent.provider,
                        model=ent.model,
                        request_fingerprint=ent.request_fingerprint,
                        response_cache_key=ent.response_cache_key,
                        distance=dist,
                        similarity=sim,
                        expires_at=ent.expires_at,
                    )
                )
            scored.sort(key=lambda c: c.distance)
            return scored[:bounded_top_k]

    async def store_entry(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        model: str,
        fingerprint: str,
        semantic_representation: str,
        embedding: List[float],
        embedding_model: str,
        embedding_version: str,
        response_cache_key: str,
        expires_at: datetime,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        if session is None:
            return False

        entry = SemanticCacheEntry(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
            model=model,
            request_fingerprint=fingerprint,
            semantic_representation=semantic_representation,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            response_cache_key=response_cache_key,
            expires_at=expires_at,
            hit_count=0,
        )
        session.add(entry)
        await session.commit()
        return True

    async def delete_entry(self, entry_id: UUID, session: Optional[AsyncSession] = None) -> bool:
        if session is None:
            return False
        stmt = delete(SemanticCacheEntry).where(SemanticCacheEntry.id == entry_id)
        res = await session.execute(stmt)
        await session.commit()
        return bool(res.rowcount > 0)

    async def update_hit(self, entry_id: UUID, session: Optional[AsyncSession] = None) -> None:
        if session is None:
            return
        now = datetime.now(timezone.utc)
        stmt = (
            update(SemanticCacheEntry)
            .where(SemanticCacheEntry.id == entry_id)
            .values(
                hit_count=SemanticCacheEntry.hit_count + 1,
                last_hit_at=now,
            )
        )
        await session.execute(stmt)
        await session.commit()

    async def invalidate_project(
        self, tenant_id: UUID, project_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        if session is None:
            return 0
        stmt = delete(SemanticCacheEntry).where(
            SemanticCacheEntry.tenant_id == tenant_id,
            SemanticCacheEntry.project_id == project_id,
        )
        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount or 0

    async def invalidate_tenant(
        self, tenant_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        if session is None:
            return 0
        stmt = delete(SemanticCacheEntry).where(SemanticCacheEntry.tenant_id == tenant_id)
        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount or 0

    async def list_entries(
        self,
        tenant_id: UUID,
        project_id: UUID,
        limit: int = 50,
        session: Optional[AsyncSession] = None,
    ) -> List[dict]:
        if session is None:
            return []
        stmt = (
            select(SemanticCacheEntry)
            .where(
                SemanticCacheEntry.tenant_id == tenant_id,
                SemanticCacheEntry.project_id == project_id,
            )
            .order_by(SemanticCacheEntry.created_at.desc())
            .limit(limit)
        )
        entries = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": e.id,
                "tenant_id": e.tenant_id,
                "project_id": e.project_id,
                "provider": e.provider,
                "model": e.model,
                "request_fingerprint": e.request_fingerprint,
                "embedding_model": e.embedding_model,
                "embedding_version": e.embedding_version,
                "created_at": e.created_at.isoformat(),
                "expires_at": e.expires_at.isoformat(),
                "last_hit_at": e.last_hit_at.isoformat() if e.last_hit_at else None,
                "hit_count": e.hit_count,
            }
            for e in entries
        ]


class InMemorySemanticCacheBackend(BaseSemanticCacheBackend):
    """
    Thread-safe in-memory semantic cache backend for lightning-fast test isolation.
    """

    def __init__(self):
        self._entries: Dict[UUID, dict] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _cosine_distance(v1: List[float], v2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2, strict=True))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 1.0
        sim = dot / (norm1 * norm2)
        return max(0.0, min(2.0, 1.0 - sim))

    async def search_candidates(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        model: str,
        fingerprint: str,
        query_embedding: List[float],
        top_k: int,
        session: Optional[AsyncSession] = None,
    ) -> List[SemanticCandidate]:
        async with self._lock:
            now = datetime.now(timezone.utc)
            bounded_top_k = min(top_k, settings.semantic_cache_max_candidates)

            matched = []
            for entry_id, item in list(self._entries.items()):
                if (
                    item["tenant_id"] == tenant_id
                    and item["project_id"] == project_id
                    and item["provider"] == provider
                    and item["model"] == model
                    and item["fingerprint"] == fingerprint
                ):
                    if item["expires_at"] <= now:
                        # Lazy eviction of expired entry
                        del self._entries[entry_id]
                        continue

                    dist = self._cosine_distance(query_embedding, item["embedding"])
                    sim = 1.0 - dist
                    matched.append(
                        SemanticCandidate(
                            id=entry_id,
                            tenant_id=item["tenant_id"],
                            project_id=item["project_id"],
                            provider=item["provider"],
                            model=item["model"],
                            request_fingerprint=item["fingerprint"],
                            response_cache_key=item["response_cache_key"],
                            distance=dist,
                            similarity=sim,
                            expires_at=item["expires_at"],
                        )
                    )

            matched.sort(key=lambda c: c.distance)
            return matched[:bounded_top_k]

    async def store_entry(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        model: str,
        fingerprint: str,
        semantic_representation: str,
        embedding: List[float],
        embedding_model: str,
        embedding_version: str,
        response_cache_key: str,
        expires_at: datetime,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        async with self._lock:
            entry_id = uuid.uuid4()
            self._entries[entry_id] = {
                "id": entry_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "provider": provider,
                "model": model,
                "fingerprint": fingerprint,
                "semantic_representation": semantic_representation,
                "embedding": embedding,
                "embedding_model": embedding_model,
                "embedding_version": embedding_version,
                "response_cache_key": response_cache_key,
                "created_at": datetime.now(timezone.utc),
                "expires_at": expires_at,
                "last_hit_at": None,
                "hit_count": 0,
            }
            return True

    async def delete_entry(self, entry_id: UUID, session: Optional[AsyncSession] = None) -> bool:
        async with self._lock:
            return bool(self._entries.pop(entry_id, None))

    async def update_hit(self, entry_id: UUID, session: Optional[AsyncSession] = None) -> None:
        async with self._lock:
            item = self._entries.get(entry_id)
            if item:
                item["hit_count"] += 1
                item["last_hit_at"] = datetime.now(timezone.utc)

    async def invalidate_project(
        self, tenant_id: UUID, project_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        async with self._lock:
            to_remove = [
                eid
                for eid, item in self._entries.items()
                if item["tenant_id"] == tenant_id and item["project_id"] == project_id
            ]
            for eid in to_remove:
                del self._entries[eid]
            return len(to_remove)

    async def invalidate_tenant(
        self, tenant_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        async with self._lock:
            to_remove = [
                eid for eid, item in self._entries.items() if item["tenant_id"] == tenant_id
            ]
            for eid in to_remove:
                del self._entries[eid]
            return len(to_remove)

    async def list_entries(
        self,
        tenant_id: UUID,
        project_id: UUID,
        limit: int = 50,
        session: Optional[AsyncSession] = None,
    ) -> List[dict]:
        async with self._lock:
            matched = [
                {
                    "id": item["id"],
                    "tenant_id": item["tenant_id"],
                    "project_id": item["project_id"],
                    "provider": item["provider"],
                    "model": item["model"],
                    "request_fingerprint": item["fingerprint"],
                    "embedding_model": item["embedding_model"],
                    "embedding_version": item["embedding_version"],
                    "created_at": item["created_at"].isoformat(),
                    "expires_at": item["expires_at"].isoformat(),
                    "last_hit_at": (
                        item["last_hit_at"].isoformat() if item["last_hit_at"] else None
                    ),
                    "hit_count": item["hit_count"],
                }
                for item in self._entries.values()
                if item["tenant_id"] == tenant_id and item["project_id"] == project_id
            ]
            matched.sort(key=lambda x: x["created_at"], reverse=True)
            return matched[:limit]

    def clear(self) -> None:
        self._entries.clear()
