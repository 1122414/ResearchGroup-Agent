import json
import re
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..core.research_goal import primary_goal
from ..storage.repositories import (
    AgentRepository,
    EvidenceRepository,
    ExperimentFindingRepository,
    ExperimentResultRepository,
    OutputRepository,
    ResearchClaimRepository,
    ResearchBriefRepository,
    ResearchMilestoneRepository,
    RunRepository,
    TaskRepository,
)
from .run_artifact_service import run_artifact_service
from .artifact_manifest_service import artifact_manifest_service
from .grounding_audit_service import grounding_audit_service
from .paper_assembly_service import paper_assembly_service
from .run_event_service import run_event_service
from .scientific_quality_gate_service import scientific_quality_gate_service
from .thesis_chapter_service import thesis_chapter_service


class ReportGroundingError(RuntimeError):
    pass


class ReportQualityError(RuntimeError):
    pass


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

        narrative = await self._writer_reviewer_loop(
            run, writer_agent, writer_draft, task_summaries, review_summary, agent_time
        )

        # Derive a concise report title — either extract the first H1 from the
        # LLM narrative (advisor's final version usually has a proper title) or
        # generate one via LLM.  This avoids dumping the raw research-goal
        # prompt into the document heading.
        title = self._extract_title_from_narrative(narrative)
        if not title:
            title = await self._generate_title(run, task_summaries)

        # The final report is always assembled from the knowledge graph so that
        # claims, tables and citations are grounded. The free-form writer draft is
        # retained as an artifact, but cannot enter the publishable report until it
        # has sentence-level evidence bindings.
        mode = paper_assembly_service.detect_mode(run, tasks)
        report = (
            thesis_chapter_service.assemble(run, title)
            if thesis_chapter_service.can_assemble(run["id"])
            else paper_assembly_service.assemble(run, mode=mode, narrative="", title=title)
        )

        grounding_audit = self._run_grounding_audit(run["id"], report)
        scientific_quality = self._run_scientific_quality_gate(run["id"], report, grounding_audit)
        report = self._promote_delivery_status(report, scientific_quality)
        self._mark_report_verified(run["id"])
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

    @staticmethod
    def _promote_delivery_status(report: str, quality: dict) -> str:
        if quality.get("master_thesis_ready") and "`master_thesis_candidate`" in report:
            return report.replace("`master_thesis_candidate`", "`master_thesis`", 1)
        if quality.get("publication_ready") and "`thesis_draft`" in report:
            return report.replace("`thesis_draft`", "`publishable_manuscript`", 1)
        return report

    @staticmethod
    def _run_scientific_quality_gate(run_id: str, report: str, grounding_audit: dict) -> dict:
        quality = scientific_quality_gate_service.evaluate_report(run_id, report, grounding_audit)
        OutputRepository.insert(
            {
                "id": f"scientific_quality_gate_{run_id}", "output_type": "scientific_quality_gate",
                "title": "五层科学质量门报告", "content": json.dumps(quality, ensure_ascii=False, indent=2),
                "run_id": run_id, "created_at": datetime.now().isoformat(),
            }
        )
        run_event_service.emit(
            run_id, "report.scientific_quality_gate", "report", "五层科学质量门完成",
            f"通过={quality['passed']}", payload=quality,
        )
        if not quality["passed"]:
            failed = [name for name, result in quality["layers"].items() if not result["passed"]]
            raise ReportQualityError("报告科学质量门未通过：" + "、".join(failed))
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        if (brief.get("thesis_requirements") or {}).get("status") == "confirmed" and not quality.get(
            "master_thesis_ready"
        ):
            issues = (quality.get("thesis_quality") or {}).get("issues") or [
                item.get("description") for item in quality.get("master_thesis_blockers") or []
            ]
            raise ReportQualityError("完整硕士论文门未通过：" + "；".join(filter(None, issues[:8])))
        return quality

    def _run_grounding_audit(self, run_id: str, report: str) -> dict:
        audit = grounding_audit_service.audit_report(report)
        if not audit.get("checked"):
            return audit
        OutputRepository.insert(
            {
                "id": f"grounding_audit_{run_id}",
                "output_type": "grounding_audit",
                "title": "接地审计报告",
                "content": json.dumps(audit, ensure_ascii=False, indent=2),
                "run_id": run_id,
                "created_at": datetime.now().isoformat(),
            }
        )
        run_event_service.emit(
            run_id,
            "report.grounding_audit",
            "report",
            "接地审计完成",
            f"通过={audit['passed']} 无效引用={len(audit['invalid_citations'])} 缺引用结论={audit['uncited_claim_count']}",
            payload=audit,
        )
        if not audit["passed"]:
            logger.warning(
                "[ReportService] grounding audit issues | run_id=%s | invalid=%s | uncited=%d",
                run_id,
                audit["invalid_citations"],
                audit["uncited_claim_count"],
            )
            raise ReportGroundingError(
                f"报告接地审计未通过：无效引用 {len(audit['invalid_citations'])}，"
                f"缺少引用的结论 {audit['uncited_claim_count']}"
            )
        return audit

    @staticmethod
    def _mark_report_verified(run_id: str) -> None:
        milestone = next(
            (
                item
                for item in ResearchMilestoneRepository.get_by_run(run_id)
                if item["milestone_key"] == "report_verified"
            ),
            None,
        )
        if milestone:
            now = datetime.now().isoformat()
            ResearchMilestoneRepository.update(milestone["id"], status="passed", completed_at=now, updated_at=now)

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

    async def _writer_reviewer_loop(
        self,
        run: dict,
        writer_agent: dict | None,
        writer_draft: str,
        task_summaries: list[dict],
        review_summary: str,
        agent_time: str,
    ) -> str:
        """Bounded writer<->reviewer revision rounds on the narrative draft.

        In mock mode there is no real reviewer, so the draft is returned as-is.
        In real mode the advisor reviews and the writer revises up to
        `paper_revision_rounds` times before the narrative is embedded into the
        grounded paper.
        """
        if settings.mock_mode:
            return writer_draft
        narrative = writer_draft
        rounds = max(1, settings.paper_revision_rounds)
        for index in range(rounds):
            narrative = await self._generate_advisor_final(run, narrative, task_summaries, review_summary, agent_time)
            OutputRepository.insert(
                {
                    "id": f"report_revision_{run['id']}_{index + 1}",
                    "output_type": "final_report_revision",
                    "title": f"报告修订第 {index + 1} 轮",
                    "content": narrative,
                    "run_id": run["id"],
                    "agent_id": writer_agent.get("id") if writer_agent else None,
                    "created_at": datetime.now().isoformat(),
                }
            )
        return narrative

    async def _generate_advisor_final(self, run: dict, writer_draft: str, task_summaries: list[dict], review_summary: str, agent_time: str) -> str:
        goal = self._primary_goal(run)
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请以导师 Agent 的身份，基于写作研究生提交的报告初稿和所有审核通过的任务产出，直接撰写一份完整、可发布的 Markdown 最终研究报告。

