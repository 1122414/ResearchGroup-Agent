import json
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from ..core.config import settings


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        role: str = "graduate",
        run_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> str:
        pass


class MockLLMProvider(LLMProvider):
    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        role: str = "graduate",
        run_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> str:
        started = time.perf_counter()
        if role == "advisor_decompose":
            result = self._mock_advisor_decomposition()
        elif role == "advisor_review":
            result = self._mock_review()
        elif role == "advisor_report":
            result = self._mock_report()
        elif role == "subagent":
            result = self._mock_subagent_result()
        else:
            result = self._mock_graduate_result(prompt)

        from ..services.cost_tracker import cost_tracker

        cost_tracker.record(
            role=role,
            provider="mock",
            model="mock",
            prompt=prompt,
            completion=result,
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            success=True,
        )
        return result

    def _mock_advisor_decomposition(self) -> str:
        return json.dumps(
            [
                {
                    "title": "梳理相关研究与系统定位",
                    "description": "整理多 Agent 科研协作、任务分解、Agent 调度和成果审核相关工作，明确本项目的差异化定位。",
                    "task_type": "literature_survey",
                    "priority": 9,
                    "complexity": 7,
                    "decomposability": 9,
                    "required_skills": {
                        "literature_review": 9,
                        "coding": 2,
                        "experiment": 1,
                        "data_analysis": 4,
                        "academic_writing": 7,
                        "mentoring": 6,
                    },
                },
                {
                    "title": "设计可观测的运行架构",
                    "description": "设计 Run、Task、Agent、SubAgent、事件日志和成本记录之间的数据流，保证用户能看到系统正在做什么。",
                    "task_type": "system_design",
                    "priority": 10,
                    "complexity": 8,
                    "decomposability": 7,
                    "required_skills": {
                        "literature_review": 3,
                        "coding": 9,
                        "experiment": 4,
                        "data_analysis": 6,
                        "academic_writing": 5,
                        "mentoring": 6,
                    },
                },
                {
                    "title": "制定任务执行与停止验证方案",
                    "description": "设计从创建 Run、执行任务、生成事件、记录成本到前端停止任务的功能测试流程。",
                    "task_type": "experiment_design",
                    "priority": 8,
                    "complexity": 7,
                    "decomposability": 7,
                    "required_skills": {
                        "literature_review": 4,
                        "coding": 6,
                        "experiment": 9,
                        "data_analysis": 7,
                        "academic_writing": 5,
                        "mentoring": 6,
                    },
                },
                {
                    "title": "分析运行结果与成本指标",
                    "description": "汇总任务完成率、审核结果、LLM 调用次数、token 消耗、成本估算和失败原因。",
                    "task_type": "result_analysis",
                    "priority": 8,
                    "complexity": 7,
                    "decomposability": 6,
                    "required_skills": {
                        "literature_review": 3,
                        "coding": 5,
                        "experiment": 6,
                        "data_analysis": 10,
                        "academic_writing": 6,
                        "mentoring": 5,
                    },
                },
                {
                    "title": "撰写阶段性研究报告",
                    "description": "将任务产出、导师审核意见和运行指标整理为结构化 Markdown 报告。",
                    "task_type": "report_writing",
                    "priority": 8,
                    "complexity": 6,
                    "decomposability": 5,
                    "required_skills": {
                        "literature_review": 6,
                        "coding": 2,
                        "experiment": 3,
                        "data_analysis": 5,
                        "academic_writing": 10,
                        "mentoring": 5,
                    },
                },
            ],
            ensure_ascii=False,
            indent=2,
        )

    def _mock_graduate_result(self, prompt: str) -> str:
        if "system_design" in prompt or "系统设计" in prompt:
            result = {
                "summary": "建议以 Run 事件流作为系统可观测性的核心，把拆解、调度、执行、SubAgent、审核和报告生成都写入结构化事件。",
                "deliverables": ["运行状态机", "事件日志表", "成本记录表", "前端运行详情页"],
                "risks": ["长请求期间无法实时推送", "真实 LLM 调用成本需要兜底估算"],
                "next_steps": ["先实现轮询接口", "后续再预留 SSE 或 WebSocket"],
            }
        elif "experiment_design" in prompt or "实验" in prompt:
            result = {
                "summary": "功能测试应覆盖 Mock 完整流程、运行事件、成本记录、取消请求和报告产出。",
                "metrics": ["任务总数", "完成任务数", "事件数量", "LLM 调用数量", "累计成本", "取消后新增事件数量"],
                "procedure": ["创建 Run", "启动执行", "轮询 summary", "检查 events 和 usage", "触发 cancel", "检查最终状态"],
            }
        elif "result_analysis" in prompt or "结果分析" in prompt:
            result = {
                "summary": "运行分析应关注任务状态分布、Agent 负载、LLM 调用耗时、失败重试和需修改任务比例。",
                "key_metrics": {
                    "task_completion_rate": "按 completed / total 计算",
                    "review_revision_rate": "按 need_revision / total 计算",
                    "cost_usd": "按 usage 明细求和",
                },
                "recommendations": ["对失败和需修改任务展示醒目提示", "把成本明细放入运行详情页"],
            }
        elif "report_writing" in prompt or "报告" in prompt:
            result = {
                "summary": "报告应先解释研究目标，再列出任务拆解、执行结果、审核结论、成本统计和后续建议。",
                "sections": ["研究目标", "任务拆解", "Agent 分工", "执行结果", "成本与耗时", "导师结论"],
            }
        else:
            result = {
                "summary": "完成了任务要求的初步分析，并给出了可执行的结果结构。",
                "findings": ["当前系统需要优先提升可读性", "事件日志和成本记录是后续监控 UI 的基础"],
                "recommendations": ["先修 P0 可观测链路", "再做像素办公室体验"],
            }
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _mock_subagent_result(self) -> str:
        return json.dumps(
            {
                "findings": [
                    {
                        "title": "事件流是运行监控的主数据源",
                        "detail": "每个阶段都应写入用户可读标题、说明和结构化 payload。",
                    },
                    {
                        "title": "取消只能作为服务端状态处理",
                        "detail": "前端 Abort 不能代表任务停止，后端需要在阶段边界检查取消标记。",
                    },
                ],
                "summary": "SubAgent 已完成辅助调研，结果需要由父 Agent 整合后再进入导师审核。",
            },
            ensure_ascii=False,
            indent=2,
        )

    def _mock_review(self) -> str:
        return json.dumps(
            {
                "approved": True,
                "feedback": "任务产出结构完整，能够支撑当前阶段报告。后续可以补充更细的指标和失败样例。",
            },
            ensure_ascii=False,
        )

    def _mock_report(self) -> str:
        return """# 阶段性研究报告

## 1. 研究目标

本次运行围绕用户提交的研究目标展开，由导师 Agent 拆解任务，并调度研究生 Agent 协作完成。

## 2. 任务拆解与分工

系统将目标拆分为文献调研、系统设计、实验设计、结果分析和报告写作等任务。

## 3. 执行结果

各 Agent 已生成结构化产出，导师审核后形成阶段性结论。

## 4. 成本与可观测性

建议后续持续记录 LLM 调用次数、token、耗时和成本，并在前端运行详情页集中展示。

## 5. 后续建议

先完成 P0 可读性、事件流、成本记录和停止控制，再推进像素办公室监控体验。
"""


