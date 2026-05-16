from fastapi import APIRouter

from ..services.dashboard_service import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
async def get_dashboard_overview(run_id: str | None = None):
    return dashboard_service.overview(run_id)
