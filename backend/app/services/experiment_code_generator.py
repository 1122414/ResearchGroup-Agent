from __future__ import annotations

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger

_CONTRACT = """该脚本必须满足：
1. 仅使用 Python 标准库（可选 numpy/matplotlib，如不可用需自动降级，不得联网、不得安装包）。
2. 围绕给定假设设计一个小而真实、可在 3 分钟内完成的实验，包含基线与处理（treatment）两种条件。
3. 在当前工作目录写出 summary.json，字段固定为：
   {
     "metric_name": 字符串,
     "baseline_value": 数值,
     "treatment_value": 数值,
     "direction": "maximize" 或 "minimize",
     "rows": [ {可用于报告表格的对照行} ],
     "notes": 字符串
   }
4. 如可用 matplotlib，则额外保存 figure.png 展示对照结果；不可用时跳过且不报错。
5. 把关键过程 print 到 stdout，最后 print("experiment completed")。
只返回完整的 Python 源码，不要任何解释或 Markdown 代码围栏。"""


class ExperimentCodeGenerator:
    """Generate goal/hypothesis-driven experiment code instead of a fixed script.

    Returns None when generation is disabled or unavailable (mock mode / parse
    failure), so the caller can fall back to the deterministic built-in script.
    """

    async def generate(self, *, goal: str, protocol: dict, hypothesis: dict) -> str | None:
        if not settings.experiment_generated_code_enabled or settings.mock_mode:
            return None
        prompt = (
            "你是负责设计可复现实验的研究生 Agent。请根据下面的研究目标与假设，生成一个自包含的 Python 实验脚本。\n\n"
            f"研究目标：{goal}\n"
            f"假设：{hypothesis.get('statement', '')}\n"
            f"假设依据：{hypothesis.get('rationale', '')}\n"
            f"协议研究问题：{protocol.get('research_question', '')}\n\n"
            f"{_CONTRACT}"
        )
        try:
            raw = await create_llm_provider().generate(prompt=prompt, role="graduate")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ExperimentCodeGen] generation failed | error=%s", exc)
            return None
        script = self._strip_fences(raw)
        if "summary.json" not in script or "def " not in script:
            logger.warning("[ExperimentCodeGen] generated script did not satisfy contract; falling back")
            return None
        return script

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


experiment_code_generator = ExperimentCodeGenerator()
