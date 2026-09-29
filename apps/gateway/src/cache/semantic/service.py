import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

from gateway.src.cache.semantic.backend import (
    BaseSemanticCacheBackend,
    PgvectorSemanticCacheBackend,
    SemanticCandidate,
)
from gateway.src.cache.semantic.embeddings import (
    EmbeddingProvider,
    get_embedding_provider,
)
from gateway.src.cache.semantic.metrics import semantic_cache_metrics
from gateway.src.cache.semantic.representation import (
    SEMANTIC_REPRESENTATION_VERSION,
    SemanticRepresentation,
)
from gateway.src.cache.service import CACHE_SCHEMA_VERSION, exact_cache
from gateway.src.config import settings
from gateway.src.schemas.chat import ChatCompletionRequest, ChatCompletionResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("tollgate.cache.semantic.service")


class SemanticResponseCache:
    """
    Tenant-safe, conservative semantic response cache.
    Combines vector similarity search (PostgreSQL pgvector) with exact response storage (Redis),
    guaranteeing strict multi-tenant isolation, fail-open resilience, and budget preservation.
    """

    def __init__(
        self,
        backend: Optional[BaseSemanticCacheBackend] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.backend = backend or PgvectorSemanticCacheBackend()
        self._embedding_provider = embedding_provider

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    @embedding_provider.setter
    def embedding_provider(self, provider: EmbeddingProvider) -> None:
        self._embedding_provider = provider

    async def get(
        self,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        session: Optional[AsyncSession] = None,
    ) -> Tuple[Optional[ChatCompletionResponse], Optional[float]]:
        """
        Looks up semantically similar cached response.
        Returns (response, similarity_score) on HIT, or (None, None) on MISS/BYPASS/Error.
        Fails open if embedding, database, or Redis lookup encounters any failure.
        """
        if not settings.semantic_cache_enabled:
            return None, None

        semantic_cache_metrics.increment("semantic_cache_requests_total")

        # 1. Evaluate cacheability policy (bypasses tools, streaming, etc.)
        is_cacheable, bypass_reason = SemanticRepresentation.is_cacheable(request)
        if not is_cacheable:
            semantic_cache_metrics.increment("semantic_cache_bypasses_total")
            logger.debug(f"Semantic cache lookup bypassed: reason={bypass_reason}")
            return None, None

        t0 = time.perf_counter()

        # 2. Build text to embed and generate embedding with timeout
        text_to_embed = SemanticRepresentation.build_text_to_embed(request)
        try:
            semantic_cache_metrics.increment("semantic_cache_embedding_requests_total")
            t_emb = time.perf_counter()
            query_embedding = await asyncio.wait_for(
                self.embedding_provider.embed(text_to_embed),
                timeout=settings.embedding_timeout_seconds,
            )
            emb_latency_ms = (time.perf_counter() - t_emb) * 1000.0
            semantic_cache_metrics.record_embedding_latency(emb_latency_ms)
        except Exception as emb_err:
            semantic_cache_metrics.increment("semantic_cache_embedding_errors_total")
            semantic_cache_metrics.increment("semantic_cache_errors_total")
            logger.warning(f"Semantic embedding generation failed (failing open): {emb_err}")
            return None, None

        # 3. Compute compatibility fingerprint
        fingerprint = SemanticRepresentation.compute_fingerprint(
            request=request,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
        )

        # 4. Search candidates in backend with timeout
        try:
            candidates = await asyncio.wait_for(
                self.backend.search_candidates(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    provider=provider,
                    model=request.model,
                    fingerprint=fingerprint,
                    query_embedding=query_embedding,
                    top_k=settings.semantic_cache_top_k,
                    session=session,
                ),
                timeout=settings.semantic_cache_lookup_timeout_seconds,
            )
        except Exception as search_err:
            semantic_cache_metrics.increment("semantic_cache_errors_total")
            logger.warning(f"Semantic candidate search failed (failing open): {search_err}")
            return None, None

        lookup_latency_ms = (time.perf_counter() - t0) * 1000.0
        semantic_cache_metrics.record_lookup_latency(lookup_latency_ms)

        if not candidates:
            semantic_cache_metrics.increment("semantic_cache_misses_total")
            logger.debug(
                f"Semantic cache MISS (no candidates): model={request.model} tenant={tenant_id}"
            )
            return None, None

        # 5. Evaluate nearest candidate against similarity threshold
        best_candidate: SemanticCandidate = candidates[0]
        semantic_cache_metrics.record_similarity_score(best_candidate.similarity)

        if best_candidate.similarity < settings.semantic_cache_threshold:
            semantic_cache_metrics.increment("semantic_cache_misses_total")
            logger.info(
                f"Semantic cache MISS: similarity={best_candidate.similarity:.4f} < "
                f"threshold={settings.semantic_cache_threshold:.4f} model={request.model}"
            )
            return None, None

        # 6. Check Shadow Mode (Section 37)
        if settings.semantic_cache_shadow_mode:
            semantic_cache_metrics.increment("semantic_cache_hits_total")
            logger.info(
                f"Semantic cache SHADOW HIT: similarity={best_candidate.similarity:.4f} "
                f"threshold={settings.semantic_cache_threshold:.4f} entry_id={best_candidate.id} "
                f"(shadow mode active; proceeding to provider)"
            )
            return None, None

        # 7. Validate referenced response from Redis (Section 27)
        try:
            raw_entry = await exact_cache.backend.get(best_candidate.response_cache_key)
        except Exception as redis_err:
            logger.warning(
                f"Failed to fetch referenced Redis response for semantic hit (failing open): {redis_err}"
            )
            semantic_cache_metrics.increment("semantic_cache_misses_total")
            return None, None

        if raw_entry is None:
            # Stale semantic reference in Redis (evicted via TTL or invalidated)
            logger.info(
                f"Stale semantic cache reference: key={best_candidate.response_cache_key} missing in Redis"
            )
            # Clean up stale metadata asynchronously
            asyncio.create_task(self.backend.delete_entry(best_candidate.id, session))
            semantic_cache_metrics.increment("semantic_cache_misses_total")
            return None, None

        try:
            entry = json.loads(raw_entry)
            if entry.get("cache_version") != CACHE_SCHEMA_VERSION:
                logger.warning(f"Incompatible response cache version: {entry.get('cache_version')}")
                asyncio.create_task(self.backend.delete_entry(best_candidate.id, session))
                semantic_cache_metrics.increment("semantic_cache_misses_total")
                return None, None

            # Verify tenant & project ownership integrity
            if entry.get("tenant_id") != str(tenant_id) or entry.get("project_id") != str(
                project_id
            ):
                logger.error(
                    f"Cross-tenant cache poisoning detected! Response owner: {entry.get('tenant_id')} "
                    f"Requested tenant: {tenant_id}"
                )
                asyncio.create_task(self.backend.delete_entry(best_candidate.id, session))
                semantic_cache_metrics.increment("semantic_cache_misses_total")
                return None, None

            response_data = entry.get("response")
            cached_response = ChatCompletionResponse.model_validate(response_data)

            # Update hit count & timestamp in metadata
            await self.backend.update_hit(best_candidate.id, session)
            semantic_cache_metrics.increment("semantic_cache_hits_total")

            logger.info(
                f"Semantic cache HIT: similarity={best_candidate.similarity:.4f} "
                f"threshold={settings.semantic_cache_threshold:.4f} model={request.model} "
                f"entry_id={best_candidate.id} latency_ms={lookup_latency_ms:.2f}"
            )
            return cached_response, best_candidate.similarity

        except Exception as parse_err:
            logger.warning(
                f"Failed to deserialize referenced response (treating as miss): {parse_err}"
            )
            asyncio.create_task(self.backend.delete_entry(best_candidate.id, session))
            semantic_cache_metrics.increment("semantic_cache_misses_total")
            return None, None

    async def set(
        self,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
        response_cache_key: str,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Stores semantic metadata and embedding vector in PostgreSQL pgvector.
        Points to the response previously saved in the exact cache (Redis).
        Fails open on any error.
        """
        if not settings.semantic_cache_enabled:
            return False

        is_cacheable, _ = SemanticRepresentation.is_cacheable(request)
        if not is_cacheable:
            return False

        t0 = time.perf_counter()
        try:
            text_to_embed = SemanticRepresentation.build_text_to_embed(request)
            embedding = await asyncio.wait_for(
                self.embedding_provider.embed(text_to_embed),
                timeout=settings.embedding_timeout_seconds,
            )

            fingerprint = SemanticRepresentation.compute_fingerprint(
                request=request,
                tenant_id=tenant_id,
                project_id=project_id,
                provider=provider,
            )

            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=settings.semantic_cache_ttl_seconds
            )

            success = await self.backend.store_entry(
                tenant_id=tenant_id,
                project_id=project_id,
                provider=provider,
                model=request.model,
                fingerprint=fingerprint,
                semantic_representation=text_to_embed[:1000],  # truncated debug preview
                embedding=embedding,
                embedding_model=self.embedding_provider.model_name,
                embedding_version=SEMANTIC_REPRESENTATION_VERSION,
                response_cache_key=response_cache_key,
                expires_at=expires_at,
                session=session,
            )

            write_latency_ms = (time.perf_counter() - t0) * 1000.0
            semantic_cache_metrics.record_write_latency(write_latency_ms)
            logger.debug(
                f"Semantic cache entry indexed: model={request.model} "
                f"ttl={settings.semantic_cache_ttl_seconds}s latency_ms={write_latency_ms:.2f}"
            )
            return success
        except Exception as e:
            semantic_cache_metrics.increment("semantic_cache_errors_total")
            logger.warning(f"Failed to store semantic cache entry (ignoring): {e}")
            return False

    async def invalidate_project(
        self, tenant_id: UUID, project_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        """
        Deletes all semantic cache entries for a project.
        """
        count = await self.backend.invalidate_project(tenant_id, project_id, session)
        logger.info(
            f"Invalidated semantic cache for tenant={tenant_id} project={project_id} (count={count})"
        )
        return count

    async def invalidate_tenant(
        self, tenant_id: UUID, session: Optional[AsyncSession] = None
    ) -> int:
        """
        Deletes all semantic cache entries for a tenant.
        """
        count = await self.backend.invalidate_tenant(tenant_id, session)
        logger.info(f"Invalidated semantic cache for tenant={tenant_id} (count={count})")
        return count


semantic_cache = SemanticResponseCache()