当前 Agent 时间：{agent_time}
研究目标：{goal}

写作研究生初稿（供参考，需修正和提升）：
{writer_draft}

任务产出索引：
{json.dumps(task_summaries, ensure_ascii=False, indent=2)}

导师阶段审核汇总（供参考）：
{review_summary}

严格要求：
1. 直接输出完整的 Markdown 研究报告正文，以 # 标题开头。
2. 禁止输出审核对话、裁决意见、评语、"好的"等寒暄语、JSON 或任何非报告内容。
3. 报告必须是独立可读的最终成果，不是对初稿的点评。
4. 修正不一致、遗漏、重复和证据不足之处，剔除与研究主题无关的离题内容。
5. 保留清晰的小标题、结论和可追溯依据。
"""
        llm = create_llm_provider()
        return await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            role="advisor_report",
            run_id=run["id"],
        )

    @staticmethod
    def _extract_title_from_narrative(narrative: str) -> str:
        """Extract the first H1 title from the advisor's final narrative.

        The advisor LLM typically rewrites the raw goal into a proper concise
        report title as the first heading.  We prefer that over the raw prompt.
        """
        if not narrative:
            return ""
        for line in narrative.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped[2:].strip().strip("「」""''\"'")
        return ""

    async def _generate_title(self, run: dict, task_summaries: list[dict]) -> str:
        """Generate a concise report title via LLM when none was found in the narrative."""
        goal = self._primary_goal(run)
        # Quick fallback: use the first meaningful line of the goal.
        fallback = ""
        for line in goal.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                fallback = s[:60]
                break
        if settings.mock_mode:
            return fallback or "研究报告"
        try:
            llm = create_llm_provider()
            raw = await llm.generate(
                prompt=(
                    f"请为以下研究课题生成一个简洁的中文报告标题（不超过30个字，不要句号，不要引号，只输出标题文字）：\n\n"
                    f"{goal[:500]}"
                ),
                role="advisor_report",
                run_id=run["id"],
            )
            title = raw.strip().split("\n")[0].strip().strip("「」""''\"\"#")
            return title if title else fallback
        except Exception:
            return fallback or "研究报告"

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
        normalized = "\n".join(lines[: title_index + 1] + metadata + lines[title_index + 1 :]).strip()
        evidence = self._evidence_section(run)
        if evidence and "可追溯证据" not in normalized:
            normalized = f"{normalized}\n\n{evidence}"
        return normalized + "\n"

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
                        points.append(str(value)[: settings.report_output_point_max_chars])
                for key in ("findings", "deliverables", "recommendations", "next_steps", "key_metrics", "sections", "metrics"):
                    value = output.get(key)
                    if value:
                        points.append(f"{key}: {json.dumps(value, ensure_ascii=False)[: settings.report_output_point_max_chars]}")
            elif output:
                points.append(str(output)[: settings.report_output_point_max_chars])
        return points or ["该任务已完成，但未留下结构化摘要。"]

    def _summarize_outputs(self, outputs: list) -> list[str]:
        return [f"- 产出要点：{point}" for point in self._output_points(outputs)[:5]]

    def _agent_name(self, agents: list[dict], agent_id: str | None) -> str:
        if not agent_id:
            return "未分配"
        agent = next((item for item in agents if item.get("id") == agent_id), None)
        return agent.get("name", agent_id) if agent else agent_id

    def _primary_goal(self, run: dict) -> str:
        return primary_goal(str(run.get("research_goal", "")))
        goal = str(run.get("research_goal", "")).strip()
        return goal.split("## 用户上传的多模态附件上下文", 1)[0].strip()

    def _agent_time_label(self) -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _save_report(self, run_id: str, content: str, review_summary: str, writer_draft: str):
        run_data = RunRepository.get_by_id(run_id) or {}
        run_dir = run_artifact_service.run_dir(run_data, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "final_report.md").write_text(content, encoding="utf-8")
        (run_dir / "review_summary.md").write_text(review_summary, encoding="utf-8")
        (run_dir / "writer_final_draft.md").write_text(writer_draft, encoding="utf-8")
        for name in ("final_report.md", "review_summary.md", "writer_final_draft.md"):
            artifact_manifest_service.register(run_dir, kind="report", path=str(run_dir / name))

        tasks = TaskRepository.get_all(run_id=run_id)
        (run_dir / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_manifest_service.register(run_dir, kind="run_snapshot", path=str(run_dir / "tasks.json"))
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
        artifact_manifest_service.register(run_dir, kind="run_snapshot", path=str(run_dir / "agent_assignments.json"))
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
        artifact_manifest_service.register(run_dir, kind="run_log", path=str(run_dir / "run_log.md"))

    def _evidence_section(self, run: dict) -> str:
        tasks = TaskRepository.get_all(run_id=run["id"])
        research_claims = ResearchClaimRepository.get_by_run(run["id"])
        evidence_bundle = EvidenceRepository.get_by_run(run["id"])
        experiment_results = ExperimentResultRepository.get_by_run(run["id"])
        experiment_findings = ExperimentFindingRepository.get_by_run(run["id"])
        source_map = {item["id"]: item for item in evidence_bundle["sources"]}
        excerpt_map = {item["id"]: item for item in evidence_bundle["excerpts"]}
        lines = ["## 可追溯证据", ""]
        run_dir = run_artifact_service.run_dir(run, run["id"])
        lines.append(f"- 运行产物目录：`{run_dir}`")
        found = False

        if research_claims:
            found = True
            lines.extend(["", "### 结论与证据映射", ""])
            for claim in research_claims:
                related_links = [item for item in evidence_bundle["links"] if item["claim_id"] == claim["id"]]
                supporting = [item for item in related_links if item["relation_type"] == "supports"]
                opposing = [item for item in related_links if item["relation_type"] == "opposes"]
                lines.append(f"- `{claim['status']}` {claim['statement']}")
                if not related_links:
                    claim_findings = [item for item in experiment_findings if item.get("claim_id") == claim["id"]]
                    if not claim_findings:
                        lines.append("  - 证据缺口：当前还没有已绑定证据或实验 finding。")
                        continue
                lines.append(
                    f"  - 支持={len(supporting)}，反驳={len(opposing)}，置信度={round(claim.get('confidence', 0) * 100)}%"
                )
                for link in related_links[: settings.report_evidence_paper_limit]:
                    source = source_map.get(link["source_id"], {})
                    excerpt = excerpt_map.get(link.get("excerpt_id") or "", {})
                    relation_label = {"supports": "支持", "opposes": "反驳", "context": "上下文"}.get(
                        link["relation_type"],
                        link["relation_type"],
                    )
                    citation = " ".join(
                        str(item)
                        for item in [
                            source.get("authors", "").strip(),
                            f"({source.get('year')})" if source.get("year") else "",
                            source.get("title", "").strip(),
                        ]
                        if item
                    ).strip()
                    locator = excerpt.get("locator") or source.get("url") or ""
                    lines.append(f"  - {relation_label}: {citation or link['source_id']} [{locator}]")
                for finding in [item for item in experiment_findings if item.get("claim_id") == claim["id"]]:
                    lines.append(f"  - 实验 finding: {finding['relation_type']} / {finding['statement']}")

        if experiment_results:
            found = True
            lines.extend(["", "### 实验结果", ""])
            for item in experiment_results:
                lines.append(f"- `{item['status']}` {item['summary']}")
                if item.get("metrics"):
                    lines.append(f"  - metrics：`{json.dumps(item['metrics'], ensure_ascii=False)}`")
                lines.append(f"  - exit_code：`{item.get('exit_code')}`")

        for task in tasks:
            for output in task.get("outputs", []) or []:
                if not isinstance(output, dict):
                    continue
                experiment = output.get("reproducible_experiment") or {}
                if experiment:
                    found = True
                    lines.append(f"- 实验任务 `{task.get('title', '')}` workspace：`{experiment.get('workspace_dir')}`")
                    lines.append(f"  - 脚本：`{experiment.get('script_path')}`")
                    data_paths = experiment.get("data_paths") or {}
                    for label, path in data_paths.items():
                        lines.append(f"  - {label}：`{path}`")
                source_artifacts = output.get("source_artifacts") or {}
                papers = output.get("papers_read") or []
                if source_artifacts or papers:
                    found = True
                    lines.append(f"- 文献任务 `{task.get('title', '')}` 来源记录：`{source_artifacts.get('sources_json', '')}`")
                    for paper in papers[: settings.report_evidence_paper_limit]:
                        lines.append(f"  - {paper.get('authors')} ({paper.get('year')}). {paper.get('title')}. {paper.get('url')}")
        return "\n".join(lines) if found else ""


report_service = ReportService()
