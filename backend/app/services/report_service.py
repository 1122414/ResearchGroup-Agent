import json
import re
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import AgentRepository, OutputRepository, RunRepository, TaskRepository


class ReportService:
    async def generate(self, run: dict) -> str:
        logger.info("[ReportService] generate started | run_id=%s", run["id"])
        tasks = TaskRepository.get_all(run_id=run["id"])
        agents = AgentRepository.get_all()
        agent_time = self._agent_time_label()
        goal = self._primary_goal(run)
        task_summaries = self._task_summaries(tasks, agents)

        review_summary = self._build_review_summary(run, tasks, agents, agent_time)
        OutputRepository.insert(
            {
                "id": f"review_summary_{run['id']}",
                "output_type": "review_summary",
                "title": f"导师审核汇总：{goal[:50]}",
                "content": review_summary,
                "run_id": run["id"],
                "created_at": datetime.now().isoformat(),
            }
        )

        writer_agent = next((agent for agent in agents if agent.get("type") == "writer"), None)
        writer_draft = await self._generate_writer_draft(run, writer_agent, task_summaries, review_summary, agent_time)
        OutputRepository.insert(
            {
                "id": f"final_report_draft_{run['id']}",
                "output_type": "final_report_draft",
                "title": f"写作研究生最终报告初稿：{goal[:50]}",
                "content": writer_draft,
                "run_id": run["id"],
                "agent_id": writer_agent.get("id") if writer_agent else None,
                "created_at": datetime.now().isoformat(),
            }
        )

        advisor_final = await self._generate_advisor_final(run, writer_draft, task_summaries, review_summary, agent_time)
        if settings.mock_mode:
            report = self._normalize_final_report(self._build_fallback_report(run, tasks, agents, agent_time), run, agent_time)
        else:
            report = self._format_final_report(advisor_final, run, tasks, agents, agent_time)

        self._save_report(run["id"], report, review_summary, writer_draft)
        OutputRepository.insert(
            {
                "id": f"final_report_{run['id']}",
                "output_type": "final_report",
                "title": f"最终研究报告：{goal[:50]}",
                "content": report,
                "run_id": run["id"],
                "created_at": datetime.now().isoformat(),
            }
        )
        logger.info("[ReportService] generate completed | run_id=%s | report_length=%d", run["id"], len(report))
        return report

    async def _generate_writer_draft(self, run: dict, writer_agent: dict | None, task_summaries: list[dict], review_summary: str, agent_time: str) -> str:
        goal = self._primary_goal(run)
        system_prompt = prompt_loader.load("grad_writer")
        user_prompt = f"""请以写作研究生 Agent 的身份，等待全部调研任务完成并通过导师审核后，整合所有任务产出，起草一份 Markdown 最终研究报告初稿。

当前 Agent 时间：{agent_time}
研究目标：{goal}

已完成并审核的任务产出：
{json.dumps(task_summaries, ensure_ascii=False, indent=2)}

导师阶段审核汇总：
{review_summary}

要求：
1. 输出完整 Markdown，不要输出 JSON。
2. 报告必须围绕研究目标给出最终结论，而不是逐条复述审核意见。
3. 至少包含：研究目标、核心结论、对比分析、证据与任务来源、局限性、建议。
"""
        llm = create_llm_provider()
        raw = await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            role="graduate",
            run_id=run["id"],
            agent_id=writer_agent.get("id") if writer_agent else None,
        )
        if settings.mock_mode or not raw.strip().startswith("#"):
            return self._build_writer_draft(run, task_summaries, agent_time)
        return raw.strip()

    async def _generate_advisor_final(self, run: dict, writer_draft: str, task_summaries: list[dict], review_summary: str, agent_time: str) -> str:
        goal = self._primary_goal(run)
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请以导师 Agent 的身份，审核写作研究生提交的最终报告初稿，并给出可直接发布的 Markdown 最终研究报告。

当前 Agent 时间：{agent_time}
研究目标：{goal}

写作研究生初稿：
{writer_draft}

任务产出索引：
{json.dumps(task_summaries, ensure_ascii=False, indent=2)}

导师阶段审核汇总：
{review_summary}

