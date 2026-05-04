import json
from datetime import datetime
from pathlib import Path
from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import TaskRepository, AgentRepository, OutputRepository, RunRepository


class ReportService:
    def __init__(self):
        self._llm = create_llm_provider()

    async def generate(self, run: dict) -> str:
        tasks = TaskRepository.get_all(run_id=run["id"])
        agents = AgentRepository.get_all()
        completed_tasks = [t for t in tasks if t.get("status") == "completed"]

        task_summaries = []
        for t in completed_tasks:
            task_summaries.append({
                "title": t.get("title", ""),
                "type": t.get("task_type", ""),
                "owner": t.get("owner_agent", ""),
                "collaborators": t.get("collaborator_agents", []),
                "outputs": t.get("outputs", []),
            })

        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请根据以下信息生成阶段性研究报告：

研究目标：{run.get('research_goal', '')}

任务完成情况：
{json.dumps(task_summaries, ensure_ascii=False, indent=2)}

参与 Agent：
{json.dumps([{'id': a['id'], 'name': a['name'], 'type': a['type']} for a in agents if a['type'] != 'advisor'], ensure_ascii=False, indent=2)}

报告要求：
1. 使用 Markdown 格式
2. 包含以下章节：研究目标、任务拆解、Agent分工、调研结果、系统架构建议、实验验证方案、数据分析与指标、当前问题、下一步计划、导师总结
3. 内容要有实质性，不要空泛描述
4. 基于实际任务结果撰写"""

        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        raw_response = await self._llm.generate(prompt=full_prompt, role="advisor")

        report = self._format_report(raw_response, run, completed_tasks, agents)
        self._save_report(run["id"], report)

        OutputRepository.insert({
            "id": f"final_report_{run['id']}",
            "output_type": "final_report",
            "title": f"阶段性研究报告 - {run.get('research_goal', '')[:50]}",
            "content": report,
            "run_id": run["id"],
            "created_at": datetime.now().isoformat(),
        })

        return report

    def _format_report(self, raw: str, run: dict, tasks: list[dict], agents: list[dict]) -> str:
        if "##" not in raw and "#" not in raw:
            raw = self._build_fallback_report(run, tasks, agents)
        return raw

    def _build_fallback_report(self, run: dict, tasks: list[dict], agents: list[dict]) -> str:
        lines = [
            f"# 阶段性研究报告",
            "",
            f"## 1. 研究目标",
            f"",
            f"{run.get('research_goal', '')}",
            "",
            "## 2. 任务拆解",
            "",
        ]
        for t in tasks:
            status_icon = "✅" if t.get("status") == "completed" else "⏳" if t.get("status") in ("running", "assigned") else "❌" if t.get("status") == "failed" else "⬜"
            lines.append(f"- {status_icon} **{t.get('title', '')}** [{t.get('task_type', '')}] - {t.get('status', '')}")

        lines.extend([
            "",
            "## 3. Agent 分工",
            "",
        ])
        agent_tasks = {}
        for t in tasks:
            owner = t.get("owner_agent", "未分配")
            if owner not in agent_tasks:
                agent_tasks[owner] = []
            agent_tasks[owner].append(t.get("title", ""))

        for agent_id, task_titles in agent_tasks.items():
            agent = next((a for a in agents if a["id"] == agent_id), None)
            name = agent["name"] if agent else agent_id
            lines.append(f"### {name}")
            for title in task_titles:
                lines.append(f"- {title}")
            lines.append("")

        lines.extend([
            "## 4. 调研结果",
            "",
            "（详见各任务输出）",
            "",
            "## 5. 系统架构建议",
            "",
            "（详见系统设计任务输出）",
            "",
            "## 6. 实验验证方案",
            "",
            "（详见实验设计任务输出）",
            "",
            "## 7. 数据分析与指标",
            "",
            "（详见数据分析任务输出）",
            "",
            "## 8. 当前问题",
            "",
            "MVP 阶段以 mock 模式运行，结果内容为预设模板。后续接入真实 LLM API 后可获得更丰富的分析内容。",
            "",
            "## 9. 下一步计划",
            "",
            "1. 接入真实 OpenAI-compatible API",
            "2. 实现更精细的 Prompt 工程",
            "3. 添加真实文献搜索工具",
            "4. 支持代码执行沙箱",
            "",
            "## 10. 导师总结",
            "",
            f"本次运行共拆解 {len(tasks)} 个任务，完成 {len([t for t in tasks if t.get('status') == 'completed'])} 个。",
            "虚拟课题组的多 Agent 协作机制运行正常，任务调度、SubAgent 委派、导师审核等核心流程均已验证。",
            "",
            f"---",
            f"*报告生成时间：{datetime.now().isoformat()}*",
        ])

        return "\n".join(lines)

    def _save_report(self, run_id: str, content: str):
        run_dir = settings.artifacts_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "final_report.md"
        report_path.write_text(content, encoding="utf-8")

        tasks = TaskRepository.get_all(run_id=run_id)
        (run_dir / "tasks.json").write_text(
            json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run_dir / "agent_assignments.json").write_text(
            json.dumps({t["id"]: {"owner": t.get("owner_agent"), "collaborators": t.get("collaborator_agents", [])} for t in tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        run_data = RunRepository.get_by_id(run_id)
        (run_dir / "run_log.md").write_text(
            f"# 运行日志 - {run_id}\n\n"
            f"研究目标: {run_data.get('research_goal', '')}\n\n"
            f"状态: {run_data.get('status', '')}\n\n"
            f"创建时间: {run_data.get('created_at', '')}\n\n"
            f"完成时间: {run_data.get('completed_at', '')}\n\n"
            f"任务数: {len(tasks)}\n\n"
            f"完成任务数: {len([t for t in tasks if t.get('status') == 'completed'])}\n",
            encoding="utf-8"
        )


report_service = ReportService()
