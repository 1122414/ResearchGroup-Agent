import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent))

from app.api.routes_agents import router as agents_router
from app.api.routes_agent_skills import router as agent_skills_router
from app.api.routes_experiments import router as experiments_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_logs import router as logs_router
from app.api.routes_monitor import router as monitor_router
from app.api.routes_outputs import router as outputs_router
from app.api.routes_runs import router as runs_router
from app.api.routes_settings import router as settings_router
from app.api.routes_tasks import router as tasks_router
from app.core.config import settings
from app.core.logger import logger, setup_logging
from app.core.logging_middleware import LoggingMiddleware
from app.services.agent_registry import agent_registry
from app.services.agent_skill_service import agent_skill_service
from app.services.provider_audit_service import provider_audit_service
from app.storage import init_db

setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    agent_registry.load_seed_agents()
    seeded_skills = agent_skill_service.seed_defaults()
    logger.info("Default agent skills seeded | created=%d", seeded_skills)
    audit = provider_audit_service.audit()
    logger.info(
        "Backend started | port=%s | mock_mode=%s | ready_for_real_research=%s | live_evidence=%s",
        settings.backend_port,
        settings.mock_mode,
        audit["ready_for_real_research"],
        ",".join(audit["live_evidence_providers"]) or "none",
    )
    for warning in audit["warnings"]:
        logger.warning("[ProviderAudit] %s", warning)
    yield


app = FastAPI(
    title="ResearchGroup-Agent",
    description="多 Agent 研究生课题组协作系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(LoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parsed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)
app.include_router(agent_skills_router)
app.include_router(experiments_router)
app.include_router(dashboard_router)
app.include_router(tasks_router)
app.include_router(runs_router)
app.include_router(outputs_router)
app.include_router(settings_router)
app.include_router(monitor_router)
app.include_router(logs_router)


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "model": settings.llm_model_name,
    }


@app.get("/api/health/providers")
async def provider_health():
    return provider_audit_service.audit()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.backend_port)
