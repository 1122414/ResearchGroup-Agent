import json
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..core.research_goal import primary_goal
from ..models.task import TaskStatus
from ..storage.repositories import ResearchHypothesisRepository, ResearchMilestoneRepository, TaskRepository
from .run_event_service import run_event_service

SURVEY_MARKERS = ("综述", "调研", "survey", "review", "github", "现状", "对比", "landscape", "梳理")


class TaskDecomposer:
    def detect_mode(self, research_goal: str, brief: dict | None = None) -> str:
        if brief:
            return "survey" if brief.get("research_type") == "survey" else "paper"
        goal = primary_goal(str(research_goal or "")).lower()
        return "survey" if any(marker in goal for marker in SURVEY_MARKERS) else "paper"

    async def decompose(self, research_goal: str, run_id: str, contract: dict | None = None) -> list[dict]:
        logger.info("[TaskDecomposer] decompose started | run_id=%s | goal=%s", run_id, research_goal[:80])
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请把下面的研究目标拆解为 3-7 个可执行任务。

研究目标：
{research_goal}

已冻结 Research Contract：
{json.dumps(contract or {}, ensure_ascii=False, indent=2)}

要求：
1. 每个任务必须包含 title、description、task_type、priority、complexity、decomposability、required_skills。
2. task_type 只能是 literature_survey、system_design、experiment_design、result_analysis、report_writing。
3. priority、complexity、decomposability 和 required_skills 中的技能分数均为 1-10。
4. 每个任务必须给出 subquestion_id、hypothesis_id、milestone_key，且只能引用 Contract 中已有对象。
5. 只返回合法 JSON 数组，不要输出解释性文字。
"""

        llm = create_llm_provider()
        logger.info("[TaskDecomposer] calling LLM | run_id=%s | role=advisor_decompose", run_id)
        task_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "task_type": {
                        "type": "string",
                        "enum": [
                            "literature_survey", "system_design", "experiment_design",
                            "result_analysis", "report_writing",
                        ],
                    },
                    "priority": {"type": "integer", "minimum": 1, "maximum": 10},
                    "complexity": {"type": "integer", "minimum": 1, "maximum": 10},
                    "decomposability": {"type": "integer", "minimum": 1, "maximum": 10},
                    "required_skills": {"type": "object"},
                    "subquestion_id": {"type": "string"},
                    "hypothesis_id": {"type": "string"},
                    "milestone_key": {"type": "string"},
                },
                "required": [
                    "title", "description", "task_type", "priority", "complexity", "decomposability",
                    "required_skills", "subquestion_id", "hypothesis_id", "milestone_key",
                ],
            },
        }
        raw_response = await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            schema=task_schema,
            role="advisor_decompose",
            run_id=run_id,
        )

        tasks_data = self._parse_response(raw_response)
        if not tasks_data and settings.llm_structured_repair_attempts > 0:
            raw_response = await llm.generate(
                prompt=(
                    f"{system_prompt}\n\n---\n\n{user_prompt}\n\n"
                    "上次任务数组结构非法或为空。只修复 JSON 结构，不新增研究目标之外的内容：\n"
                    f"{raw_response[:4000]}"
                ),
                schema=task_schema,
                role="advisor_decompose",
                run_id=run_id,
            )
            tasks_data = self._parse_response(raw_response)
        if not tasks_data:
            raise ValueError("任务拆解未返回合法非空数组，已停止而非继续空转")
        brief = (contract or {}).get("brief") or {}
        hypotheses = (contract or {}).get("hypotheses") or []
        mode = self.detect_mode(research_goal, brief or None)
        if mode == "survey":
            # Surveys/investigations should not fabricate experiments; drop experiment tasks.
            filtered = [item for item in tasks_data if item.get("task_type") != "experiment_design"]
            if filtered:
                tasks_data = filtered
        if not contract:
            self._seed_hypotheses(research_goal, run_id, mode)
        logger.info("[TaskDecomposer] LLM response parsed | run_id=%s | mode=%s | tasks=%d", run_id, mode, len(tasks_data))
        run_event_service.emit(
            run_id,
            "decompose.mode_detected",
            "decompose",
            "已判定研究模式",
            f"模式：{'论文' if mode == 'paper' else '调研报告'}",
            payload={"mode": mode},
        )
        now = datetime.now().isoformat()
        tasks = []
        subquestion_ids = {item.get("id") for item in brief.get("subquestions") or [] if item.get("id")}
        hypothesis_ids = {item.get("id") for item in hypotheses if item.get("id")}
        milestones = {item["milestone_key"]: item["id"] for item in ResearchMilestoneRepository.get_by_run(run_id)}

        for item in tasks_data:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = {
                "id": task_id,
                "title": item.get("title", "未命名任务"),
                "description": item.get("description", ""),
                "task_type": item.get("task_type", "literature_survey"),
                "required_skills": self._normalize_skills(item.get("required_skills", {})),
                "priority": self._bounded_int(item.get("priority", 5)),
                "complexity": self._bounded_int(item.get("complexity", 5)),
                "decomposability": self._bounded_int(item.get("decomposability", 5)),
                "status": TaskStatus.pending.value,
                "owner_agent": None,
                "collaborator_agents": [],
                "subtasks": [],
                "outputs": [],
                "review_result": None,
                "review_feedback": None,
                "run_id": run_id,
                "blocked_reason": None,
                "parallelizable": item.get("task_type") not in {"report_writing"},
                "is_critical_path": False,
                "attempt_count": 0,
                "last_checkpoint": None,
                "subquestion_id": self._known_or_default(item.get("subquestion_id"), subquestion_ids),
                "hypothesis_id": self._known_or_default(item.get("hypothesis_id"), hypothesis_ids),
                "milestone_id": milestones.get(item.get("milestone_key")) or milestones.get(
                    self._default_milestone(item.get("task_type", "literature_survey"))
                ),
                "created_at": now,
                "updated_at": now,
            }
            TaskRepository.insert(task)
            tasks.append(task)
            logger.info("[TaskDecomposer] task inserted | run_id=%s | task_id=%s | title=%s", run_id, task_id, task["title"])

        logger.info("[TaskDecomposer] decompose completed | run_id=%s | total_tasks=%d | task_ids=%s",
                    run_id, len(tasks), [t["id"] for t in tasks])
        return tasks

    def _seed_hypotheses(self, research_goal: str, run_id: str, mode: str) -> None:
        """Persist goal-specific, testable hypotheses so the run is hypothesis-driven.

        This fallback is used only by legacy/direct decomposition calls that do
        not provide a frozen Research Contract.
        """
        goal = primary_goal(str(research_goal or "")).strip()
        if not goal:
            return
        now = datetime.now().isoformat()
        if mode == "paper":
            statement = f"针对“{goal}”，所提出的方法在关键评测指标上优于基线方法。"
            rationale = "以可检验的方式约束研究流程，由实验结果支持或反驳。"
        else:
            statement = f"针对“{goal}”，现有方法在覆盖面与有效性上存在可识别的权衡与空白。"
            rationale = "以可检验的方式约束综述，由证据来源支持或反驳。"
        ResearchHypothesisRepository.insert(
            {
                "id": f"hypothesis_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "statement": statement,
                "rationale": rationale,
                "status": "proposed",
                "confidence": 0.0,
                "treatment": "待研究方案",
                "baseline": "最小合理基线",
                "conditions": ["相同评价条件"],
                "predicted_direction": "优于基线" if mode == "paper" else "存在可验证差异",
                "primary_metric": "待研究契约冻结的主指标",
                "minimum_effect": "达到领域最小重要差异",
                "falsification_criterion": "证据或实验未显示预期差异",
                "originating_evidence_ids": [],
                "competing_hypothesis_ids": [],
                "created_at": now,
                "updated_at": now,
            }
        )

    def _parse_response(self, raw: str) -> list[dict]:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    def _bounded_int(self, value: int, default: int = 5) -> int:
        try:
            return max(1, min(10, int(value)))
        except (TypeError, ValueError):
            return default

    def _normalize_skills(self, skills: dict) -> dict:
        keys = ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]
        return {key: self._bounded_int(skills.get(key, 1), default=1) for key in keys}

    @staticmethod
    def _known_or_default(value, allowed: set[str]) -> str | None:
        if value in allowed:
            return str(value)
        return sorted(allowed)[0] if allowed else None

    @staticmethod
    def _default_milestone(task_type: str) -> str:
        return {
            "literature_survey": "evidence_sufficient",
            "system_design": "framing_frozen",
            "experiment_design": "experiment_protocol_frozen",
            "result_analysis": "replication_passed",
            "report_writing": "report_verified",
        }.get(task_type, "framing_frozen")


task_decomposer = TaskDecomposer()
