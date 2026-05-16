from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..core.config import settings
from ..core.logger import logger

router = APIRouter(prefix="/api/settings", tags=["settings"])


READONLY_FIELDS = {
    "has_llm_api_key",
    "llm_api_key_masked",
}

ALLOWED_FIELDS = {
    "mock_mode",
    "llm_api_key",
    "llm_base_url",
    "llm_model_name",
    "advisor_model_name",
    "graduate_model_name",
    "subagent_model_name",
    "llm_timeout",
    "llm_max_retries",
    "llm_max_tokens",
    "advisor_temperature",
    "graduate_temperature",
    "subagent_temperature",
    "scheduler_skill_weight",
    "scheduler_idle_weight",
    "scheduler_idle_scale",
    "collab_complexity_threshold",
    "collab_load_threshold",
    "collab_max_count",
    "subagent_complexity_threshold",
    "subagent_decomposability_threshold",
    "subagent_mentoring_threshold",
    "run_poll_interval_ms",
    "frontend_log_flush_interval_ms",
    "run_cancel_check_enabled",
    "run_event_default_limit",
    "run_event_max_limit",
    "attachment_extract_max_chars",
    "attachment_max_file_size_mb",
    "multimodal_enabled",
    "vision_model_name",
    "literature_source_limit",
    "literature_fallback_source_count",
    "report_title_preview_chars",
    "report_output_point_max_chars",
    "report_output_point_limit",
    "report_evidence_paper_limit",
    "run_artifact_title_max_length",
    "run_artifact_dedupe_limit",
    "agent_skill_enabled",
    "skill_auto_capture_enabled",
    "skill_default_status",
    "skill_min_confidence",
    "skill_max_injected",
    "skill_sensitive_scan_enabled",
    "experiment_execution_enabled",
    "experiment_workspace_dir",
    "experiment_execution_backend",
    "experiment_command_timeout_seconds",
    "reproducible_experiment_timeout_seconds",
    "experiment_max_output_chars",
    "experiment_allow_network",
    "experiment_allow_package_install",
    "experiment_require_review",
    "experiment_env_file",
    "experiment_remote_host",
    "experiment_remote_port",
    "experiment_docker_image",
    "experiment_queue_backend",
    "review_pass_threshold",
    "review_default_approved_score",
    "review_default_rejected_score",
    "review_traceability_missing_score",
    "review_missing_score",
    "review_report_evidence_score",
    "log_level",
    "default_input_cost_per_token",
    "default_output_cost_per_token",
    "mock_input_cost_per_token",
    "mock_output_cost_per_token",
    "token_estimate_chars_per_token",
}


