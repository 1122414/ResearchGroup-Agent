"""Application configuration loaded from the project-level .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class Settings(BaseSettings):
    """Centralized runtime settings.

    Keep operational constants here so local runs can be adjusted from `.env`
    without editing service code.
    """

    # LLM provider
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_name: str = "gpt-4o-mini"
    advisor_model_name: str = ""
    graduate_model_name: str = ""
    subagent_model_name: str = ""
    llm_timeout: int = 120
    llm_max_retries: int = 3
    llm_max_tokens: int = 4096
    advisor_temperature: float = 0.3
    graduate_temperature: float = 0.7
    subagent_temperature: float = 0.7
    mock_mode: bool = True

    # Cost estimation, USD per token. Keep these configurable because model
    # pricing differs across OpenAI-compatible providers.
    default_input_cost_per_token: float = 0.0
    default_output_cost_per_token: float = 0.0
    mock_input_cost_per_token: float = 0.0
    mock_output_cost_per_token: float = 0.0
    token_estimate_chars_per_token: float = 4.0

    # Storage
    database_url: str = "sqlite:///./researchgroup.db"

    # Scheduler and collaboration gates
    scheduler_skill_weight: float = 0.7
    scheduler_idle_weight: float = 0.3
    scheduler_idle_scale: float = 100.0
    collab_complexity_threshold: int = 7
    collab_load_threshold: float = 0.7
    collab_max_count: int = 2
    subagent_complexity_threshold: int = 6
    subagent_decomposability_threshold: int = 7
    subagent_mentoring_threshold: int = 6

    # Server and frontend integration
    backend_port: int = 8000
    backend_host: str = "0.0.0.0"
    frontend_port: int = 3000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    frontend_api_base: str = "http://localhost:8000/api"
    run_poll_interval_ms: int = 1500
    frontend_log_flush_interval_ms: int = 5000

    # Runtime behavior
    run_cancel_check_enabled: bool = True
    run_interaction_mode: str = "hitl"
    run_event_default_limit: int = 100
    run_event_max_limit: int = 500
    attachment_extract_max_chars: int = 12000
    attachment_max_file_size_mb: int = 25
    multimodal_enabled: bool = False
    vision_model_name: str = ""
    literature_source_limit: int = 5
    literature_fallback_source_count: int = 4
    report_title_preview_chars: int = 50
    report_output_point_max_chars: int = 500
    report_output_point_limit: int = 5
    report_evidence_paper_limit: int = 5
    run_artifact_title_max_length: int = 28
    run_artifact_dedupe_limit: int = 100
    evidence_provider_mode: str = "auto"
    evidence_remote_search_enabled: bool = False
    web_search_enabled: bool = False
    web_search_provider_mode: str = "tavily"
    evidence_search_max_results: int = 5
    evidence_excerpt_max_chars: int = 1200
    evidence_stale_after_years: int = 8
    evidence_primary_source_bonus: float = 0.15
    evidence_peer_review_bonus: float = 0.15
    evidence_link_support_weight: float = 1.0
    evidence_link_oppose_weight: float = 1.0
    claim_support_threshold: float = 0.65
    claim_conflict_threshold: float = 0.35
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    tavily_search_depth: str = "basic"
    crossref_enabled: bool = True
    crossref_base_url: str = "https://api.crossref.org"
    crossref_mailto: str = ""
    literature_require_grounded_sources: bool = True
    literature_min_grounded_sources: int = 1
    citation_validation_enabled: bool = True

    # Agent skill evolution
    agent_skill_enabled: bool = True
    skill_auto_capture_enabled: bool = True
    skill_default_status: str = "draft"
    skill_min_confidence: float = 0.7
    skill_max_injected: int = 5
    skill_sensitive_scan_enabled: bool = True

    # Experiment execution. Local execution is intentionally opt-in and guarded.
    experiment_execution_enabled: bool = False
    experiment_workspace_dir: str = "artifacts/experiment_workspace"
    experiment_execution_backend: str = "local"
    experiment_command_timeout_seconds: int = 300
    reproducible_experiment_timeout_seconds: int = 120
    experiment_max_output_chars: int = 20000
    experiment_allow_network: bool = False
    experiment_allow_package_install: bool = False
    experiment_require_review: bool = True
    experiment_env_file: str = ""
    experiment_remote_host: str = ""
    experiment_remote_port: int = 22
    experiment_docker_image: str = ""
    experiment_queue_backend: str = ""
    experiment_support_base_confidence: float = 0.6
    experiment_support_max_confidence: float = 0.95
    experiment_weaken_confidence: float = 0.45
    experiment_reject_confidence: float = 0.8
    experiment_inconclusive_failure_confidence: float = 0.2
    experiment_inconclusive_missing_metric_confidence: float = 0.3

    # Review heuristics
    review_pass_threshold: float = 0.75
    review_default_approved_score: float = 0.8
    review_default_rejected_score: float = 0.55
    review_traceability_missing_score: float = 0.45
    review_missing_score: float = 0.5
    review_report_evidence_score: float = 0.9

    # Research loop orchestration
    research_loop_auto_continue: bool = True
    research_loop_max_auto_rounds: int = 1
    research_loop_max_tasks_per_round: int = 3

    # Logging and artifacts
    log_level: str = "INFO"
    log_dir: str = "artifacts/logs"
    artifact_manifest_filename: str = "manifest.json"

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    @property
    def prompt_dir(self) -> Path:
        return PROJECT_ROOT / "backend" / "app" / "prompts"

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "backend" / "app" / "data"

    @property
    def artifacts_dir(self) -> Path:
        return PROJECT_ROOT / "artifacts"

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def get_model_for_role(self, role: str) -> str:
        role_map = {
            "advisor": self.advisor_model_name or self.llm_model_name,
            "advisor_decompose": self.advisor_model_name or self.llm_model_name,
            "advisor_review": self.advisor_model_name or self.llm_model_name,
            "advisor_report": self.advisor_model_name or self.llm_model_name,
            "graduate": self.graduate_model_name or self.llm_model_name,
            "subagent": self.subagent_model_name or self.llm_model_name,
        }
        return role_map.get(role, self.llm_model_name)

    def get_temperature_for_role(self, role: str) -> float:
        if role.startswith("advisor"):
            return self.advisor_temperature
        if role == "subagent":
            return self.subagent_temperature
        return self.graduate_temperature

    def get_cost_rates_for_model(self, model: str, provider: str) -> tuple[float, float]:
        if provider == "mock":
            return self.mock_input_cost_per_token, self.mock_output_cost_per_token
        return self.default_input_cost_per_token, self.default_output_cost_per_token


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
