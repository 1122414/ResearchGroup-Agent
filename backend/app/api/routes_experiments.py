from fastapi import APIRouter

from ..core.config import settings
from ..models.experiment import ExperimentApproval, ExperimentPlanCreate, ExperimentPlanUpdate, ExperimentReject
from ..services.experiment_executor import experiment_executor_service
from ..services.experiment_protocol_service import experiment_protocol_service
from ..storage.repositories import ExperimentFindingRepository, ExperimentResultRepository, ExperimentRunRepository
from .routes_settings import _coerce_value, _safe_log_settings, _write_env

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

EXPERIMENT_CONFIG_FIELDS = {
    "experiment_execution_enabled",
    "experiment_workspace_dir",
    "experiment_execution_backend",
    "experiment_command_timeout_seconds",
    "experiment_max_output_chars",
    "experiment_allow_network",
    "experiment_allow_package_install",
    "experiment_require_review",
    "experiment_env_file",
    "experiment_remote_host",
    "experiment_remote_port",
    "experiment_docker_image",
    "experiment_queue_backend",
    "experiment_support_base_confidence",
    "experiment_support_max_confidence",
    "experiment_weaken_confidence",
    "experiment_reject_confidence",
    "experiment_inconclusive_failure_confidence",
    "experiment_inconclusive_missing_metric_confidence",
}


@router.get("/config")
async def get_experiment_config():
    return {"config": {field: getattr(settings, field) for field in sorted(EXPERIMENT_CONFIG_FIELDS)}}


@router.patch("/config")
async def update_experiment_config(body: dict):
    updated = {}
    for key, raw_value in body.items():
        if key not in EXPERIMENT_CONFIG_FIELDS:
            continue
        value = _coerce_value(key, raw_value)
        setattr(settings, key, value)
        updated[key] = value
    if updated:
        _write_env(updated)
    return {"updated": updated, "safe_log": _safe_log_settings(updated)}


@router.get("/plans")
async def list_experiment_plans(run_id: str | None = None, task_id: str | None = None, status: str | None = None):
    return {"plans": experiment_executor_service.list(run_id=run_id, task_id=task_id, status=status)}


@router.get("/protocols")
async def list_experiment_protocols(run_id: str):
    return {"protocols": experiment_protocol_service.list_for_run(run_id)}


@router.get("/runs")
async def list_experiment_runs(run_id: str):
    return {"runs": ExperimentRunRepository.get_by_run(run_id)}


@router.get("/results")
async def list_experiment_results(run_id: str):
    return {"results": ExperimentResultRepository.get_by_run(run_id)}


@router.get("/findings")
async def list_experiment_findings(run_id: str):
    return {"findings": ExperimentFindingRepository.get_by_run(run_id)}


@router.get("/plans/{plan_id}")
async def get_experiment_plan(plan_id: str):
    return {"plan": experiment_executor_service.get(plan_id)}


@router.post("/plans")
async def create_experiment_plan(body: ExperimentPlanCreate):
    return {"plan": experiment_executor_service.create_plan(body)}


@router.patch("/plans/{plan_id}")
async def update_experiment_plan(plan_id: str, body: ExperimentPlanUpdate):
    return {"plan": experiment_executor_service.update_plan(plan_id, body)}


@router.post("/plans/{plan_id}/scan")
async def scan_experiment_plan(plan_id: str):
    return {"plan": experiment_executor_service.scan_plan(plan_id)}


@router.post("/plans/{plan_id}/approve")
async def approve_experiment_plan(plan_id: str, body: ExperimentApproval):
    return {"plan": experiment_executor_service.approve_plan(plan_id, body)}


@router.post("/plans/{plan_id}/reject")
async def reject_experiment_plan(plan_id: str, body: ExperimentReject):
    return {"plan": experiment_executor_service.reject_plan(plan_id, body)}


@router.post("/plans/{plan_id}/execute")
async def execute_experiment_plan(plan_id: str):
    return {"plan": experiment_executor_service.execute_plan(plan_id)}
