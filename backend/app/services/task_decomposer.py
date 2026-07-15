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
            family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
            return "survey" if brief.get("research_type") == "survey" or family == "systematic_review" else "paper"
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
2. task_type 只能是 literature_survey、research_design、data_acquisition、system_design、experiment_design、result_analysis、report_writing。
   - research_design：冻结学科适配的方法、抽样/语料、材料协议、分析计划、质量控制与偏离处理。
   - data_acquisition：只登记真实上传或外部执行返回的材料、来源、授权与哈希，不得由语言模型生成原始数据。
   - system_design 表示通用研究设计：应按 methodology_profile 冻结抽样、语料、测量、解释框架、证明路线或实验方案，不能默认是软件系统设计。
   - experiment_design 仅用于系统能够真实执行并产生 artifact 的计算/定量实验。不得把访谈、田野、湿实验、临床、人文解释或理论证明伪装成自动计算实验。
   - result_analysis 必须采用 methodology_profile.analysis_methods 与 quality_criteria，而不是一律输出数值指标。
3. priority、complexity、decomposability 和 required_skills 中的技能分数均为 1-10。
4. 每个任务必须给出 subquestion_id、hypothesis_id、milestone_key，且只能引用 Contract 中已有对象。
5. 若课题是本系统已支持的 RAG/检索切分受控实验，检索器固定为 Python 标准库实现的
   deterministic_lexical_overlap；不得改成 BM25/rank_bm25、embedding 或其他外部检索器。