class OpenAICompatibleProvider(LLMProvider):
    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        role: str = "graduate",
        run_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> str:
        model = settings.get_model_for_role(role)
        request_body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3 if role.startswith("advisor") else 0.7,
            "max_tokens": 4096,
        }

        if schema:
            request_body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema},
            }

        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            for attempt in range(settings.llm_max_retries):
                try:
                    response = await client.post(
                        f"{settings.llm_base_url}/chat/completions",
                        json=request_body,
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()
                    result = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    from ..services.cost_tracker import cost_tracker

                    cost_tracker.record(
                        role=role,
                        provider="openai_compatible",
                        model=model,
                        prompt=prompt,
                        completion=result,
                        run_id=run_id,
                        task_id=task_id,
                        agent_id=agent_id,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        success=True,
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                    )
                    return result
                except (httpx.HTTPError, KeyError, IndexError) as exc:
                    if attempt == settings.llm_max_retries - 1:
                        latency_ms = int((time.perf_counter() - started) * 1000)
                        from ..services.cost_tracker import cost_tracker

                        cost_tracker.record(
                            role=role,
                            provider="openai_compatible",
                            model=model,
                            prompt=prompt,
                            completion="",
                            run_id=run_id,
                            task_id=task_id,
                            agent_id=agent_id,
                            latency_ms=latency_ms,
                            success=False,
                            error=str(exc),
                        )
                        raise RuntimeError(f"LLM 调用失败，耗时 {latency_ms}ms: {exc}") from exc
        return ""


def create_llm_provider() -> LLMProvider:
    if settings.mock_mode:
        return MockLLMProvider()
    return OpenAICompatibleProvider()
