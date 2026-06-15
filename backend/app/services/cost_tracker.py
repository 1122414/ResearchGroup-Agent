import uuid
from datetime import datetime

from ..core.config import settings
from ..core.logger import logger
from ..storage.repositories import LLMUsageRepository, RunRepository


class CostTracker:
    def estimate_tokens(self, text: str) -> int:
        chars_per_token = max(settings.token_estimate_chars_per_token, 1)
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        return max(1, int(len(text) / chars_per_token))

    def record(
        self,
        role: str,
        provider: str,
        model: str,
        prompt: str,
        completion: str = "",
        run_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        latency_ms: int = 0,
        success: bool = True,
        error: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> dict:
        prompt_count = prompt_tokens if prompt_tokens is not None else self.estimate_tokens(prompt)
        completion_count = completion_tokens if completion_tokens is not None else self.estimate_tokens(completion or "")
        total_tokens = prompt_count + completion_count
        input_rate, output_rate = settings.get_cost_rates_for_model(model, provider)
        cost_usd = prompt_count * input_rate + completion_count * output_rate
        item = {
            "id": f"usage_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "role": role,
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_count,
            "completion_tokens": completion_count,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "success": success,
            "error": error,
            "created_at": datetime.now().isoformat(),
        }
        LLMUsageRepository.insert(item)
        if run_id:
            RunRepository.increment_usage(run_id, cost_usd, total_tokens)
        logger.info(
            "[CostTracker] recorded | role=%s | provider=%s | model=%s | tokens=%d | cost=%.6f | latency=%dms | success=%s | run_id=%s",
            role, provider, model, total_tokens, cost_usd, latency_ms, success, run_id,
        )
        return item


cost_tracker = CostTracker()
