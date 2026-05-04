import json
import random
from abc import ABC, abstractmethod
from typing import Optional
import httpx
from ..core.config import settings


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, schema: Optional[dict] = None, role: str = "graduate") -> str:
        pass


class MockLLMProvider(LLMProvider):
    async def generate(self, prompt: str, schema: Optional[dict] = None, role: str = "graduate") -> str:
        if role == "advisor":
            return self._mock_advisor_decomposition()
        elif role == "subagent":
            return self._mock_subagent_result(schema)
        elif "review" in prompt.lower():
            return self._mock_review()
        elif "report" in prompt.lower() or "summary" in prompt.lower():
            return self._mock_report()
        else:
            return self._mock_graduate_result(schema)

    def _mock_advisor_decomposition(self) -> str:
        return json.dumps([
            {
                "title": "调研已有相关系统与工具",
                "description": "搜索并分析现有多Agent协作系统和科研辅助工具，整理功能对比与技术栈。",
                "task_type": "literature_survey",
                "priority": 9,
                "complexity": 7,
                "decomposability": 9,
                "required_skills": {
                    "literature_review": 9, "coding": 2, "experiment": 1,
                    "data_analysis": 4, "academic_writing": 7, "mentoring": 6
                }
            },
            {
                "title": "设计系统架构方案",
                "description": "设计ResearchGroup-Agent MVP的整体架构，包括技术选型、模块划分和数据流。",
                "task_type": "system_design",
                "priority": 9,
                "complexity": 8,
                "decomposability": 6,
                "required_skills": {
                    "literature_review": 3, "coding": 9, "experiment": 4,
                    "data_analysis": 4, "academic_writing": 5, "mentoring": 5
                }
            },
            {
                "title": "设计实验验证方案",
                "description": "设计用于验证系统效果的实验方案，包括评价指标、实验步骤和预期结果。",
                "task_type": "experiment_design",
                "priority": 7,
                "complexity": 8,
                "decomposability": 7,
                "required_skills": {
                    "literature_review": 4, "coding": 5, "experiment": 9,
                    "data_analysis": 7, "academic_writing": 5, "mentoring": 6
                }
            },
            {
                "title": "数据分析与指标设计",
                "description": "定义系统运行的关键指标，设计数据采集和分析方案。",
                "task_type": "result_analysis",
                "priority": 8,
                "complexity": 7,
                "decomposability": 7,
                "required_skills": {
                    "literature_review": 3, "coding": 5, "experiment": 6,
                    "data_analysis": 10, "academic_writing": 6, "mentoring": 5
                }
            },
            {
                "title": "汇总阶段性周报",
                "description": "整合所有调研和设计结果，撰写阶段性周报和项目总结。",
                "task_type": "report_writing",
                "priority": 8,
                "complexity": 6,
                "decomposability": 5,
                "required_skills": {
                    "literature_review": 6, "coding": 2, "experiment": 3,
                    "data_analysis": 5, "academic_writing": 10, "mentoring": 5
                }
            }
        ], ensure_ascii=False, indent=2)

    def _mock_graduate_result(self, schema: Optional[dict] = None) -> str:
        results = {
            "literature_survey": json.dumps({
                "summary": "已完成相关系统调研，共发现5个主要的多Agent协作框架：LangGraph、AutoGen、CrewAI、MetaGPT、ChatDev。",
                "comparison_table": [
                    {"name": "LangGraph", "focus": "状态图编排", "language": "Python"},
                    {"name": "AutoGen", "focus": "对话式协作", "language": "Python"},
                    {"name": "CrewAI", "focus": "角色分工", "language": "Python"},
                    {"name": "MetaGPT", "focus": "SOP驱动", "language": "Python"},
                    {"name": "ChatDev", "focus": "软件开发生命周期", "language": "Python"}
                ],
                "key_findings": "现有系统多聚焦于软件工程场景，缺少面向学术课题组的分层管理机制。",
                "recommendations": "建议采用导师-研究生-本科生三层Agent架构，支持任务板可视化。"
            }, ensure_ascii=False, indent=2),
            "system_design": json.dumps({
                "architecture": "前后端分离架构，FastAPI + React，SQLite 本地存储",
                "modules": ["Agent管理", "任务调度", "SubAgent管理", "审核服务", "报告生成"],
                "tech_stack": {"backend": "Python FastAPI", "frontend": "React/Next.js", "database": "SQLite"},
                "data_flow": "用户输入 → 导师拆解 → 调度分配 → Agent执行 → 审核 → 报告"
            }, ensure_ascii=False, indent=2),
            "experiment_design": json.dumps({
                "objective": "验证多Agent课题组协作系统的有效性和效率",
                "metrics": ["任务完成率", "协作效率", "SubAgent利用率", "审核通过率"],
                "procedure": ["定义基准任务集", "运行单Agent基线", "运行多Agent协作", "对比分析结果"],
                "expected_outcome": "多Agent协作在复杂任务上表现优于单Agent"
            }, ensure_ascii=False, indent=2),
            "result_analysis": json.dumps({
                "key_metrics": {"任务完成率": 0.95, "平均执行时间": "180s", "协作效率提升": "35%"},
                "analysis": "多Agent协作在跨领域任务上有显著效率提升，SubAgent机制有效分担了主Agent的负载。",
                "visualization_data": {"labels": ["调研", "设计", "实验", "分析", "写作"], "values": [4.2, 3.8, 3.5, 4.0, 4.5]}
            }, ensure_ascii=False, indent=2),
            "report_writing": json.dumps({
                "title": "阶段性研究报告",
                "sections": ["项目背景", "系统调研", "架构设计", "实验方案", "数据分析", "下一步计划"],
                "summary": "本次调研完成多Agent协作系统分析，提出了面向课题组的架构方案，设计了验证实验。"
            }, ensure_ascii=False, indent=2),
        }
        if schema and "task_type" in schema:
            return results.get(schema["task_type"], json.dumps({"result": "任务执行完成", "confidence": 0.85}, ensure_ascii=False))
        task_type = random.choice(list(results.keys()))
        return results[task_type]

    def _mock_subagent_result(self, schema: Optional[dict] = None) -> str:
        return json.dumps({
            "findings": [
                {"project_name": "LangGraph", "link": "https://github.com/langchain-ai/langgraph", "main_features": "状态图Agent编排", "tech_stack": "Python, LangChain", "relevance": "高"},
                {"project_name": "AutoGen", "link": "https://github.com/microsoft/autogen", "main_features": "多Agent对话协作", "tech_stack": "Python", "relevance": "高"},
                {"project_name": "CrewAI", "link": "https://github.com/crewAIInc/crewAI", "main_features": "角色化Agent协作", "tech_stack": "Python", "relevance": "中"},
                {"project_name": "MetaGPT", "link": "https://github.com/geekan/MetaGPT", "main_features": "SOP驱动多Agent开发", "tech_stack": "Python", "relevance": "中"},
                {"project_name": "ChatDev", "link": "https://github.com/OpenBMB/ChatDev", "main_features": "软件开发生命周期模拟", "tech_stack": "Python", "relevance": "低"}
            ],
            "summary": "共找到5个高相关项目，技术栈以Python为主。"
        }, ensure_ascii=False, indent=2)

    def _mock_review(self) -> str:
        if random.random() < 0.15:
            return json.dumps({"approved": False, "feedback": "结果分析不够深入，请补充更多量化指标和对比数据。"}, ensure_ascii=False)
        return json.dumps({"approved": True, "feedback": "任务完成质量良好，结果结构清晰，可以进入下一步。"}, ensure_ascii=False)

    def _mock_report(self) -> str:
        return json.dumps({"report": "mock_report_content_placeholder"}, ensure_ascii=False)


class OpenAICompatibleProvider(LLMProvider):
    async def generate(self, prompt: str, schema: Optional[dict] = None, role: str = "graduate") -> str:
        model = settings.get_model_for_role(role)
        messages = [{"role": "user", "content": prompt}]

        request_body = {
            "model": model,
            "messages": messages,
            "temperature": 0.7 if role != "advisor" else 0.3,
            "max_tokens": 4096,
        }

        if schema:
            request_body["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}

        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }

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
                    return data["choices"][0]["message"]["content"]
                except (httpx.HTTPError, KeyError, IndexError) as e:
                    if attempt == settings.llm_max_retries - 1:
                        raise RuntimeError(f"LLM调用失败（已重试{settings.llm_max_retries}次）: {e}")
        return ""


def create_llm_provider() -> LLMProvider:
    if settings.mock_mode:
        return MockLLMProvider()
    return OpenAICompatibleProvider()