要求：
1. 输出最终 Markdown 报告，不要输出审核对话或 JSON。
2. 修正不一致、遗漏、重复和证据不足之处。
3. 保留清晰的小标题、结论和可追溯依据。
"""
        llm = create_llm_provider()
        return await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            role="advisor_report",
            run_id=run["id"],
        )

    def _format_final_report(self, raw: str, run: dict, tasks: list[dict], agents: list[dict], agent_time: str) -> str:
        text = raw.strip()
        first_heading = text.find("#")
        if first_heading > 0:
            text = text[first_heading:].strip()
        if not ("##" in text or text.startswith("#")):
            text = self._build_fallback_report(run, tasks, agents, agent_time)
        return self._normalize_final_report(text, run, agent_time)

    def _normalize_final_report(self, text: str, run: dict, agent_time: str) -> str:
        goal = self._primary_goal(run)
        lines = []
        for line in text.splitlines():
            if re.search(r"报告生成时间|研究目标|起草 Agent|审核 Agent", line):
                continue
            lines.append(line)

        title_index = next((idx for idx, line in enumerate(lines) if line.strip().startswith("#")), None)
        if title_index is None:
            lines.insert(0, f"# 最终研究报告：{goal}")
            title_index = 0
        else:
            lines[title_index] = f"# 最终研究报告：{goal}"

        metadata = [
            "",
            f"**报告生成时间:** {agent_time}",
            f"**研究目标:** {goal}",
            "**起草 Agent:** 写作研究生",
            "**审核 Agent:** 导师 Agent",
            "",
            "---",
            "",
        ]
        return "\n".join(lines[: title_index + 1] + metadata + lines[title_index + 1 :]).strip() + "\n"

    def _build_writer_draft(self, run: dict, task_summaries: list[dict], agent_time: str) -> str:
        goal = self._primary_goal(run)
        lines = [
            f"# 写作研究生最终报告初稿：{goal}",
            "",
            f"**起草时间:** {agent_time}",
            "",
            "## 研究目标",
            "",
            f"本报告围绕“{goal}”整合已完成任务的调研、分析和导师审核意见，形成最终报告初稿。",
            "",
            "## 关键发现",
            "",
        ]
        if not task_summaries:
            lines.append("当前运行没有可汇总的已完成任务产出。")
        for item in task_summaries:
            lines.extend(
                [
                    f"### {item['title']}",
                    "",
                    f"- 负责 Agent：{item['owner_name']}",
                    f"- 任务类型：{item['task_type']}",
                    f"- 审核结论：{item['review_feedback']}",
                ]
            )
            for summary in item["output_points"][:3]:
                lines.append(f"- 产出要点：{summary}")
            lines.append("")
        lines.extend(
            [
                "## 初步结论",
                "",
                "写作研究生认为，最终结论应基于已通过导师审核的任务产出进行综合，而不是仅复述单次审核结果。后续由导师 Agent 进行终审、纠偏和定稿。",
            ]
        )
        return "\n".join(lines)

    def _build_fallback_report(self, run: dict, tasks: list[dict], agents: list[dict], agent_time: str) -> str:
        goal = self._primary_goal(run)
        completed = [task for task in tasks if task.get("status") == "completed"]
        need_revision = [task for task in tasks if task.get("status") == "need_revision"]
        lines = [
            f"# 最终研究报告：{goal}",
            "",
            "## 研究目标",
            "",
            f"本报告总结课题“{goal}”的全部调研结果，并在写作研究生整合后由导师 Agent 审核定稿。",
            "",
            "## 核心结论",
            "",
            "系统已将各研究生 Agent 的任务产出、SubAgent 协作结果与导师审核意见合并为最终研究结论。最终报告优先采用已通过导师审核的任务产出；需要修改的任务仅作为风险与局限性参考。",
            "",
            "## 任务产出汇总",
            "",
        ]
        for task in completed:
            lines.append(f"### {task.get('title', '')}")
            lines.append("")
            lines.append(f"- 负责 Agent：{self._agent_name(agents, task.get('owner_agent'))}")
            lines.append(f"- 任务类型：{task.get('task_type', '')}")
            review = task.get("review_result") or {}
            lines.append(f"- 导师审核：{review.get('feedback', '已通过')}")
            lines.extend(self._summarize_outputs(task.get("outputs", [])))
            lines.append("")

        if not completed:
            lines.append("暂无通过审核的任务产出，最终报告仅能给出过程性结论。")
            lines.append("")

        lines.extend(
            [
                "## 局限性",
                "",
                f"- 需要修改的任务数：{len(need_revision)}",
                "- Mock 模式下的内容为结构化模拟产物，真实研究质量取决于配置的 LLM 与输入材料质量。",
                "",
                "## 建议",
                "",
                "1. 对需要修改的任务重新执行或补充资料。",
                "2. 在涉及图片、扫描件或复杂 PDF 时，配置支持多模态或高质量文档解析的模型。",
                "3. 将最终报告与导师审核汇总同时保留，便于区分最终结论和过程性审核意见。",
            ]
        )
        return "\n".join(lines)

    def _build_review_summary(self, run: dict, tasks: list[dict], agents: list[dict], agent_time: str) -> str:
        goal = self._primary_goal(run)
        lines = [
            f"# 导师审核汇总：{goal}",
            "",
            f"**生成时间:** {agent_time}",
            "",
            "这份文档记录导师 Agent 对各任务产出的阶段性审核意见，用于追踪质量控制过程；它不是最终研究报告。",
            "",
            "## 审核明细",
            "",
        ]
        for index, task in enumerate(tasks, start=1):
            review = task.get("review_result") or {}
            approved = "通过" if review.get("approved") else ("需要修改" if review else "未审核")
            lines.extend(
                [
                    f"### 任务 {index:02d}：{task.get('title', '')}",
                    "",
                    f"- 负责 Agent：{self._agent_name(agents, task.get('owner_agent'))}",
                    f"- 任务状态：{task.get('status', '')}",
                    f"- 审核结论：{approved}",
                    f"- 导师意见：{review.get('feedback', task.get('review_feedback') or '暂无')}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _task_summaries(self, tasks: list[dict], agents: list[dict]) -> list[dict]:
        items: list[dict] = []
        for task in tasks:
            if task.get("status") != "completed":
                continue
            review = task.get("review_result") or {}
            items.append(
                {
                    "title": task.get("title", ""),
                    "task_type": task.get("task_type", ""),
                    "owner": task.get("owner_agent", ""),
                    "owner_name": self._agent_name(agents, task.get("owner_agent")),
                    "collaborators": task.get("collaborator_agents", []),
                    "output_points": self._output_points(task.get("outputs", [])),
                    "review_feedback": review.get("feedback", task.get("review_feedback") or "已通过"),
                }
            )
        return items

    def _output_points(self, outputs: list) -> list[str]:
        points: list[str] = []
        for output in outputs:
            if isinstance(output, dict):
                for key in ("summary", "conclusion", "final_conclusion", "raw_output"):
                    value = output.get(key)
                    if value:
                        points.append(str(value)[:500])
                for key in ("findings", "deliverables", "recommendations", "next_steps", "key_metrics", "sections", "metrics"):
                    value = output.get(key)
                    if value:
                        points.append(f"{key}: {json.dumps(value, ensure_ascii=False)[:500]}")
            elif output:
                points.append(str(output)[:500])
        return points or ["该任务已完成，但未留下结构化摘要。"]

    def _summarize_outputs(self, outputs: list) -> list[str]:
        return [f"- 产出要点：{point}" for point in self._output_points(outputs)[:5]]

    def _agent_name(self, agents: list[dict], agent_id: str | None) -> str:
        if not agent_id:
            return "未分配"
        agent = next((item for item in agents if item.get("id") == agent_id), None)
        return agent.get("name", agent_id) if agent else agent_id

    def _primary_goal(self, run: dict) -> str:
        goal = str(run.get("research_goal", "")).strip()
        return goal.split("## 用户上传的多模态附件上下文", 1)[0].strip()

    def _agent_time_label(self) -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _save_report(self, run_id: str, content: str, review_summary: str, writer_draft: str):
        run_dir = settings.artifacts_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "final_report.md").write_text(content, encoding="utf-8")
        (run_dir / "review_summary.md").write_text(review_summary, encoding="utf-8")
        (run_dir / "writer_final_draft.md").write_text(writer_draft, encoding="utf-8")

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
                    f"研究目标：{self._primary_goal(run_data)}",
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
