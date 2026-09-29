import asyncio
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add core and apps to path
root_dir = Path(__file__).resolve().parents[1]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tollgate_core.models import Base, Project, Tenant
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


async def run_benchmark(num_events: int = 500):
    print("=== Tollgate Phase 6 Usage Pipeline Benchmark ===")
    print(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {platform.python_version()}")
    print(f"Total events: {num_events}")

    # Use in-memory SQLite for reproducible standalone benchmark
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(test_db_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    t_id = uuid.uuid4()
    p_id = uuid.uuid4()

    async with session_factory() as session:
        tenant = Tenant(id=t_id, name="Bench Co", slug="bench-co")
        project = Project(id=p_id, tenant_id=t_id, name="Bench Proj", slug="bench-proj")
        session.add_all([tenant, project])
        await session.commit()

    # Generate events
    events = [
        UsageEventPayload(
            event_id=uuid.uuid4(),
            request_id=f"req_bench_{i}",
            timestamp=datetime.now(timezone.utc),
            tenant_id=t_id,
            project_id=p_id,
            provider="openai" if i % 2 == 0 else "anthropic",
            model="gpt-4o" if i % 2 == 0 else "claude-3-5-sonnet",
            status="success",
            input_tokens=150,
            output_tokens=75,
            total_tokens=225,
            estimated_cost=2500,
            actual_cost=2000,
            latency_ms=150.0,
        )
        for i in range(num_events)
    ]

    # Measure serialization latency
    t0_ser = time.perf_counter()
    _ = [e.to_stream_entry() for e in events]
    t_ser_total = (time.perf_counter() - t0_ser) * 1000.0
    avg_ser = t_ser_total / num_events

    print("\n--- Event Serialization ---")
    print(f"Total serialization time: {t_ser_total:.2f} ms")
    print(f"Average serialization latency: {avg_ser:.4f} ms/event")

    # Measure database insertion & rollup latency
    latencies = []
    t0_db = time.perf_counter()

    batch_size = 50
    for i in range(0, num_events, batch_size):
        batch = events[i : i + batch_size]
        t_batch_start = time.perf_counter()
        async with session_factory() as session:
            async with session.begin():
                for ev in batch:
                    await persist_usage_event(session, ev)
        batch_duration_ms = (time.perf_counter() - t_batch_start) * 1000.0
        latencies.extend([batch_duration_ms / len(batch)] * len(batch))

    total_db_time = time.perf_counter() - t0_db
    throughput = num_events / total_db_time

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p90 = latencies[int(len(latencies) * 0.90)]
    p99 = latencies[int(len(latencies) * 0.99)]

    print("\n--- Worker Database Persistence & Rollup Upsert ---")
    print(f"Total processing time: {total_db_time:.2f} s")
    print(f"Worker throughput: {throughput:.1f} events/sec")
    print(f"Per-event latency P50: {p50:.3f} ms")
    print(f"Per-event latency P90: {p90:.3f} ms")
    print(f"Per-event latency P99: {p99:.3f} ms")
    print("===================================================\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_benchmark())
