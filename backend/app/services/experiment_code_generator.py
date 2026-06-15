from __future__ import annotations

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger

_CONTRACT = """该脚本必须满足：
1. 可使用 Python 标准库以及 numpy、pandas、matplotlib（这些库已安装且保证可用）。不得联网、不得安装包。
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
4. 必须使用 matplotlib（matplotlib.use("Agg")）将对照结果绘制成图表并保存为当前目录下的 figure.png。
   绘图代码需用 try/except 包裹，万一绘图失败也不能让整个实验崩溃，但正常情况下必须产出 figure.png。
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
        if "summary.json" not in script or "def " not in script or "figure.png" not in script:
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
