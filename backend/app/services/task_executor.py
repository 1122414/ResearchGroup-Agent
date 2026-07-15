import json
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import (
    AgentRepository,
    OutputRepository,
    ResearchBriefRepository,
    ResearchHypothesisRepository,
    ResearchMilestoneRepository,
    SubAgentRepository,
    TaskRepository,
)
from .agent_skill_service import agent_skill_service
from .claim_entailment_service import claim_entailment_service
from .collaborator_service import collaborator_service
from .external_memory import external_memory
from .evidence_pipeline_service import evidence_pipeline_service
from .experiment_protocol_service import experiment_protocol_service
from .knowledge_graph_service import knowledge_graph_service
from .literature_source_service import literature_source_service
from .research_integrity_service import research_integrity_service
from .research_analysis_service import research_analysis_service
from .method_material_analysis_service import method_material_analysis_service
from .research_material_service import research_material_service
from .research_method_registry_service import research_method_registry_service
from .thesis_chapter_service import thesis_chapter_service
from .reproducible_experiment_service import reproducible_experiment_service
from .run_event_service import run_event_service


class TaskExecutor:
    RESULT_SCHEMA = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "evidence_source_ids": {"type": "array", "items": {"type": "string"}},
                        "evidence_passage_ids": {"type": "array", "items": {"type": "string"}},
                        "relation": {"type": "string", "enum": ["supports", "opposes", "context"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["statement", "evidence_source_ids", "evidence_passage_ids", "relation", "confidence"],
                },
            },
        },
        "required": ["summary", "claims"],
    }

    async def execute(self, task: dict) -> dict:
        task_title = task.get("title", "")
        task_type = task.get("task_type", "literature_survey")
        owner_id = task.get("owner_agent", "")
        owner = AgentRepository.get_by_id(owner_id) if owner_id else None
        agent_type = owner.get("type", "researcher") if owner else "researcher"
        logger.info("[TaskExecutor] execute started | task_id=%s | type=%s | agent=%s", task.get("id"), task_type, agent_type)
        evidence_bundle = await evidence_pipeline_service.collect_for_task(task) if task_type == "literature_survey" else None

        prompt_map = {
            "researcher": "grad_researcher",
            "engineer": "grad_engineer",
            "experimenter": "grad_experimenter",
            "analyst": "grad_analyst",
            "writer": "grad_writer",
        }
        system_prompt = prompt_loader.load(prompt_map.get(agent_type, "grad_researcher"))
        active_skills = agent_skill_service.active_for_task(owner_id, task)
        skill_prompt = agent_skill_service.render_for_prompt(active_skills)
        contract_context = self._research_contract_context(task)
        brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
        method_requirement = research_method_registry_service.requirements_for(brief).get(task_type, {})
        method_work_package = (
            "【方法专用工作包（字段缺失将被硬门拒绝）】\n"
            + json.dumps(method_requirement, ensure_ascii=False, indent=2)
            if method_requirement else ""
        )
        thesis_chapter_context = thesis_chapter_service.context_for_task(task) if task_type == "thesis_chapter" else ""
        upstream_context = self._upstream_context(task)
        experiment_protocol = (
            experiment_protocol_service.ensure_for_task(task)
            if task_type == "system_design" and task.get("hypothesis_id")
            else None
        )
        protocol_context = self._experiment_protocol_context(experiment_protocol)
        literature_grounding = ""
        if evidence_bundle is not None:
            required_source_count = research_integrity_service.required_grounded_source_count(task, evidence_bundle["query"])
            prompt_sources = evidence_bundle["sources"][: max(int(settings.literature_source_limit), 1)]
            prompt_source_ids = {item["id"] for item in prompt_sources}
            prompt_excerpts = [
                item for item in evidence_bundle["excerpts"] if item.get("source_id") in prompt_source_ids
            ]
            literature_grounding = f"""

【学术诚信与证据边界】
1. 你只能基于下方 allowed_sources 归纳，不得补写、猜测或伪造任何论文、作者、年份、DOI、URL。
2. 若来源不足以回答任务，请明确输出“证据不足”，不要为了完整性编造结论。
3. 只允许通过 source_id 引用，格式为 [source_id]；不要自行生成参考文献列表。
4. 每条结论必须同时给出 source_id 与对应 passage_id；没有 passage 的来源只能用于检索线索，不能支撑结论。
5. 输出 JSON 中必须包含 references_used，且每一项都只能来自 allowed_sources.source_id。
6. 当前检索 query：{evidence_bundle["query"]}
7. allowed_sources（含可引用 passages）：
当前任务所需最少可核验来源数：{required_source_count}
{research_integrity_service.render_allowed_sources(prompt_sources, prompt_excerpts)}

【文献综合要求】
1. 优先提取 3–5 条来源实际报告的原子化方法、结果或局限，每条只表达一个可由 passage 直接蕴含的事实。
2. 单篇来源结论必须明确归因于该研究；若五篇来源各有相关事实，应分别形成 claim，不要压成一个宽泛总结。
3. “这些来源没有讨论/没有比较某主题”属于检索缺口，只能写入 uncertainties 或 search_gaps，relation=context 的说明不得放入 claims。
4. 没有直接做相同实验不等于没有可用背景证据；可提取与构念、指标、基线、方法选择或有效性边界相关的实际报告，但不得暗示其验证了本课题结果。
"""
        collaborator_results = await collaborator_service.execute_all(task, literature_grounding)
        collaboration_context = self._collaboration_context(task, collaborator_results)
        user_prompt = f"""请以 {agent_type} 研究生 Agent 的身份完成下面任务，并返回合法 JSON。

任务标题：{task_title}
任务类型：{task_type}
任务描述：{task.get("description", "")}

{skill_prompt}
{collaboration_context}
{contract_context}
{method_work_package}
{thesis_chapter_context}
{upstream_context}
{protocol_context}
{literature_grounding}

输出要求：
1. 给出 summary。
2. 给出 findings 或 deliverables。
3. 给出 risks 或 next_steps。
4. 给出 claims：数组，每个元素 {{"statement": 可单独核验的研究性结论, "evidence_source_ids": [来源ID], "evidence_passage_ids": [该来源下的原文片段ID], "relation": "supports"|"opposes"|"context", "confidence": 0到1}}。没有可定位片段时不要输出该 claim。
   单一来源的实验结果必须写成“该研究/该论文在其设置下报告或观察到……”，不得改写成无归因的“导致、证明、证实”式普遍结论；只有至少两个独立来源共同支持时才可使用跨来源强结论。
5. 给出 hypotheses（可选）：数组，每个元素 {{"statement": 可检验的假设, "rationale": 依据}}。
6. 给出 uncertainties（可选）：数组，每个元素 {{"description": 仍未解决的问题, "severity": "low"|"medium"|"high"}}。
7. 不要输出 Markdown，只返回 JSON。
8. 若存在“方法专用工作包”，必须按 required_object 输出对应对象和全部字段；不得用 summary 代替。
9. 若存在“论文章节写作契约”，必须输出 chapter 对象；不得自行添加 allowed_support 之外的事实或引用。
"""

        llm = create_llm_provider()
        prompt_len = len(system_prompt) + len(user_prompt)
        logger.info("[TaskExecutor] calling LLM | task_id=%s | role=graduate | prompt_len=%d | active_skills=%d", task.get("id"), prompt_len, len(active_skills))
        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        try:
            result = await self._generate_structured(llm, prompt, task, owner_id)
        except Exception:
            agent_skill_service.record_usage(active_skills, success=False)
            raise
        result = self._preserve_revision_work_packages(task, result)
        if task_type == "literature_survey" and evidence_bundle is not None:
            result = research_integrity_service.apply_literature_policy(
                result,
                evidence_bundle["sources"],
                evidence_bundle["query"],
                evidence_bundle["mode"],
                task,
                evidence_bundle["excerpts"],
            )
            if not result.get("insufficient_evidence") and not result.get("integrity_blocked"):
                result = await claim_entailment_service.verify(
                    result, evidence_bundle["excerpts"], task.get("run_id"), task.get("id")
                )
            methods = literature_source_service.methods_from_sources(evidence_bundle["sources"])
            artifacts = literature_source_service.write_artifacts(task, evidence_bundle["sources"], methods)
            result = {
                **result,
                "source_mode": evidence_bundle["mode"],
                "search_protocol_id": evidence_bundle.get("search_protocol_id"),
                "search_metrics": evidence_bundle.get("search_metrics", {}),
                "papers_read": evidence_bundle["sources"],
                "methods_found": methods,
                "evidence_excerpts": evidence_bundle["excerpts"],
                "evidence_assessments": evidence_bundle["assessments"],
                "source_artifacts": artifacts,
            }
            if str(task_title).startswith("[循环R"):
                # A verification action may add evidence, but must not silently
                # expand the frozen project with new hypotheses.
                result["hypotheses"] = []
        if task_type in {"result_analysis", "report_writing"}:
            experiment = self._approved_task_results(
                task.get("run_id"), {"experiment_design"}, task.get("id")
            ).get("experiment_design", {})
            executed = experiment.get("reproducible_experiment") or {}
            result["reproducible_experiment"] = executed
            if task_type == "result_analysis":
                result["claims"] = executed.get("claims") or experiment.get("claims") or []
                method_inputs = self._approved_task_results(
                    task.get("run_id"), {"data_acquisition"}, task.get("id")
                ).get("data_acquisition", {})
                material_manifest = method_inputs.get("material_manifest") or {}
                if material_manifest:
                    generated_package = await method_material_analysis_service.build_for_task(
                        task, material_manifest,
                    )
                    analysis_artifact = research_analysis_service.analyze_for_task(
                        task, material_manifest, generated_package,
                    )
                    result["analysis_artifact"] = analysis_artifact
                    result["claims"] = research_analysis_service.claims_for_artifact(analysis_artifact)
        if task_type == "data_acquisition":
            material_manifest = research_material_service.ingest_for_task(task)
            result = self._ground_material_output(result, material_manifest)
            if material_manifest.get("completeness") != "complete":
                result.setdefault("uncertainties", []).append({
                    "description": "真实研究材料清单不完整：" + "、".join(
                        material_manifest.get("missing_conditions") or []
                    ),
                    "severity": "high",
                })
        if task_type == "experiment_design":
            experiment_result = await reproducible_experiment_service.run_for_task(task, owner_id)
            result = self._ground_experiment_output(experiment_result)
        if experiment_protocol is not None:
            result = {**result, "experiment_protocol": experiment_protocol}
        if active_skills:
            result["used_skills"] = [
                {
                    "id": skill["id"],
                    "title": skill["title"],
                    "usage_count_before": skill.get("usage_count", 0),
                    "last_used_at_before": skill.get("last_used_at"),
                }
                for skill in active_skills
            ]
            agent_skill_service.record_usage(active_skills, success=True)
        graph = knowledge_graph_service.ingest_task_result(task, result)
        # evidence_links is a count (int), not a collection — see knowledge_graph_service.
        evidence_link_count = graph.get("evidence_links") or 0
        if not isinstance(evidence_link_count, int):
            evidence_link_count = len(evidence_link_count)
        if graph["claims"] or graph["hypotheses"] or graph["uncertainties"]:
            result = {
                **result,
                "knowledge_graph": {
                    "claim_ids": [item["id"] for item in graph["claims"] if item],
                    "hypothesis_ids": [item["id"] for item in graph["hypotheses"]],
                    "uncertainty_ids": [item["id"] for item in graph["uncertainties"]],
                    "evidence_links": evidence_link_count,
                },
            }
            run_event_service.emit(
                task.get("run_id"),
                "knowledge_graph.updated",
                "execute",
                "知识图谱已更新",
                f"新增结论 {len(graph['claims'])} 条、假设 {len(graph['hypotheses'])} 条、证据关联 {evidence_link_count} 条",
                task_id=task.get("id"),
                agent_id=owner_id,
                payload={
                    "claims": len(graph["claims"]),
                    "hypotheses": len(graph["hypotheses"]),
                    "evidence_links": evidence_link_count,
                },
            )
        logger.info("[TaskExecutor] LLM response parsed | task_id=%s | has_summary=%s", task.get("id"), "summary" in result)
        TaskRepository.update_status(task["id"], "running", outputs=task.get("outputs", []) + [result])
        self._write_memory(task, owner_id, result)

        OutputRepository.insert(
            {
                "id": f"out_{task['id']}",
                "output_type": "task_result",
                "title": f"任务产出：{task_title}",
                "content": json.dumps(result, ensure_ascii=False, indent=2),
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "agent_id": owner_id,
                "created_at": datetime.now().isoformat(),
            }
        )
        logger.info("[TaskExecutor] execute completed | task_id=%s | output_saved=%s", task.get("id"), f"out_{task['id']}")
        return result

    @staticmethod
    def _ground_material_output(result: dict, material_manifest: dict) -> dict:
        """Replace LLM file claims with the deterministic material registry."""
        records = material_manifest.get("source_records") or []
        findings = [
            f"已冻结 {record.get('name') or record.get('id')}："
            f"sha256={record.get('sha256')}，size_bytes={record.get('size_bytes')}，"
            f"provenance={record.get('provenance')}"
            for record in records
        ]
        return {
            **result,
            "summary": (
                f"已登记并冻结 {len(records)} 个真实原始材料文件；清单只陈述磁盘上存在且已校验哈希的材料。"
            ),
            "findings": findings,
            "risks": [
                "本清单不包含尚未由可执行任务生成的派生数据；派生文件必须在生成任务中另行登记哈希。"
            ],
            "next_steps": ["由获批的实验或分析任务读取冻结材料并生成可追溯派生工件。"],
            "claims": [],
            "hypotheses": [],
            "material_manifest": material_manifest,
        }

    @staticmethod
    def _preserve_revision_work_packages(task: dict, result: dict) -> dict:
        """Fill fields a revision accidentally dropped without overriding its edits."""
        root_id = task.get("revision_of_task_id")
        if not root_id:
            return result
        current_created = str(task.get("created_at") or "")
        family = [
            item for item in TaskRepository.get_all(run_id=task.get("run_id"))
            if (item.get("id") == root_id or item.get("revision_of_task_id") == root_id)
            and item.get("id") != task.get("id")
            and str(item.get("created_at") or "") < current_created
            and item.get("outputs")
        ]
        if not family:
            return result
        previous = max(family, key=lambda item: str(item.get("created_at") or ""))["outputs"][-1]

        def fill_missing(old, new):
            if isinstance(old, dict) and isinstance(new, dict):
                merged = dict(new)
                for key, value in old.items():
                    merged[key] = fill_missing(value, merged.get(key))
                return merged
            return old if new in (None, "", [], {}) else new

        merged = dict(result)
        for key in ("method_package", "material_manifest", "analysis_artifact", "chapter"):
            if isinstance(previous, dict) and previous.get(key):
                merged[key] = fill_missing(previous[key], merged.get(key))
        return merged

    def _collaboration_context(self, task: dict, collaborator_results: list[dict] | None = None) -> str:
        """Surface SubAgent/collaborator results so the owner integrates them.

        Previously a SubAgent ran and its result was stored, but the owner's LLM
        call never consumed it, so collaboration was cosmetic. Here we inject any
        SubAgent results and collaborator roster into the owner prompt and require
        their integration before the task output is reviewed.
        """
        subagent_results = [
            sub["result"]
            for sub in SubAgentRepository.get_by_task(task["id"])
            if isinstance(sub.get("result"), (dict, list)) and sub.get("result")
        ]
        collaborators = task.get("collaborator_agents", []) or []
        if not subagent_results and not collaborators and not collaborator_results:
            return ""
        parts = ["【协作中间结果（用于风险检查，不得覆盖父任务与冻结契约）】"]
        if collaborators:
            parts.append(f"协作 Agent：{', '.join(str(item) for item in collaborators)}")
        if collaborator_results:
            parts.append("独立协作者的结构化产出（负责人必须检查冲突后再整合）：")
            parts.append(json.dumps(collaborator_results, ensure_ascii=False, indent=2)[:8000])
        if subagent_results:
            parts.append("SubAgent 返回的中间结果：")
            parts.append(json.dumps(subagent_results, ensure_ascii=False, indent=2)[:4000])
        parts.append(
            "请检查并回应其中合理风险，但必须完成父任务要求的最终交付物；"
            "不得把协作者的‘缺少/建议补充’原样当作自己的交付结果。"
        )
        return "\n".join(parts)

    @staticmethod
    def _experiment_protocol_context(protocol: dict | None) -> str:
        if not protocol:
            return ""
        return (
            "【系统已冻结的实验协议（权威输入，不得另行编造检索器、指标、参数或种子）】\n"
            + json.dumps(protocol, ensure_ascii=False, indent=2)
            + "\n若任务描述出现 BM25/rank_bm25、embedding 等冲突内容，视为拆解漂移并忽略；"
            "请把本协议整理为完整、可执行、可复现的设计交付物，并明确公式、接口、伪代码、"
            "目录、哈希、精确数值容差和停止条件。"
        )

    @staticmethod
    def _research_contract_context(task: dict) -> str:
        run_id = task.get("run_id")
        if not run_id:
            return ""
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        subquestion = next(
            (item for item in brief.get("subquestions") or [] if item.get("id") == task.get("subquestion_id")),
            None,
        )
        hypothesis = ResearchHypothesisRepository.get_by_id(task.get("hypothesis_id")) if task.get("hypothesis_id") else None
        milestone = next(
            (item for item in ResearchMilestoneRepository.get_by_run(run_id) if item["id"] == task.get("milestone_id")),
            None,
        )
        research_frame = {
            "research_type": brief.get("research_type"),
            "discipline": brief.get("discipline"),
            "methodology_profile": brief.get("methodology_profile"),
            "resource_plan": brief.get("resource_plan"),
            "ethics_plan": brief.get("ethics_plan"),
            "thesis_requirements": brief.get("thesis_requirements"),
            "feasibility_assessment": brief.get("feasibility_assessment"),
        }
        if not any((subquestion, hypothesis, milestone, research_frame.get("methodology_profile"))):
            return ""
        return "【已冻结研究契约（不得擅自改变）】\n" + json.dumps(
            {
                "research_frame": research_frame, "subquestion": subquestion,
                "hypothesis": hypothesis, "milestone": milestone,
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _upstream_context(task: dict) -> str:
        """Pass approved predecessor facts across research stages without raw-context bloat."""
        run_id = task.get("run_id")
        task_type = task.get("task_type")
        wanted = {
            "result_analysis": {"research_design", "data_acquisition", "experiment_design"},
            "report_writing": {
                "literature_survey", "research_design", "data_acquisition",
                "system_design", "experiment_design", "result_analysis", "thesis_chapter",
            },
        }.get(task_type)
        if not run_id or not wanted:
            return ""
        selected = {
            predecessor_type: TaskExecutor._compact_upstream(value, predecessor_type)
            for predecessor_type, value in TaskExecutor._approved_task_results(
                run_id, wanted, task.get("id")
            ).items()
        }
        if not selected:
            return ""
        instruction = (
            "必须按冻结的方法画像分析下列已审核材料或实验，不得把质性、人文、理论或综述材料伪装成数值实验；"
            "有已审核实验数值时不得声称缺少实验数据。"
            if task_type == "result_analysis"
            else "必须综合下列已审核产出撰写论文，不得重新猜测数值、来源或适用范围。"
        )
        return (
            "【已审核上游产出（权威只读输入）】\n"
            + instruction
            + "\n"
            + json.dumps(selected, ensure_ascii=False, indent=2)[:16000]
        )

    @staticmethod
    def _approved_task_results(run_id: str | None, wanted: set[str], exclude_id: str | None = None) -> dict[str, dict]:
        if not run_id:
            return {}
        tasks = {item["id"]: item for item in TaskRepository.get_all(run_id)}
        selected: dict[str, dict] = {}
        for output in reversed(OutputRepository.get_by_run(run_id)):
            if output.get("output_type") != "task_result":
                continue
            predecessor = tasks.get(output.get("task_id"))
            predecessor_type = (predecessor or {}).get("task_type")
            if (
                not predecessor
                or predecessor_type not in wanted
                or predecessor_type in selected
                or predecessor.get("status") != "completed"
                or predecessor.get("id") == exclude_id
            ):
                continue
            try:
                selected[predecessor_type] = json.loads(output.get("content") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
        return selected

    @staticmethod
    def _compact_upstream(value: dict, predecessor_type: str) -> dict:
        if predecessor_type == "experiment_design":
            experiment = value.get("reproducible_experiment") or {}
            metrics = experiment.get("metrics") or {}
            return {
                "summary": experiment.get("summary"),
                "claims": experiment.get("claims") or value.get("claims"),
                "protocol": {
                    key: (experiment.get("protocol") or {}).get(key)
                    for key in ("id", "research_question", "metrics", "baselines", "stopping_conditions", "expected_risks")
                },
                "metrics": {
                    key: metrics.get(key)
                    for key in (
                        "benchmark_design", "query_sample_size", "evaluated_query_count", "rows",
                        "best_strategy", "paired_query_metric_deltas", "statistical_analysis",
                        "randomness_audit", "preregistration_trace",
                    )
                },
                "reproduction": experiment.get("reproduction"),
                "publishable": experiment.get("publishable"),
            }
        return {
            key: value.get(key)
            for key in (
                "summary", "findings", "deliverables", "claims", "risks", "next_steps",
                "uncertainties", "references_used", "academic_integrity", "experiment_protocol",
                "method_package", "material_manifest", "analysis_artifact",
                "chapter",
            )
            if value.get(key) is not None
        }

    @staticmethod
    def _ground_experiment_output(experiment: dict) -> dict:
        """Build experiment prose only from executed artifacts, never the model draft."""
        protocol = experiment.get("protocol") or {}
        metrics = experiment.get("metrics") or {}
        stats = metrics.get("statistical_analysis") or {}
        rows = metrics.get("rows") or []
        values = {
            row.get("strategy"): row.get("mrr_at_10")
            for row in rows
            if isinstance(row, dict)
        }
        summary = (
            f"已实际执行冻结协议 {protocol.get('id', '')}："
            f"no_split 的 MRR@10={values.get('no_split')}，"
            f"fixed_100_overlap_30 的 MRR@10={values.get('fixed_100_overlap_30')}；"
            f"查询级配对均值差={stats.get('mean_delta')}，95% bootstrap 区间="
            f"{stats.get('confidence_interval_95')}。主实验完成={bool(experiment.get('experiment_ran'))}，"
            f"干净目录复现通过={bool((experiment.get('reproduction') or {}).get('passed'))}。"
        )
        return {
            "summary": summary,
            "findings": {
                "metric_rows": rows,
                "statistical_analysis": stats,
                "preregistration_trace": experiment.get("preregistration_trace"),
                "reproduction": experiment.get("reproduction"),
                "publishable": experiment.get("publishable"),
            },
            "deliverables": experiment.get("artifacts") or [],
            "risks": protocol.get("expected_risks") or [],
            "next_steps": experiment.get("next_steps") or [],
            "claims": experiment.get("claims") or [],
            "hypotheses": ([{
                "statement": protocol.get("research_question"),
                "rationale": "冻结研究协议中的预注册问题",
            }] if protocol.get("research_question") else []),
            "uncertainties": [],
            "reproducible_experiment": experiment,
        }

    async def _generate_structured(self, llm, prompt: str, task: dict, owner_id: str) -> dict:
        attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 2) + 1
        current_prompt = prompt
        last_error = ""
        for attempt in range(attempts):
            raw = await llm.generate(
                prompt=current_prompt,
                schema=self.RESULT_SCHEMA,
                role="graduate",
                run_id=task.get("run_id"),
                task_id=task.get("id"),
                agent_id=owner_id,
            )
            try:
                return self._parse_result(raw)
            except ValueError as exc:
                last_error = str(exc)
                if attempt + 1 >= attempts:
                    break
                current_prompt = (
                    f"{prompt}\n\n上一次输出未通过结构校验（{last_error}）。"
                    "请只修复 JSON 结构，不新增事实；无法提供证据的 claims 必须删除。\n"
                    f"待修复输出：{raw[:4000]}"
                )
        raise ValueError(f"LLM structured output invalid after {attempts} attempt(s): {last_error}")

    def _parse_result(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise ValueError("response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("response root must be an object")
        if not str(parsed.get("summary") or "").strip():
            raise ValueError("summary is required")
        if not isinstance(parsed.get("claims"), list):
            raise ValueError("claims must be an array")
        return parsed

    def _write_memory(self, task: dict, owner_id: str, result: dict) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        summary = str(result.get("summary") or result.get("conclusion") or task.get("title") or "")
        if summary:
            external_memory.write(
                run_id,
                "project",
                task.get("task_type", "task"),
                summary[:500],
                source_task_id=task.get("id"),
                payload={"task_title": task.get("title"), "task_type": task.get("task_type")},
            )
            external_memory.write(
                run_id,
                "agent",
                "task_experience",
                summary[:500],
                agent_id=owner_id or None,
                source_task_id=task.get("id"),
                payload={"task_title": task.get("title"), "task_type": task.get("task_type")},
            )


task_executor = TaskExecutor()
