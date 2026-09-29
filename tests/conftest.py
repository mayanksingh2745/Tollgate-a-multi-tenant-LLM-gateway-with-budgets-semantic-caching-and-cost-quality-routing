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
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()
