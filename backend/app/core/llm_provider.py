import json
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from ..core.config import settings
from ..core.logger import logger


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
        prompt_len = len(prompt)
        logger.info("[LLM] Mock generate start | role=%s | run_id=%s | task_id=%s | prompt_len=%d", role, run_id, task_id, prompt_len)
        if role == "advisor_decompose":
            result = self._mock_advisor_decomposition()
        elif role == "advisor_contract":
            result = self._mock_research_contract(prompt)
        elif role == "advisor_review":
            result = self._mock_review()
        elif role == "advisor_report":
            result = self._mock_report()
        elif role == "subagent":
            result = self._mock_subagent_result()
        else:
            result = self._mock_graduate_result(prompt)

        latency = int((time.perf_counter() - started) * 1000)
        logger.info("[LLM] Mock generate end | role=%s | run_id=%s | latency=%dms | result_len=%d", role, run_id, latency, len(result))

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
            latency_ms=latency,
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

    def _mock_research_contract(self, prompt: str) -> str:
        goal = prompt.split("用户目标：", 1)[-1].split("要求：", 1)[0].strip() or "待研究问题"
        return json.dumps(
            {
                "research_type": "empirical",
                "primary_question": f"在可获得数据与明确基线下，如何验证“{goal}”的核心方案是否有效？",
                "objective": f"围绕“{goal}”形成可复现、可证伪且有证据支撑的研究结论。",
                "subquestions": [
                    {"id": "sq_literature", "question": "现有方法、数据和评价指标分别是什么？"},
                    {"id": "sq_method", "question": "候选方案相对基线的关键差异是什么？"},
                    {"id": "sq_evaluation", "question": "实验结果是否达到预先声明的最小效应？"},
                ],
                "scope_in": ["可核验公开文献", "可合法获取的数据", "可复现实验"],
                "scope_out": ["无法取得数据的效果断言", "未经复现的单次结果", "超出当前资源的部署验证"],
                "target_domain": "用户目标所限定的计算研究场景",
                "constraints": ["结论必须绑定证据或实验产物", "失败结果必须保留"],
                "expected_contribution": "给出相对基线的可复现实证比较及适用边界。",
                "novelty_criteria": ["方法或实证结论相对现有工作有可说明差异"],
                "data_availability": "执行前核验公开数据或用户上传数据；缺失时实验不可发布。",
                "ethics_risks": ["核验数据许可与隐私限制"],
                "success_criteria": ["核心主张有 passage 支撑", "实验达到预设最小效应并可复现"],
                "failure_criteria": ["关键全文或真实数据不可得", "相对基线未达到最小效应", "复现失败"],
                "discipline": {
                    "broad_field": "engineering", "field": "computer_science", "subfield": "computational_research",
                },
                "methodology_profile": {
                    "family": "computational", "epistemic_mode": "hypothesis_testing",
                    "study_design": "controlled comparative study", "unit_of_analysis": "evaluation item",
                    "evidence_types": ["verified literature passages", "raw benchmark observations"],
                    "data_collection_methods": ["versioned dataset execution"],
                    "analysis_methods": ["paired comparison", "uncertainty interval", "independent reproduction"],
                    "quality_criteria": ["construct validity", "reproducibility", "external-validity disclosure"],
                    "component_methods": [],
                },
                "resource_plan": [{
                    "resource_type": "licensed_dataset", "description": "合法且可版本化的研究数据",
                    "required": True, "status": "available", "owner": "user_or_public_source",
                    "evidence": "执行前由数据门复核", "resolution": "缺失时阻断实验而非生成指标",
                }],
                "ethics_plan": {
                    "required": False, "status": "not_required", "review_body": "",
                    "approval_reference": "", "data_sensitivity": "待数据门复核",
                    "participant_risks": [],
                },
                "thesis_requirements": {
                    "degree_level": "master", "institution": "", "programme": "",
                    "language": "zh-CN", "citation_style": "GB/T 7714", "target_word_count": 30000,
                    "minimum_references": 30, "minimum_supported_claims": 8,
                    "required_chapters": ["引言", "文献综述", "方法", "结果", "讨论", "结论"],
                    "status": "not_provided",
                },
                "hypotheses": [
                    {
                        "statement": "候选方案在目标场景的主指标上优于最小基线。",
                        "rationale": "以预注册比较替代无基线的效果陈述。",
                        "treatment": "候选方案", "baseline": "领域内可复现的最小合理基线",
                        "conditions": ["相同数据划分", "相同资源预算"],
                        "predicted_direction": "主指标提升", "primary_metric": "由领域协议冻结的主指标",
                        "minimum_effect": "相对基线至少提升 5% 或达到领域最小重要差异",
                        "falsification_criterion": "重复实验的置信区间未超过基线或未达到最小效应",
                    }
                ],
            },
            ensure_ascii=False,
        )

    def _mock_graduate_result(self, prompt: str) -> str:
        if "thesis_chapter" in prompt or "论文章节写作契约" in prompt:
            result = {
                "summary": "Mock 仅演示章节结构；篇幅和证据门应保持 fail-closed。",
                "chapter": {
                    "name": "Mock章节", "word_budget": 1000,
                    "sections": [{
                        "heading": "结构演示",
                        "paragraphs": [{
                            "id": "mock_p1", "text": "该段仅用于结构测试，不构成真实学位论文内容。" * 3,
                            "paragraph_type": "limitation", "support_ids": [],
                        }],
                    }],
                },
                "claims": [],
            }
        elif "research_design" in prompt or "研究设计" in prompt:
            family = next((item for item in (
                "quantitative", "qualitative", "computational", "experimental", "systematic_review",
                "humanities", "theoretical", "design_science", "mixed_methods",
            ) if f'"family": "{item}"' in prompt), "computational")
            result = {
                "summary": "已按冻结方法画像形成研究设计工作包。",
                "method_package": {
                    "family": family, "study_design": "按 Research Contract 冻结的研究设计",
                    "sampling_or_corpus_plan": "以契约声明的分析单位、纳排边界和资源清单为准",
                    "data_or_material_protocol": "只接收带来源、授权与完整性哈希的真实材料",
                    "analysis_plan": "使用 methodology_profile.analysis_methods 并执行方法专用检查",
                    "quality_controls": ["证据可追溯", "负例、反例或稳健性检查"],
                    "stopping_rule": "达到预注册充分性标准或资源/伦理门阻断",
                    "deviation_policy": "所有偏离均记录、说明影响并重新审核",
                },
            }
        elif "data_acquisition" in prompt or "材料与数据获取" in prompt:
            result = {
                "summary": "材料清单由系统从用户上传原文件生成；Mock 文本不作为原始研究材料。",
                "claims": [],
            }
        elif "system_design" in prompt or "系统设计" in prompt:
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
        result.setdefault(
            "claims",
            [
                {
                    "statement": "该任务已得出结构化结论，可作为后续阶段的输入。",
                    "evidence_source_ids": [],
                    "relation": "supports",
                    "confidence": 0.5,
                }
            ],
        )
        result.setdefault(
            "uncertainties",
            [{"description": "Mock 模式下结论未经真实证据核验。", "severity": "medium"}],
        )
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
    """Universal entry for any OpenAI-compatible chat completions endpoint.

    Users only need to provide a base URL, model name and API key. Because
    providers disagree on the `response_format` field (OpenAI supports strict
    `json_schema`, while DeepSeek/Moonshot/Qwen/local servers only support
    `json_object` or nothing), the JSON mode is chosen by `settings.llm_json_mode`
    and automatically downgrades on a 400 so the call succeeds across providers.
    """

    @staticmethod
    def _endpoint() -> str:
        base = (settings.llm_base_url or "").strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _format_strategies(self, schema: Optional[dict]) -> list[str]:
        """Ordered response_format strategies to attempt for this request."""
        if not schema:
            return ["none"]
        mode = (settings.llm_json_mode or "auto").strip().lower()
        if mode == "none":
            return ["none"]
        if mode == "json_object":
            return ["json_object", "none"]
        if mode == "json_schema":
            return ["json_schema", "json_object", "none"]
        # auto: OpenAI endpoints get strict schema first; everyone else starts at
        # json_object. Both fall back to none so an unknown provider still works.
        base = (settings.llm_base_url or "").lower()
        if "openai.com" in base or "azure" in base:
            return ["json_schema", "json_object", "none"]
        return ["json_object", "none"]

    def _build_body(self, prompt: str, schema: Optional[dict], model: str, role: str, rf_mode: str) -> dict:
        messages = [{"role": "user", "content": prompt}]
        # json_object mode on several providers requires the word "json" to appear
        # in the messages; add a tiny system hint when it is missing.
        if rf_mode in ("json_object", "json_schema") and "json" not in prompt.lower():
            messages.insert(0, {"role": "system", "content": "You must respond with a single valid JSON value only."})
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": settings.get_temperature_for_role(role),
            "max_tokens": settings.llm_max_tokens,
        }
        if rf_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema},
            }
        elif rf_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

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
        endpoint = self._endpoint()
        strategies = self._format_strategies(schema)
        logger.info("[LLM] OpenAI generate start | role=%s | model=%s | run_id=%s | task_id=%s | prompt_len=%d | has_schema=%s | json_modes=%s",
                    role, model, run_id, task_id, len(prompt), bool(schema), ",".join(strategies))
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            for rf_mode in strategies:
                request_body = self._build_body(prompt, schema, model, role, rf_mode)
                for attempt in range(settings.llm_max_retries):
                    try:
                        response = await client.post(endpoint, json=request_body, headers=headers)
                        response.raise_for_status()
                        data = response.json()
                        result = data["choices"][0]["message"]["content"]
                        if not isinstance(result, str):
                            result = str(result) if result is not None else ""
                        usage = data.get("usage", {})
                        latency = int((time.perf_counter() - started) * 1000)
                        logger.info("[LLM] OpenAI success | role=%s | model=%s | json_mode=%s | latency=%dms | prompt_tokens=%s | completion_tokens=%s | result_len=%d",
                                    role, model, rf_mode, latency, usage.get("prompt_tokens"), usage.get("completion_tokens"), len(result))
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
                            latency_ms=latency,
                            success=True,
                            prompt_tokens=usage.get("prompt_tokens"),
                            completion_tokens=usage.get("completion_tokens"),
                        )
                        return result
                    except httpx.HTTPStatusError as exc:
                        detail = self._error_detail(exc)
                        last_error = RuntimeError(detail)
                        # A 400 usually means the endpoint rejected this request shape
                        # (most often response_format). Stop retrying and downgrade the
                        # JSON mode instead of hammering the same bad body.
                        if exc.response.status_code == 400 and rf_mode != strategies[-1]:
                            logger.warning("[LLM] 400 with json_mode=%s, downgrading | role=%s | detail=%s", rf_mode, role, detail)
                            break
                        logger.warning("[LLM] OpenAI attempt %d failed | role=%s | json_mode=%s | error=%s", attempt + 1, role, rf_mode, detail)
                        if attempt == settings.llm_max_retries - 1:
                            break
                    except (httpx.HTTPError, KeyError, IndexError) as exc:
                        last_error = exc
                        logger.warning("[LLM] OpenAI attempt %d failed | role=%s | json_mode=%s | error=%s", attempt + 1, role, rf_mode, exc)
                        if attempt == settings.llm_max_retries - 1:
                            break

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.error("[LLM] OpenAI final failure | role=%s | latency=%dms | error=%s", role, latency_ms, last_error)
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
            error=str(last_error),
        )
        raise RuntimeError(f"LLM 调用失败，耗时 {latency_ms}ms: {last_error}")

    @staticmethod
    def _error_detail(exc: httpx.HTTPStatusError) -> str:
        status = exc.response.status_code
        try:
            body = exc.response.json()
            message = body.get("error", {}).get("message") if isinstance(body, dict) else None
        except (ValueError, AttributeError):
            message = None
        if not message:
            message = (exc.response.text or "")[:300]
        return f"HTTP {status} from {exc.request.url}: {message}".strip()


def create_llm_provider() -> LLMProvider:
    if settings.mock_mode:
        return MockLLMProvider()
    return OpenAICompatibleProvider()