6. 只返回合法 JSON 数组，不要输出解释性文字。
7. resource_plan 或 ethics_plan 未放行的步骤不得写成已经可自动执行；应保留为范围外条件或人工资源要求。
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
                            "literature_survey", "research_design", "data_acquisition",
                            "system_design", "experiment_design",
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
            tasks_data = self._respect_methodology_capability(tasks_data, brief)
            # Surveys/investigations should not fabricate experiments; drop experiment tasks.
            filtered = [item for item in tasks_data if item.get("task_type") != "experiment_design"]
            if filtered:
                tasks_data = filtered
        else:
            tasks_data = self._normalize_inverted_experiment_roles(tasks_data)
            tasks_data = self._normalize_supported_retrieval_tasks(tasks_data, research_goal, contract or {})
            tasks_data = self._respect_methodology_capability(tasks_data, brief)
        tasks_data = self._ensure_complete_workflow(tasks_data, brief, mode)
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
                "milestone_id": milestones.get(self._scalar_ref(item.get("milestone_key"))) or milestones.get(
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
    def _normalize_inverted_experiment_roles(tasks: list[dict]) -> list[dict]:
        """Swap only an unmistakably inverted design/execution pair."""
        def text(item: dict) -> str:
            return f"{item.get('title', '')} {item.get('description', '')}".lower()

        execution_markers = ("实验执行", "执行实验", "执行至少", "运行实验", "pipeline", "artifact hash", "结果文件")
        planning_markers = ("设计冻结", "冻结", "评估方案", "实验方案", "协议", "停止条件")
        def executes(item: dict) -> bool:
            value = text(item)
            return (
                any(marker in value for marker in execution_markers)
                and "不执行实验" not in value and "不运行实验" not in value
            )

        inverted_execution = next(
            (
                item for item in tasks
                if item.get("task_type") == "system_design"
                and executes(item)
            ),
            None,
        )
        planning_experiment = next(
            (
                item for item in tasks
                if item.get("task_type") == "experiment_design"
                and any(marker in text(item) for marker in planning_markers)
                and not executes(item)
            ),
            None,
        )
        if inverted_execution and planning_experiment:
            inverted_execution["task_type"] = "experiment_design"
            planning_experiment["task_type"] = "system_design"
        return tasks

    @staticmethod
    def _normalize_supported_retrieval_tasks(
        tasks: list[dict], research_goal: str, contract: dict
    ) -> list[dict]:
        """Keep the supported retrieval pilot aligned with its executable protocol."""
        goal = primary_goal(str(research_goal or "")).lower()
        markers = ("rag", "检索", "retrieval", "切分", "chunk", "mrr")
        if not any(marker in goal for marker in markers):
            return tasks

        hypotheses = {
            item.get("id"): item.get("statement")
            for item in contract.get("hypotheses") or []
            if item.get("id") and item.get("statement")
        }
        common = (
            "检索器固定为 Python 标准库实现的 deterministic_lexical_overlap："
            "lowercase_unicode_word_regex 分词、cosine-like lexical overlap 评分、"
            "maximum chunk aggregation；不得改为 BM25/rank_bm25、embedding 或其他外部检索器。"
            "三种切分策略为 no_split、fixed_100_no_overlap、fixed_100_overlap_30，"
            "指标为 Top-1/3/5 accuracy 与 MRR@10。核心实验不得新增第三方依赖。"
        )
        for item in tasks:
            task_type = item.get("task_type")
            if task_type not in {"system_design", "experiment_design"}:
                continue
            linked_hypothesis = hypotheses.get(
                TaskDecomposer._scalar_ref(item.get("hypothesis_id"))
            )
            hypothesis_text = (
                f"冻结并检验契约假设“{linked_hypothesis}”。" if linked_hypothesis
                else "冻结并检验 hypothesis_id 对应的契约假设及最小效应阈值。"
            )
            if task_type == "system_design":
                item["description"] = (
                    f"依据冻结 Research Contract 设计并冻结受控检索实验。{hypothesis_text}{common}"
                    "给出数据快照与哈希、函数接口、关键伪代码、三个固定复现标签、"
                    "查询级配对 bootstrap、精确数值复现容差、目录和停止条件；"
                    "本任务只交付可执行设计，不声称已经运行实验或生成结果。"
                )
            else:
                item["description"] = (
                    f"依据已冻结协议实际创建隔离工作区并执行受控检索实验。{hypothesis_text}{common}"
                    "对完整冻结 query/qrel 运行三个固定复现标签，输出逐查询原始结果、"
                    "配对 bootstrap 统计、环境清单、文件哈希，并在干净目录按数值容差复现；"
                    "不得用文字声称代替真实 artifact。"
                )
        return tasks

    @staticmethod
    def _respect_methodology_capability(tasks: list[dict], brief: dict) -> list[dict]:
        """Translate computer-centric task labels into method-neutral work packages."""
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
        executable_families = {"computational", "quantitative", "design_science"}
        if family in executable_families:
            return tasks
        profile = brief.get("methodology_profile") or {}
        for item in tasks:
            if item.get("task_type") == "system_design":
                item["task_type"] = "research_design"
                item["title"] = "冻结跨学科研究设计"
                item["description"] = (
                    f"按 {family} / {profile.get('epistemic_mode', '')} 方法冻结研究设计、抽样或语料、"
                    "材料协议、分析计划、至少两项质量控制、停止规则和偏离处理；不得声称已取得材料。"
                )
            elif item.get("task_type") == "experiment_design":
                item["task_type"] = "data_acquisition"
                item["title"] = "获取并冻结真实研究材料"
                item["description"] = (
                    "仅接收用户上传或经审计外部执行返回的真实材料，生成逐文件来源、授权、SHA-256、"
                    "收集日志与完整性清单；缺失材料时必须失败，不得由 LLM 补造。"
                )
        return tasks

    @staticmethod
    def _ensure_complete_workflow(tasks: list[dict], brief: dict, mode: str) -> list[dict]:
        """Add only missing research roles so stochastic decomposition cannot omit the thesis."""
        present = {item.get("task_type") for item in tasks}
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
        template = tasks[0] if tasks else {}

        def add(task_type: str, title: str, description: str, skills: dict) -> None:
            if task_type in present:
                return
            tasks.append({
                "title": title,
                "description": description,
                "task_type": task_type,
                "priority": 8,
                "complexity": 6,
                "decomposability": 4,
                "required_skills": skills,
                "subquestion_id": template.get("subquestion_id"),
                "hypothesis_id": template.get("hypothesis_id"),
                "milestone_key": TaskDecomposer._default_milestone(task_type),
            })
            present.add(task_type)

        add(
            "literature_survey", "核验并综合相关文献",
            "检索、筛选并阅读全文证据，形成逐来源可追溯的综合；不得引用未核验或未取得正文的文献。",
            {"literature_review": 9, "academic_writing": 6},
        )
        if not present.intersection({"research_design", "system_design"}):
            add(
                "research_design", "冻结研究方法与分析计划",
                "依据 Research Contract 冻结研究设计、材料、分析方法、质量控制、停止规则和偏离处理。",
                {"experiment": 7, "data_analysis": 7, "academic_writing": 5},
            )
        needs_material_task = mode != "survey" or family == "systematic_review"
        if needs_material_task and not present.intersection({"data_acquisition", "experiment_design"}):
            task_type = "experiment_design" if family == "computational" else "data_acquisition"
            add(
                task_type,
                "执行冻结实验并生成可复现产物" if task_type == "experiment_design" else "获取并冻结真实研究材料",
                (
                    "严格执行冻结协议，保存原始结果、环境、统计分析、哈希和独立复现记录。"
                    if task_type == "experiment_design" else
                    "仅登记真实上传或外部返回的研究材料、来源、授权与哈希；缺失材料时停止。"
                ),
                {"experiment": 9, "coding": 8, "data_analysis": 7} if task_type == "experiment_design"
                else {"experiment": 7, "data_analysis": 6},
            )
        add(
            "result_analysis", "分析结果并回答研究问题",
            "只依据已核验文献与真实研究产物完成契约指定分析，报告不确定性、反证与有效性边界。",
            {"data_analysis": 9, "academic_writing": 7},
        )
        add(
            "report_writing", "撰写并校验完整学位论文",
            "按已确认的院校规范整合完整论文；每项实质主张须链接证据或真实产物，并通过引用、字数和章节门禁。",
            {"academic_writing": 10, "literature_review": 8, "data_analysis": 7},
        )
        return tasks

    @staticmethod
    def _known_or_default(value, allowed: set[str]) -> str | None:
        value = TaskDecomposer._scalar_ref(value)
        if value in allowed:
            return str(value)
        return sorted(allowed)[0] if allowed else None

    @staticmethod
    def _scalar_ref(value) -> str | None:
        """Tolerate providers returning a one-item array for scalar contract refs."""
        while isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return str(value) if isinstance(value, (str, int)) else None

    @staticmethod
    def _default_milestone(task_type: str) -> str:
        return {
            "literature_survey": "evidence_sufficient",
            "research_design": "methodology_frozen",
            "data_acquisition": "resources_ready",
            "system_design": "framing_frozen",
            "experiment_design": "experiment_protocol_frozen",
            "result_analysis": "replication_passed",
            "report_writing": "report_verified",
        }.get(task_type, "framing_frozen")


task_decomposer = TaskDecomposer()
