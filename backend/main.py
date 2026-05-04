from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .app.core.config import settings
from .app.storage import init_db
from .app.services.agent_registry import agent_registry
from .app.api.routes_agents import router as agents_router
from .app.api.routes_tasks import router as tasks_router
from .app.api.routes_runs import router as runs_router
from .app.api.routes_outputs import router as outputs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    agent_registry.load_seed_agents()
    yield


app = FastAPI(
    title="ResearchGroup-Agent",
    description="面向研究生课题组场景的多 Agent 协作与产出管理系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(runs_router)
app.include_router(outputs_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "mock_mode": settings.mock_mode}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.backend_host, port=settings.backend_port, reload=True)
