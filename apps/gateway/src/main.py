import sys
from pathlib import Path

# Add workspace root to sys.path so imports work seamlessly regardless of launch directory
root_dir = Path(__file__).resolve().parents[3]
core_src = root_dir / "packages" / "core" / "src"
gateway_src = root_dir / "apps" / "gateway"

for p in [str(root_dir), str(core_src), str(gateway_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from gateway.src.api.health import router as health_router
from gateway.src.api.routes.tenants import router as tenants_router
from gateway.src.api.routes.users import router as users_router
from gateway.src.api.routes.projects import router as projects_router
from gateway.src.api.routes.api_keys import router as api_keys_router
from gateway.src.config import settings
from gateway.src.redis import close_redis_connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    print(f"[Tollgate Gateway] Starting in {settings.environment} mode...")
    yield
    # Shutdown sequence
    print("[Tollgate Gateway] Shutting down...")
    await close_redis_connection()


app = FastAPI(
    title="Tollgate LLM Gateway API",
    description="Multi-tenant LLM gateway identity & API key management.",
    version="0.1.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(projects_router)
app.include_router(api_keys_router)


@app.get("/", summary="Root Endpoint")
async def root():
    return {
        "service": "Tollgate LLM Gateway",
        "phase": "1 - Multi-Tenancy & API Key Authentication",
        "status": "online",
        "docs_url": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "gateway.src.main:app",
        host=settings.gateway_host,
        port=settings.gateway_port,
        reload=True
    )
