import asyncio
import hashlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

root_dir = Path(__file__).resolve().parents[1]
core_src = root_dir / "packages" / "core" / "src"
gateway_dir = root_dir / "apps" / "gateway"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src), str(gateway_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tollgate_core.models import APIKey, Base, Project, Tenant, UsageEvent, User
from tollgate_core.security import hash_password

DATABASE_URL = "sqlite+aiosqlite:///tollgate_local.db"


async def seed():
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        # Check if already seeded
        from sqlalchemy import select

        res = await session.execute(select(User).where(User.email == "admin@tollgate.io"))
        if res.scalar_one_or_none():
            print("Local database already seeded.")
            return

        tenant_id = uuid.uuid4()
        tenant = Tenant(
            id=tenant_id,
            name="Acme AI Systems",
            slug="acme-ai",
            status="active",
        )
        session.add(tenant)
        await session.flush()

        project_id = uuid.uuid4()
        project = Project(
            id=project_id,
            tenant_id=tenant_id,
            name="Production Gateway",
            slug="prod",
            status="active",
        )
        session.add(project)

        project_staging_id = uuid.uuid4()
        project_staging = Project(
            id=project_staging_id,
            tenant_id=tenant_id,
            name="Staging Environment",
            slug="staging",
            status="active",
        )
        session.add(project_staging)
        await session.flush()

        pwd_hash = hash_password("Password123!")

        user1 = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name="Alex Rivera (Owner)",
            email="admin@tollgate.io",
            password_hash=pwd_hash,
            role="owner",
            status="active",
        )
        session.add(user1)

        user2 = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name="Demo Admin",
            email="admin@tenant.com",
            password_hash=pwd_hash,
            role="admin",
            status="active",
        )
        session.add(user2)
        await session.flush()

        # Seed standard API key
        key_raw = "tg_live_demo_key_tollgate_2026_abcdef"
        key_prefix = key_raw[:16]
        key_hash = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()

        api_key = APIKey(
            id=uuid.uuid4(),
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user1.id,
            name="Primary Web API Key",
            key_prefix=key_prefix,
            key_hash=key_hash,
            status="active",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
            last_used_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        session.add(api_key)

        # Seed sample usage events so dashboard metrics and logs are populated
        sample_models = [
            ("gpt-4o-mini", "OpenAI", "cheap", 140, 80, 220, 30),
            ("gpt-4o", "OpenAI", "strong", 500, 320, 820, 4200),
            ("claude-3-5-sonnet", "Anthropic", "strong", 420, 260, 680, 3500),
            ("mistral-large", "Mistral AI", "strong", 600, 150, 750, 1800),
        ]
        now = datetime.now(timezone.utc)
        for i in range(25):
            m, p, route, p_tok, c_tok, t_tok, cost = sample_models[i % len(sample_models)]
            ev = UsageEvent(
                id=uuid.uuid4(),
                event_id=uuid.uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                api_key_id=api_key.id,
                request_id=f"req_{uuid.uuid4().hex[:12]}",
                provider=p,
                model=m,
                stream=False,
                status="success" if i != 7 else "provider_failure",
                latency_ms=180.0 + (i * 24.5) % 400,
                input_tokens=p_tok,
                output_tokens=c_tok,
                total_tokens=t_tok,
                estimated_cost=cost,
                actual_cost=cost,
                cache_status="HIT" if i % 3 == 0 else "MISS",
                router_route=route,
                created_at=now - timedelta(hours=i),
                processed_at=now - timedelta(hours=i),
            )
            session.add(ev)

        await session.commit()
        print("Database seeded successfully with users, projects, api keys, and usage events!")


if __name__ == "__main__":
    asyncio.run(seed())
