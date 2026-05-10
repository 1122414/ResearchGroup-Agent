import json
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import AgentRepository, OutputRepository, RunRepository, TaskRepository


class ReportService:
    def __init__(self):
        self._llm = create_llm_provider()

    async def generate(self, run: dict) -> str:
        tasks = TaskRepository.get_all(run_id=run["id"])
        agents = AgentRepository.get_all()
        completed_tasks = [task for task in tasks if task.get("status") == "completed"]
        task_summaries = [
            {
                "title": task.get("title", ""),
                "type": task.get("task_type", ""),
                "owner": task.get("owner_agent", ""),
                "collaborators": task.get("collaborator_agents", []),
                "outputs": task.get("outputs", []),
                "review": task.get("review_result"),
            }
            for task in completed_tasks
        ]

        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请基于已完成任务生成 Markdown 阶段报告。

研究目标：
{run.get('research_goal', '')}

已完成任务摘要：
{json.dumps(task_summaries, ensure_ascii=False, indent=2)}

Agent 列表：
{json.dumps([{'id': a['id'], 'name': a['name'], 'type': a['type']} for a in agents], ensure_ascii=False, indent=2)}

报告必须包含：研究目标、任务拆解、Agent 分工、执行结果、导师结论、后续建议。
"""

        raw_response = await self._llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            role="advisor_report",
            run_id=run["id"],
        )

        report = self._format_report(raw_response, run, tasks, agents)
        self._save_report(run["id"], report)
        OutputRepository.insert(
            {
                "id": f"final_report_{run['id']}",
                "output_type": "final_report",
                "title": f"阶段性研究报告：{run.get('research_goal', '')[:50]}",
                "content": report,
                "run_id": run["id"],
                "created_at": datetime.now().isoformat(),
            }
        )
        return report

    def _format_report(self, raw: str, run: dict, tasks: list[dict], agents: list[dict]) -> str:
        if "##" in raw or "#" in raw:
            return raw
        return self._build_fallback_report(run, tasks, agents)

    def _build_fallback_report(self, run: dict, tasks: list[dict], agents: list[dict]) -> str:
        lines = [
            "# 阶段性研究报告",
            "",
            "## 1. 研究目标",
            "",
            run.get("research_goal", ""),
            "",
            "## 2. 任务拆解",
            "",
        ]
        for task in tasks:
            lines.append(f"- **{task.get('title', '')}**：{task.get('status', '')}，负责人 {task.get('owner_agent') or '未分配'}")

        lines.extend(["", "## 3. Agent 分工", ""])
        for agent in agents:
            if agent.get("type") not in ("researcher", "engineer", "experimenter", "analyst", "writer"):
                continue
            owned = [task.get("title", "") for task in tasks if task.get("owner_agent") == agent["id"]]
            lines.append(f"### {agent.get('name', agent['id'])}")
            lines.append(agent.get("description", ""))
            if owned:
                for title in owned:
                    lines.append(f"- {title}")
            else:
                lines.append("- 本轮没有分配主责任务。")
            lines.append("")

        completed = len([task for task in tasks if task.get("status") == "completed"])
        need_revision = len([task for task in tasks if task.get("status") == "need_revision"])
        failed = len([task for task in tasks if task.get("status") == "failed"])
        lines.extend(
            [
                "## 4. 执行结果",
                "",
                f"- 任务总数：{len(tasks)}",
                f"- 已完成：{completed}",
                f"- 需要修改：{need_revision}",
                f"- 失败：{failed}",
                "",
                "## 5. 导师结论",
                "",
                "本轮任务完成了基础协作流程，后续应优先增强运行可观测性、成本记录和停止控制。",
                "",
                "## 6. 后续建议",
                "",
                "1. 补充 Run 事件日志和运行详情页。",
                "2. 记录 LLM 调用成本和耗时。",
                "3. 在前端提供停止任务能力。",
                "4. P0 稳定后再推进像素办公室监控。",
                "",
                f"---",
                f"*生成时间：{datetime.now().isoformat()}*",
            ]
        )
        return "\n".join(lines)

    def _save_report(self, run_id: str, content: str):
        run_dir = settings.artifacts_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "final_report.md").write_text(content, encoding="utf-8")

        tasks = TaskRepository.get_all(run_id=run_id)
        (run_dir / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "agent_assignments.json").write_text(
            json.dumps(
                {
                    task["id"]: {
                        "owner": task.get("owner_agent"),
                        "collaborators": task.get("collaborator_agents", []),
                    }
                    for task in tasks
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        run_data = RunRepository.get_by_id(run_id) or {}
        (run_dir / "run_log.md").write_text(
            "\n".join(
                [
                    f"# 运行日志 - {run_id}",
                    "",
                    f"研究目标：{run_data.get('research_goal', '')}",
                    "",
                    f"状态：{run_data.get('status', '')}",
                    "",
                    f"创建时间：{run_data.get('created_at', '')}",
                    "",
                    f"完成时间：{run_data.get('completed_at', '')}",
                    "",
                    f"任务总数：{len(tasks)}",
                    "",
                    f"完成任务数：{len([task for task in tasks if task.get('status') == 'completed'])}",
                    "",
                ]
            ),
            encoding="utf-8",
        )


report_service = ReportService()
