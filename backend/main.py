import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent))

from app.api.routes_agents import router as agents_router
from app.api.routes_outputs import router as outputs_router
from app.api.routes_runs import router as runs_router
from app.api.routes_settings import router as settings_router
from app.api.routes_tasks import router as tasks_router
from app.core.config import settings
from app.services.agent_registry import agent_registry
from app.storage import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    agent_registry.load_seed_agents()
    yield


app = FastAPI(
    title="ResearchGroup-Agent",
    description="多 Agent 研究生课题组协作系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parsed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(runs_router)
app.include_router(outputs_router)
app.include_router(settings_router)


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "model": settings.llm_model_name,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.backend_host, port=settings.backend_port)