@router.get("")
async def get_settings():
    logger.debug("[API] get_settings")
    has_key = bool(settings.llm_api_key)
    return {
        "mock_mode": settings.mock_mode,
        "llm_api_key": "",
        "has_llm_api_key": has_key,
        "llm_api_key_masked": _mask_secret(settings.llm_api_key),
        "llm_model_name": settings.llm_model_name,
        "advisor_model_name": settings.advisor_model_name or settings.llm_model_name,
        "graduate_model_name": settings.graduate_model_name or settings.llm_model_name,
        "subagent_model_name": settings.subagent_model_name or settings.llm_model_name,
        "llm_base_url": settings.llm_base_url,
        "llm_timeout": settings.llm_timeout,
        "llm_max_retries": settings.llm_max_retries,
        "llm_max_tokens": settings.llm_max_tokens,
        "advisor_temperature": settings.advisor_temperature,
        "graduate_temperature": settings.graduate_temperature,
        "subagent_temperature": settings.subagent_temperature,
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
        "frontend_log_flush_interval_ms": settings.frontend_log_flush_interval_ms,
        "run_cancel_check_enabled": settings.run_cancel_check_enabled,
        "run_event_default_limit": settings.run_event_default_limit,
        "run_event_max_limit": settings.run_event_max_limit,
        "attachment_extract_max_chars": settings.attachment_extract_max_chars,
        "attachment_max_file_size_mb": settings.attachment_max_file_size_mb,
        "multimodal_enabled": settings.multimodal_enabled,
        "vision_model_name": settings.vision_model_name,
        "literature_source_limit": settings.literature_source_limit,
        "literature_fallback_source_count": settings.literature_fallback_source_count,
        "report_title_preview_chars": settings.report_title_preview_chars,
        "report_output_point_max_chars": settings.report_output_point_max_chars,
        "report_output_point_limit": settings.report_output_point_limit,
        "report_evidence_paper_limit": settings.report_evidence_paper_limit,
        "run_artifact_title_max_length": settings.run_artifact_title_max_length,
        "run_artifact_dedupe_limit": settings.run_artifact_dedupe_limit,
        "agent_skill_enabled": settings.agent_skill_enabled,
        "skill_auto_capture_enabled": settings.skill_auto_capture_enabled,
        "skill_default_status": settings.skill_default_status,
        "skill_min_confidence": settings.skill_min_confidence,
        "skill_max_injected": settings.skill_max_injected,
        "skill_sensitive_scan_enabled": settings.skill_sensitive_scan_enabled,
        "experiment_execution_enabled": settings.experiment_execution_enabled,
        "experiment_workspace_dir": settings.experiment_workspace_dir,
        "experiment_execution_backend": settings.experiment_execution_backend,
        "experiment_command_timeout_seconds": settings.experiment_command_timeout_seconds,
        "reproducible_experiment_timeout_seconds": settings.reproducible_experiment_timeout_seconds,
        "experiment_max_output_chars": settings.experiment_max_output_chars,
        "experiment_allow_network": settings.experiment_allow_network,
        "experiment_allow_package_install": settings.experiment_allow_package_install,
        "experiment_require_review": settings.experiment_require_review,
        "experiment_env_file": settings.experiment_env_file,
        "experiment_remote_host": settings.experiment_remote_host,
        "experiment_remote_port": settings.experiment_remote_port,
        "experiment_docker_image": settings.experiment_docker_image,
        "experiment_queue_backend": settings.experiment_queue_backend,
        "review_pass_threshold": settings.review_pass_threshold,
        "review_default_approved_score": settings.review_default_approved_score,
        "review_default_rejected_score": settings.review_default_rejected_score,
        "review_traceability_missing_score": settings.review_traceability_missing_score,
        "review_missing_score": settings.review_missing_score,
        "review_report_evidence_score": settings.review_report_evidence_score,
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
    updated = {}
    for key, raw_value in body.items():
        if key in READONLY_FIELDS or key not in ALLOWED_FIELDS:
            continue
        if key == "llm_api_key" and not str(raw_value or "").strip():
            continue
        value = _coerce_value(key, raw_value)
        setattr(settings, key, value)
        updated[key] = value

    if body.get("clear_llm_api_key"):
        settings.llm_api_key = ""
        updated["llm_api_key"] = ""

    if updated:
        try:
            _write_env(updated)
        except OSError as exc:
            logger.error("[API] update_settings env write failed | error=%s", exc)
            raise HTTPException(status_code=500, detail=f".env 写入失败: {exc}") from exc

    safe_updated = dict(updated)
    if "llm_api_key" in safe_updated:
        safe_updated["llm_api_key"] = ""
        safe_updated["has_llm_api_key"] = bool(settings.llm_api_key)
        safe_updated["llm_api_key_masked"] = _mask_secret(settings.llm_api_key)

    logger.info("[API] update_settings | updated=%s", _safe_log_settings(updated))
    return {"updated": safe_updated, "message": "配置已保存到 .env，重启服务后对启动参数完全生效。"}


def _coerce_value(key: str, value):
    current = getattr(settings, key, None)
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return "" if value is None else str(value)


def _write_env(updated: dict):
    env_path = Path(settings.Config.env_file)
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    pending = {key.upper(): value for key, value in updated.items()}
    output_lines: list[str] = []
    seen: set[str] = set()

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        upper = key.upper()
        if upper in pending:
            output_lines.append(f"{key}={_format_env_value(pending[upper])}")
            seen.add(upper)
        else:
            output_lines.append(line)

    for upper, value in pending.items():
        if upper not in seen:
            output_lines.append(f"{upper}={_format_env_value(value)}")

    env_path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


def _format_env_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if any(ch in text for ch in (" ", "#", "\n", '"')):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"****...{value[-4:]}"


def _safe_log_settings(values: dict) -> dict:
    return {key: ("***" if key == "llm_api_key" and value else value) for key, value in values.items()}
