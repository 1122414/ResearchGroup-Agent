from fastapi import APIRouter

from ..core.config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    """返回当前系统配置（安全字段，不含 API Key）。"""
    return {
        "mock_mode": settings.mock_mode,
        "llm_model_name": settings.llm_model_name,
        "advisor_model_name": settings.advisor_model_name or settings.llm_model_name,
        "graduate_model_name": settings.graduate_model_name or settings.llm_model_name,
        "subagent_model_name": settings.subagent_model_name or settings.llm_model_name,
        "llm_base_url": settings.llm_base_url,
        "llm_timeout": settings.llm_timeout,
        "llm_max_retries": settings.llm_max_retries,
        "database_url": settings.database_url,
        "scheduler_skill_weight": settings.scheduler_skill_weight,
        "scheduler_idle_weight": settings.scheduler_idle_weight,
        "scheduler_idle_scale": settings.scheduler_idle_scale,
        "collab_complexity_threshold": settings.collab_complexity_threshold,
        "collab_load_threshold": settings.collab_load_threshold,
        "collab_max_count": settings.collab_max_count,
        "subagent_complexity_threshold": settings.subagent_complexity_threshold,
        "subagent_decomposability_threshold": settings.subagent_decomposability_threshold,
        "subagent_mentoring_threshold": settings.subagent_mentoring_threshold,
        "backend_port": settings.backend_port,
        "backend_host": settings.backend_host,
        "frontend_port": settings.frontend_port,
        "cors_origins": settings.cors_origins,
        "frontend_api_base": settings.frontend_api_base,
        "run_poll_interval_ms": settings.run_poll_interval_ms,
        "run_cancel_check_enabled": settings.run_cancel_check_enabled,
        "run_event_default_limit": settings.run_event_default_limit,
        "run_event_max_limit": settings.run_event_max_limit,
        "log_level": settings.log_level,
        "log_dir": settings.log_dir,
        "default_input_cost_per_token": settings.default_input_cost_per_token,
        "default_output_cost_per_token": settings.default_output_cost_per_token,
        "mock_input_cost_per_token": settings.mock_input_cost_per_token,
        "mock_output_cost_per_token": settings.mock_output_cost_per_token,
        "token_estimate_chars_per_token": settings.token_estimate_chars_per_token,
    }


@router.patch("")
async def update_settings(body: dict):
    """热更新部分运行时可变配置（主要用于切换 Mock 模式等）。

    注意：修改仅在当前进程生效，重启后从 .env 重新加载。
    """
    allowed = {"mock_mode", "llm_timeout", "llm_max_retries", "log_level", "run_poll_interval_ms"}
    updated = {}
    for key in allowed:
        if key in body:
            setattr(settings, key, body[key])
            updated[key] = body[key]
    return {"updated": updated, "message": "配置已更新（仅当前进程有效，重启后从 .env 重新加载）"}
