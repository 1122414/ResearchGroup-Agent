from __future__ import annotations

from ..core.config import settings
from .evidence_provider import evidence_provider
from .mcp_client_service import mcp_client_service


class ProviderAuditService:
    """Report which real-research capabilities are actually live.

    The system has many capabilities behind feature flags. In real mode it is
    easy to assume "search is on" when only the free academic APIs are active,
    or to run with MOCK off but no API key. This service makes the effective
    configuration explicit for startup logs and the /api/health/providers probe.
    """

    def audit(self) -> dict:
        llm = {
            "mock_mode": settings.mock_mode,
            "model": settings.llm_model_name,
            "base_url": settings.llm_base_url,
            "has_api_key": bool(settings.llm_api_key),
        }
        evidence = evidence_provider.list_capabilities()
        experiment = {
            "execution_enabled": settings.experiment_execution_enabled,
            "backend": settings.experiment_execution_backend,
            "require_review": settings.experiment_require_review,
            "allow_network": settings.experiment_allow_network,
        }
        mcp = mcp_client_service.summary()
        warnings = self._warnings(evidence)
        live_evidence = [item["name"] for item in evidence if item.get("enabled")]
        return {
            "ready_for_real_research": not settings.mock_mode and bool(settings.llm_api_key),
            "llm": llm,
            "evidence_providers": evidence,
            "live_evidence_providers": live_evidence,
            "experiment": experiment,
            "mcp": mcp,
            "warnings": warnings,
        }

    def _warnings(self, evidence: list[dict]) -> list[str]:
        warnings: list[str] = []
        if settings.mock_mode:
            warnings.append(
                "MOCK_MODE=true：所有 LLM 输出为确定性模拟数据，不会进行真实推理或检索。"
                "如需真正做科研，请设置 MOCK_MODE=false 并配置 LLM_API_KEY。"
            )
        elif not settings.llm_api_key:
            warnings.append("MOCK_MODE=false 但未配置 LLM_API_KEY，真实 LLM 调用会失败。")

        enabled = {item["name"] for item in evidence if item.get("enabled")}
        if settings.web_search_enabled and not settings.tavily_api_key and settings.web_search_provider_mode == "tavily":
            warnings.append("WEB_SEARCH_ENABLED=true 但未配置 TAVILY_API_KEY，网络搜索将不可用。")
        if not settings.web_search_enabled:
            warnings.append("WEB_SEARCH_ENABLED=false：仅使用免费学术 API，网络通用检索覆盖受限。")
        if settings.semantic_scholar_enabled and "semantic_scholar" not in enabled:
            warnings.append("SEMANTIC_SCHOLAR_ENABLED=true 但 provider 未生效，请检查 EVIDENCE_REMOTE_SEARCH_ENABLED。")
        if settings.browser_research_enabled and not settings.browser_use_model_name and not settings.llm_model_name:
            warnings.append("BROWSER_RESEARCH_ENABLED=true 但未配置浏览器模型，核验链路可能不可用。")
        if not enabled:
            warnings.append("当前没有任何已启用的证据检索 provider，文献任务将报告证据不足。")
        return warnings


provider_audit_service = ProviderAuditService()
