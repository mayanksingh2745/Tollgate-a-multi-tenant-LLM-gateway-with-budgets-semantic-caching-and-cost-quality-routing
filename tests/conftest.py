import sys
from pathlib import Path

# Setup pathing for pytest discovery
root_dir = Path(__file__).resolve().parents[1]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"
gateway_dir = root_dir / "apps" / "gateway"

for p in [str(root_dir), str(apps_dir), str(core_src), str(gateway_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest_asyncio
from gateway.src.db import get_db
from gateway.src.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tollgate_core.models import Base

# SQLite in-memory engine for fast, isolated async testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {},
)

TestAsyncSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(autouse=True)
def test_rate_limiter_backend():
    from gateway.src.ratelimit.limiter import InMemoryRateLimitBackend, rate_limiter

    original_backend = rate_limiter.backend
    rate_limiter.backend = InMemoryRateLimitBackend()
    yield
    rate_limiter.backend = original_backend


@pytest_asyncio.fixture(autouse=True)
def test_budget_manager_backend():
    from gateway.src.budgets.manager import InMemoryBudgetBackend, budget_manager

    original_backend = budget_manager.backend
    budget_manager.backend = InMemoryBudgetBackend()
    yield
    budget_manager.backend = original_backend


@pytest_asyncio.fixture(autouse=True)
def test_usage_publisher():
    from unittest.mock import AsyncMock

    from gateway.src.usage.publisher import usage_publisher

    original_client = usage_publisher._redis_client
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="mock-stream-msg-1")
    usage_publisher._redis_client = mock_redis
    yield
    usage_publisher._redis_client = original_client


@pytest_asyncio.fixture(autouse=True)
def test_exact_cache_backend():
    from gateway.src.cache import InMemoryCacheBackend, exact_cache

    original_backend = exact_cache.backend
    exact_cache.backend = InMemoryCacheBackend()
    yield
    exact_cache.backend = original_backend


@pytest_asyncio.fixture(autouse=True)
def test_semantic_cache_backend():
    from gateway.src.cache.semantic import (
        InMemorySemanticCacheBackend,
        MockEmbeddingProvider,
        semantic_cache,
    )

    original_backend = semantic_cache.backend
    original_provider = semantic_cache._embedding_provider
    semantic_cache.backend = InMemorySemanticCacheBackend()
    semantic_cache.embedding_provider = MockEmbeddingProvider()
    yield
    semantic_cache.backend = original_backend
    semantic_cache._embedding_provider = original_provider


@pytest_asyncio.fixture(autouse=True)
def test_router_isolation():
    from gateway.src.config import settings
    from gateway.src.router import model_router

    orig_router = model_router.active_router
    orig_enabled = settings.router_enabled
    orig_mode = settings.router_mode
    orig_shadow = settings.router_shadow_mode
    orig_threshold = settings.router_quality_threshold
    orig_cheap = settings.router_cheap_model
    orig_strong = settings.router_strong_model
    orig_fallback = settings.router_fallback_model
    orig_artifact = settings.router_artifact_path

    yield

    settings.router_enabled = orig_enabled
    settings.router_mode = orig_mode
    settings.router_shadow_mode = orig_shadow
    settings.router_quality_threshold = orig_threshold
    settings.router_cheap_model = orig_cheap
    settings.router_strong_model = orig_strong
    settings.router_fallback_model = orig_fallback
    settings.router_artifact_path = orig_artifact
    model_router.set_router(orig_router)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession):
    async def _override_get_db():
        async with TestAsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()
