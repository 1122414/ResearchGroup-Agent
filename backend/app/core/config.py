"""
核心配置模块
所有配置从 .env 文件和环境变量加载，方便后续更改
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class Settings(BaseSettings):
    """应用全局配置，自动从 .env 加载"""

    # ========== LLM 配置 ==========
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_name: str = "gpt-4o-mini"
    advisor_model_name: str = ""
    graduate_model_name: str = ""
    subagent_model_name: str = ""
    llm_timeout: int = 120
    llm_max_retries: int = 3

    # ========== 数据库配置 ==========
    database_url: str = "sqlite:///./researchgroup.db"

    # ========== 运行模式 ==========
    mock_mode: bool = True

    # ========== 调度器常量 ==========
    scheduler_skill_weight: float = 0.7
    scheduler_idle_weight: float = 0.3
    scheduler_idle_scale: float = 100.0
    collab_complexity_threshold: int = 7
    collab_load_threshold: float = 0.7
    collab_max_count: int = 2
    subagent_complexity_threshold: int = 6
    subagent_decomposability_threshold: int = 7
    subagent_mentoring_threshold: int = 6

    # ========== 服务配置 ==========
    backend_port: int = 8000
    backend_host: str = "0.0.0.0"
    frontend_port: int = 3000

    # ========== 日志配置 ==========
    log_level: str = "INFO"
    log_dir: str = "artifacts/logs"

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = False
        # 环境变量名前缀匹配：LLM_API_KEY -> llm_api_key
        extra = "ignore"

    @property
    def prompt_dir(self) -> Path:
        """Prompt 文件目录"""
        return PROJECT_ROOT / "backend" / "app" / "prompts"

    @property
    def data_dir(self) -> Path:
        """Seed 数据目录"""
        return PROJECT_ROOT / "backend" / "app" / "data"

    @property
    def artifacts_dir(self) -> Path:
        """产出物目录"""
        return PROJECT_ROOT / "artifacts"

    def get_model_for_role(self, role: str) -> str:
        """根据角色获取对应的模型名称"""
        role_map = {
            "advisor": self.advisor_model_name or self.llm_model_name,
            "graduate": self.graduate_model_name or self.llm_model_name,
            "subagent": self.subagent_model_name or self.llm_model_name,
        }
        return role_map.get(role, self.llm_model_name)


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 全局配置实例
settings = get_settings()
