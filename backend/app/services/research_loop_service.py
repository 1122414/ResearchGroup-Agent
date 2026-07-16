from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from ..core.config import settings
from ..models.research import ResearchActionContract
from ..storage.repositories import (
    EvidenceRepository,
    ExperimentFindingRepository,
    ExperimentProtocolRepository,
    ExperimentResultRepository,
    LLMUsageRepository,
    ResearchBriefRepository,
    ResearchClaimRepository,
    ResearchDecisionRepository,
    ResearchHypothesisRepository,
    ResearchMilestoneRepository,
    ResearchUncertaintyRepository,
    RunEventRepository,
    RunRepository,
    TaskRepository,
)
from .experiment_domain_service import experiment_domain_service
from .evidence_pipeline_service import EvidencePipelineService
from .knowledge_graph_service import knowledge_graph_service
from .research_loop_critic_service import research_loop_critic_service
from .research_method_registry_service import research_method_registry_service
from .run_event_service import run_event_service
from .task_graph_service import task_graph_service


class ResearchLoopService:
    """Bounded observe-plan-act loop driven by explicit research-state changes."""

    SCOPE_BOUNDARY_MARKERS = (
        "generalizability", "external validity", "other corpora", "other query", "multi-domain",
        "domain mismatch", "beyond the frozen", "outside the frozen", "cannot generalize",
        "larger scale", "natural corpus", "natural corpora",
        "外部效度", "泛化", "其他语料", "其他查询", "多领域", "领域迁移", "冻结范围外",
        "更大规模", "扩大样本", "自然语料", "更自然的语料",
    )
    EXPERIMENT_QUESTION_MARKERS = (
        "mrr", "ranking", "retrieval", "segmentation", "chunk", "排序", "检索", "分割", "切分", "重叠",
    )
    SCOPE_OBJECT_MARKERS = ("dataset", "corpus", "sample", "domain", "数据集", "语料", "样本", "领域")
    SCOPE_EXPANSION_MARKERS = (
        "larger", "more diverse", "additional", "different", "更大", "更多样", "扩大", "其他", "不同",
    )

    def snapshot(self, run_id: str) -> dict:
        state = self._state(run_id)
        events = RunEventRepository.get_by_run(run_id, limit=500, phase="research_loop")
        selected_events = [item for item in events if item["event_type"] == "research_loop.action_selected"]
        observation_events = [item for item in events if item["event_type"] == "research_loop.observation_validated"]
        loop_rounds = max((int(item.get("payload", {}).get("round") or 0) for item in selected_events), default=0)
        seen = {
            str(item.get("payload", {}).get("action", {}).get("fingerprint"))
            for item in selected_events
            if item.get("payload", {}).get("action", {}).get("fingerprint")
        }
        no_progress_rounds = self._consecutive_no_progress(observation_events)
        gaps, human_requirements = self._gaps(run_id, state)
        candidates = [self._candidate(gap, state, loop_rounds + 1) for gap in gaps]
        reviewed = []
        for candidate in candidates:
            critic = research_loop_critic_service.review(candidate, seen, state)
            reviewed.append({**candidate, "critic": critic})
        approved = sorted(
            [item for item in reviewed if item["critic"]["approved"]],
            key=lambda item: item["critic"]["score"],
            reverse=True,
        )

        budget_reason = self._budget_reason(state, loop_rounds)
        stop_reason = ""
        terminal_state = "continue"
        if state["ready_to_report"] and not gaps and not human_requirements:
            terminal_state, stop_reason = "ready_to_report", "关键 claim 已覆盖且没有未解决的高风险缺口"
        elif human_requirements and not approved:
            terminal_state, stop_reason = "human_required", "；".join(human_requirements)
        elif budget_reason:
            terminal_state, stop_reason = "incomplete", budget_reason
        elif no_progress_rounds >= settings.research_loop_max_no_progress_rounds:
            terminal_state, stop_reason = "incomplete", "连续研究动作未产生足够信息增益"
        elif gaps and approved and not settings.research_loop_auto_continue:
            terminal_state, stop_reason = "human_required", "自动研究循环已关闭，需要人工选择下一步动作"
        elif gaps and not approved:
            terminal_state, stop_reason = "incomplete", "候选动作均被独立 critic 拒绝或已执行过"
        elif not gaps:
            terminal_state, stop_reason = "incomplete", "当前没有安全可执行动作，但研究质量门尚未满足"

        return {
            "phase": "ready_to_report" if terminal_state == "ready_to_report" else "revision",
            "state": state,
            "gaps": gaps,
            "human_requirements": human_requirements,
            "candidate_actions": reviewed,
            "approved_actions": approved,
            "loop_rounds": loop_rounds,
            "no_progress_rounds": no_progress_rounds,
            "terminal_state": terminal_state,
            "can_auto_continue": bool(
                settings.research_loop_auto_continue and terminal_state == "continue" and approved
            ),
            "stop_reason": stop_reason,
        }

    def expand_once(self, run_id: str) -> list[dict]:
        self.validate_observations(run_id)
        snapshot = self.snapshot(run_id)
        if not snapshot["can_auto_continue"]:
            self._emit_stop(run_id, snapshot)
            return []

        current_tasks = TaskRepository.get_all(run_id=run_id)
        dependencies = self._research_dependencies(current_tasks)
        selected = self._select_diverse_actions(
            snapshot["approved_actions"], settings.research_loop_max_tasks_per_round,
        )
        round_number = snapshot["loop_rounds"] + 1
        now = datetime.now().isoformat()
        context = self._contract_context(run_id)
        created: list[dict] = []
        for candidate in selected:
            action = ResearchActionContract.model_validate(
                {
                    **candidate,
                    "id": f"action_{uuid.uuid4().hex[:10]}",
                    "round": round_number,
                    "budget": self._action_budget(snapshot["state"], len(selected)),
                    "provenance": {
                        "generator": "deterministic_gap_planner_v1",
                        "state_signature": snapshot["state"]["signature"],
                        "gap_kind": candidate["kind"],
                    },
                }
            ).model_dump()
            task = self._build_task(run_id, action, now, context)
            TaskRepository.insert(task)
            task_graph_service.set_dependencies(task["id"], dependencies)
            created.append(task)
            run_event_service.emit(
                run_id, "research_loop.action_selected", "research_loop", "研究动作已通过独立批判",
                action["objective"], task_id=task["id"], payload={
                    "round": round_number, "action": action, "state_before": snapshot["state"],
                },
            )

        ResearchDecisionRepository.insert(
            {
                "id": f"decision_{uuid.uuid4().hex[:10]}", "run_id": run_id,
                "decision": f"启动第 {round_number} 轮受控研究动作",
                "rationale": "；".join(item["objective"] for item in selected),
                "impact": f"新增 {len(created)} 个动作；全部通过指纹去重与独立 critic",
                "created_at": now,
            }
        )
        return created

    @staticmethod
    def _research_dependencies(tasks: list[dict]) -> list[str]:
        return [
            item["id"] for item in tasks
            if item.get("task_type") not in {"report_writing", "thesis_chapter"}
            and item.get("status") == "completed"
        ]

    @staticmethod
    def _select_diverse_actions(actions: list[dict], limit: int) -> list[dict]:
        """Avoid spending one round on several equivalent tool invocations."""
        limit = max(int(limit), 0)
        if not limit:
            return []
        selected: list[dict] = []
        tools: set[str] = set()
        for action in actions:
            tool = str(action.get("selected_tool") or "")
            if tool in tools:
                continue
            selected.append(action)
            tools.add(tool)
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def is_loop_task(task: dict) -> bool:
        """Return whether a task belongs to a controlled-loop action family."""
        current = task
        visited: set[str] = set()
        while current:
            if str(current.get("title") or "").startswith("[循环R"):
                return True
            parent_id = current.get("revision_of_task_id")
            if not parent_id or parent_id in visited:
                return False
            visited.add(parent_id)
            current = TaskRepository.get_by_id(parent_id)
        return False

    def validate_observations(self, run_id: str) -> list[dict]:
        events = RunEventRepository.get_by_run(run_id, limit=500, phase="research_loop")
        observed = {
            item.get("payload", {}).get("action_id")
            for item in events if item["event_type"] == "research_loop.observation_validated"
        }
        current = self._state(run_id)
        validations: list[dict] = []
        for event in events:
            if event["event_type"] != "research_loop.action_selected":
                continue
            action = event.get("payload", {}).get("action", {})
            if action.get("id") in observed:
                continue
            task = TaskRepository.get_by_id(event.get("task_id"))
            if not task or task.get("status") not in {"completed", "failed", "archived"}:
                continue
            before = event.get("payload", {}).get("state_before", {})
            gain = self._information_gain(before, current, task)
            success = task.get("status") == "completed" and gain >= settings.research_loop_min_information_gain
            validation = {
                "action_id": action.get("id"), "fingerprint": action.get("fingerprint"),
                "round": action.get("round"), "task_id": task["id"], "task_status": task.get("status"),
                "information_gain": gain, "success": success, "state_after": current,
                "observation": "state_changed" if gain > 0.05 else "bounded_negative_result",
            }
            run_event_service.emit(
                run_id, "research_loop.observation_validated", "research_loop", "研究观察已校验",
                f"信息增益={gain}", task_id=task["id"], payload=validation,
            )
            validations.append(validation)
        return validations

    def _state(self, run_id: str) -> dict:
        knowledge_graph_service.synchronize_review_status(run_id)
        scope = knowledge_graph_service.reviewed_graph_scope(run_id)
        all_claims = ResearchClaimRepository.get_by_run(run_id)
        claims = knowledge_graph_service.filter_reviewed_records(all_claims, "claims", scope)
        hypotheses = knowledge_graph_service.filter_reviewed_records(
            ResearchHypothesisRepository.get_by_run(run_id), "hypotheses", scope,
        )
        uncertainties = knowledge_graph_service.filter_reviewed_records(
            ResearchUncertaintyRepository.get_by_run(run_id), "uncertainties", scope,
        )
        evidence = EvidenceRepository.get_by_run(run_id)
        results = ExperimentResultRepository.get_by_run(run_id)
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        tasks = TaskRepository.get_all(run_id=run_id)
        usage = self._loop_usage_summary(run_id)
        auditable_claims = [item for item in claims if item["status"] != "retracted"]
        supported = [item for item in auditable_claims if item["status"] == "supported"]
        supported_ids = {item["id"] for item in supported}
        sources_by_id = {item["id"]: item for item in evidence["sources"]}
        linked_sources = [
            sources_by_id[item["source_id"]]
            for item in evidence["links"]
            if item.get("claim_id") in supported_ids
            and item.get("relation_type") == "supports"
            and item.get("source_id") in sources_by_id
        ]
        citation_source_count = self._unique_source_count(linked_sources)
        coverage = len(supported) / len(auditable_claims) if auditable_claims else 0.0
        publishable = [item for item in results if (item.get("metrics") or {}).get("publishable") is True]
        analyses = research_method_registry_service.verified_analysis_artifacts(tasks, brief)
        result_requirement = research_method_registry_service.result_evidence_requirement(brief)
        method_result_ready = bool(
            result_requirement == "none"
            or (result_requirement == "publishable_experiment" and publishable)
            or (result_requirement == "verified_analysis" and analyses)
        )
        actionable_high = self._actionable_high_uncertainties(uncertainties, method_result_ready)
        thesis_requirements = brief.get("thesis_requirements") or {}
        thesis_confirmed = thesis_requirements.get("status") == "confirmed"
        required_claims = max(1, int(thesis_requirements.get("minimum_supported_claims") or 1))
        required_references = max(1, int(thesis_requirements.get("minimum_references") or 1))
        values = {
            "source_count": self._unique_source_count(evidence["sources"]),
            "passage_count": len(evidence["excerpts"]),
            "claim_count": len(auditable_claims), "supported_claim_count": len(supported),
            "staged_claim_count": len(all_claims) - len(claims),
            "contested_claim_count": len([item for item in claims if item["status"] == "contested"]),
            "active_hypothesis_count": len([item for item in hypotheses if item["status"] in {"active", "proposed"}]),
            "publishable_experiment_count": len(publishable),
            "verified_analysis_count": len(analyses),
            "methodology_family": brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family"),
            "result_evidence_requirement": result_requirement,
            "method_result_ready": method_result_ready,
            "high_uncertainty_count": len(actionable_high),
            "citation_source_count": citation_source_count,
            "required_supported_claim_count": required_claims,
            "required_reference_count": required_references,
            "claim_coverage": round(coverage, 4), "total_tokens": usage["total_tokens"],
            "total_cost_usd": round(usage["total_cost_usd"], 6),
            "minimum_information_gain": settings.research_loop_min_information_gain,
        }
        signature_payload = {key: value for key, value in values.items() if key not in {"total_tokens", "total_cost_usd"}}
        values["signature"] = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        values["ready_to_report"] = bool(
            auditable_claims and values["passage_count"] > 0
            and coverage >= settings.research_loop_claim_coverage_target
            and values["contested_claim_count"] == 0 and values["high_uncertainty_count"] == 0
            and (not thesis_confirmed or len(supported) >= required_claims)
            and (not thesis_confirmed or citation_source_count >= required_references)
            and method_result_ready
        )
        return values

    @staticmethod
    def _unique_source_count(sources: list[dict]) -> int:
        return len({EvidencePipelineService._source_identity(item) for item in sources})

    @staticmethod
    def _loop_usage_summary(run_id: str) -> dict:
        tasks = TaskRepository.get_all(run_id=run_id)
        loop_roots = {
            item["id"] for item in tasks
            if str(item.get("title") or "").startswith("[循环R")
        }
        loop_task_ids = {
            item["id"] for item in tasks
            if item["id"] in loop_roots or item.get("revision_of_task_id") in loop_roots
        }
        usage = [
            item for item in LLMUsageRepository.get_by_run(run_id)
            if item.get("task_id") in loop_task_ids
        ]
        return {
            "total_tokens": sum(int(item.get("total_tokens") or 0) for item in usage),
            "total_cost_usd": sum(float(item.get("cost_usd") or 0) for item in usage),
        }

    def _gaps(self, run_id: str, state: dict) -> tuple[list[dict], list[str]]:
        scope = knowledge_graph_service.reviewed_graph_scope(run_id)
        claims = knowledge_graph_service.filter_reviewed_records(
            ResearchClaimRepository.get_by_run(run_id), "claims", scope,
        )
        hypotheses = knowledge_graph_service.filter_reviewed_records(
            ResearchHypothesisRepository.get_by_run(run_id), "hypotheses", scope,
        )
        uncertainties = knowledge_graph_service.filter_reviewed_records(
            ResearchUncertaintyRepository.get_by_run(run_id), "uncertainties", scope,
        )
        protocols = ExperimentProtocolRepository.get_by_run(run_id)
        findings = ExperimentFindingRepository.get_by_run(run_id)
        results = ExperimentResultRepository.get_by_run(run_id)
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        run = RunRepository.get_by_id(run_id)
        gaps: list[dict] = []
        human: list[str] = []
        if state["passage_count"] == 0:
            gaps.append(self._gap("missing_evidence", "run", "尚无可引用全文片段", "literature_survey", 0.9))
        for claim in claims:
            if claim["status"] in {"draft", "contested"}:
                gaps.append(self._gap(
                    "contested_claim" if claim["status"] == "contested" else "unsupported_claim",
                    claim["id"], f"核验 claim：{claim['statement']}", "literature_survey", 0.85,
                ))
        result_requirement = state.get("result_evidence_requirement") or research_method_registry_service.result_evidence_requirement(brief)
        method_result_ready = bool(state.get("method_result_ready"))
        actionable_uncertainty_ids = {
            item["id"] for item in self._actionable_high_uncertainties(uncertainties, method_result_ready)
        }
        for uncertainty in uncertainties:
            if uncertainty["id"] in actionable_uncertainty_ids:
                gaps.append(self._gap(
                    "high_uncertainty", uncertainty["id"], uncertainty["description"], "literature_survey", 0.8,
                ))

        if result_requirement == "publishable_experiment":
            supported_hypotheses = [item for item in hypotheses if item.get("status") == "supported"]
            protocol_hypothesis_ids = {item["hypothesis_id"] for item in protocols}
            publishable_result_ids = {
                item["id"] for item in results if (item.get("metrics") or {}).get("publishable") is True
            }
            finding_hypothesis_ids = {
                item["hypothesis_id"] for item in findings if item.get("result_id") in publishable_result_ids
            }
            results_by_protocol = {}
            for result in results:
                results_by_protocol.setdefault(result.get("protocol_id"), []).append(result)
            for hypothesis in hypotheses:
                if hypothesis["status"] not in {"active", "proposed"}:
                    continue
                if self._is_scope_boundary(str(hypothesis.get("statement") or "")):
                    continue
                if any(self._same_hypothesis(hypothesis, item) for item in supported_hypotheses):
                    continue
                if hypothesis["id"] in finding_hypothesis_ids:
                    continue
                hypothesis_protocols = [item for item in protocols if item["hypothesis_id"] == hypothesis["id"]]
                prior_results = [
                    result for protocol in hypothesis_protocols for result in results_by_protocol.get(protocol["id"], [])
                ]
                if prior_results:
                    human.append(self._experiment_diagnosis(hypothesis["id"], prior_results[-1]))
                    continue
                if hypothesis_protocols:
                    human.append(f"协议对应假设 {hypothesis['id']} 尚无实验结果；检查执行审批、沙箱和失败日志")
                    continue
                capability = experiment_domain_service.classify(
                    {"run_id": run_id, "hypothesis_id": hypothesis["id"], "title": hypothesis["statement"]}, run
                )
                if not capability["supported"] or not capability["publishable_data_ready"]:
                    human.append(f"假设 {hypothesis['id']} 缺少受支持领域模板或带许可/伦理声明的标注数据")
                    continue
                gaps.append(self._gap(
                    "untested_hypothesis", hypothesis["id"], f"检验假设：{hypothesis['statement']}",
                    "experiment_design", 0.95, dataset_ready=True,
                ))
            for hypothesis_id in protocol_hypothesis_ids - finding_hypothesis_ids:
                if not any(hypothesis_id in item for item in human):
                    human.append(f"协议对应假设 {hypothesis_id} 尚无通过复现的 finding，需要诊断或人工介入")
        elif result_requirement == "verified_analysis" and not method_result_ready:
            gaps.append(self._gap(
                "missing_verified_analysis", "run",
                "当前方法范式尚无通过方法专用质量门和真实独立审查的可追溯分析工件",
                "result_analysis", 0.95,
            ))

        if state["source_count"] and not claims:
            gaps.append(self._gap("claim_synthesis", "run", "已有证据但尚未形成可核验 claim", "literature_survey", 0.75))
        thesis_gap = self._thesis_evidence_gap(brief, state)
        if thesis_gap:
            gaps.append(thesis_gap)
        return self._dedupe_gaps(gaps), list(dict.fromkeys(human))

    def _thesis_evidence_gap(self, brief: dict, state: dict) -> dict | None:
        requirements = brief.get("thesis_requirements") or {}
        if requirements.get("status") != "confirmed":
            return None
        required_claims = max(1, int(requirements.get("minimum_supported_claims") or 1))
        required_references = max(1, int(requirements.get("minimum_references") or 1))
        actual_claims = int(state.get("supported_claim_count") or 0)
        actual_references = int(state.get("citation_source_count") or 0)
        if actual_claims >= required_claims and actual_references >= required_references:
            return None
        reason = (
            f"论文证据契约尚未满足：受支持 claim {actual_claims}/{required_claims}，"
            f"有 support 链的不同来源 {actual_references}/{required_references}。"
            "从已核验全文或新增真实全文中综合缺少的、逐来源直接蕴含的原子 claim；"
            "每条必须使用 relation=supports 并绑定 source ID 与 passage ID，"
            "来源未比较某设置等缺失性陈述只能作为 context note，不能凑数。"
        )
        return self._gap("thesis_evidence_coverage", "run", reason, "literature_survey", 0.9)

    def _actionable_high_uncertainties(self, uncertainties: list[dict], method_result_ready: bool) -> list[dict]:
        return [
            item for item in uncertainties
            if item.get("status") == "open"
            and item.get("severity") == "high"
            and not self._is_scope_boundary(str(item.get("description") or ""))
            and not (
                method_result_ready
                and any(
                    marker in str(item.get("description") or "").lower()
                    for marker in self.EXPERIMENT_QUESTION_MARKERS
                )
            )
        ]

    def _is_scope_boundary(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in self.SCOPE_BOUNDARY_MARKERS) or (
            any(marker in lowered for marker in self.SCOPE_OBJECT_MARKERS)
            and any(marker in lowered for marker in self.SCOPE_EXPANSION_MARKERS)
        )

    @classmethod
    def _same_hypothesis(cls, left: dict, right: dict) -> bool:
        left_concepts = cls._hypothesis_concepts(str(left.get("statement") or ""))
        right_concepts = cls._hypothesis_concepts(str(right.get("statement") or ""))
        shared = left_concepts & right_concepts
        return len(shared) >= 3 and len(shared) / max(len(left_concepts | right_concepts), 1) >= 0.6

    @staticmethod
    def _hypothesis_concepts(text: str) -> set[str]:
        lowered = text.lower().replace("_", "-")
        groups = {
            "mrr": ("mrr",),
            "top_k": ("top-k", "topk", "hit@", "hits@"),
            "overlap": ("overlap", "重叠"),
            "no_split": ("no-split", "no split", "无分割", "不分割"),
            "segmentation": ("segment", "split", "chunk", "分割", "切分"),
            "improvement": ("improv", "outperform", "提升", "优于"),
        }
        return {name for name, markers in groups.items() if any(marker in lowered for marker in markers)}

    @staticmethod
    def _gap(kind: str, target_id: str, reason: str, task_type: str, gain: float, dataset_ready: bool = False) -> dict:
        return {
            "kind": kind, "target_id": target_id, "reason": reason, "task_type": task_type,
            "expected_information_gain": gain, "dataset_ready": dataset_ready,
        }

    @staticmethod
    def _dedupe_gaps(gaps: list[dict]) -> list[dict]:
        unique = {}
        for gap in gaps:
            unique[(gap["kind"], gap["target_id"])] = gap
        return list(unique.values())

    def _candidate(self, gap: dict, state: dict, round_number: int) -> dict:
        tool = {
            "literature_survey": "evidence_search", "experiment_design": "experiment_runner",
            "result_analysis": "result_analyzer",
        }[gap["task_type"]]
        strategies = ["direct_verification", "counterevidence_and_replication", "boundary_conditions_and_limits"]
        strategy = strategies[min(round_number - 1, len(strategies) - 1)] if tool == "evidence_search" else "preregistered_execution"
        fingerprint = hashlib.sha256(
            json.dumps(
                {"kind": gap["kind"], "target": gap["target_id"], "tool": tool, "strategy": strategy},
                sort_keys=True,
            ).encode()
        ).hexdigest()[:20]
        return {
            **gap, "objective": f"{gap['reason']}（策略：{strategy}）",
            "target": {"type": gap["kind"], "id": gap["target_id"]},
            "selected_tool": tool,
            "arguments": {"query_focus": f"{gap['reason']} {strategy}", "round": round_number, "strategy": strategy},
            "expected_observation": "获得能改变目标研究对象状态的新 passage、统计结果或结构化负结果",
            "success_condition": "目标状态改变，或形成有边界且不可重复执行的负结果",
            "failure_handling": "不重复同一指纹动作；记录失败并在连续无进展后转人工",
            "safety_level": "medium" if tool == "experiment_runner" else "low",
            "fingerprint": fingerprint, "estimated_cost": 1.0 if tool == "experiment_runner" else 0.3,
        }

    @staticmethod
    def _experiment_diagnosis(hypothesis_id: str, result: dict) -> str:
        metrics = result.get("metrics") or {}
        if metrics.get("artifact_class") != "external":
            action = "补充含文档、标注 query/qrel、license 与 ethics_review 的评测集"
        elif not metrics.get("trusted_evaluator"):
            action = "改用受信评测器并审查生成代码，不能让生成脚本自报指标"
        elif not (metrics.get("statistical_analysis") or {}).get("passed"):
            action = "修复重复运行、baseline/消融或统计输出后再执行"
        elif not (metrics.get("reproduction") or {}).get("passed"):
            action = "检查独立复现日志、输入 hash 与主指标差异"
        else:
            action = "检查沙箱执行状态和 artifact 完整性"
        return f"假设 {hypothesis_id} 的实验不可发表；诊断动作：{action}"

    def _contract_context(self, run_id: str) -> dict:
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        milestones = {item["milestone_key"]: item["id"] for item in ResearchMilestoneRepository.get_by_run(run_id)}
        return {
            "subquestion_id": next((item.get("id") for item in brief.get("subquestions") or [] if item.get("id")), None),
            "hypothesis_id": next((item["id"] for item in ResearchHypothesisRepository.get_by_run(run_id)), None),
            "milestones": milestones,
        }

    @staticmethod
    def _build_task(run_id: str, action: dict, now: str, context: dict) -> dict:
        task_type = {
            "evidence_search": "literature_survey", "experiment_runner": "experiment_design",
            "result_analyzer": "result_analysis",
        }[action["selected_tool"]]
        skills = {
            "literature_survey": {"literature_review": 9, "coding": 1, "experiment": 1, "data_analysis": 4, "academic_writing": 3, "mentoring": 1},
            "experiment_design": {"literature_review": 1, "coding": 5, "experiment": 9, "data_analysis": 7, "academic_writing": 1, "mentoring": 1},
            "result_analysis": {"literature_review": 4, "coding": 2, "experiment": 3, "data_analysis": 9, "academic_writing": 5, "mentoring": 1},
        }[task_type]
        milestone_key = {
            "literature_survey": "evidence_sufficient", "experiment_design": "experiment_protocol_frozen",
            "result_analysis": "replication_passed",
        }[task_type]
        return {
            "id": f"task_{uuid.uuid4().hex[:8]}", "run_id": run_id,
            "title": f"[循环R{action['round']}] {action['objective'][:42]}",
            "description": action["objective"] + "\n\n## 研究动作契约（非检索词）\n" + json.dumps(action, ensure_ascii=False, indent=2),
            "task_type": task_type, "required_skills": skills, "priority": 7, "complexity": 5,
            "decomposability": 5, "status": "pending", "owner_agent": None,
            "collaborator_agents": [], "subtasks": [], "outputs": [], "review_result": None,
            "review_feedback": None, "blocked_reason": None, "parallelizable": True,
            "is_critical_path": False, "attempt_count": 0, "last_checkpoint": None,
            "subquestion_id": context["subquestion_id"],
            "hypothesis_id": action["target"]["id"] if action["target"]["type"] == "untested_hypothesis" else context["hypothesis_id"],
            "milestone_id": context["milestones"].get(milestone_key), "created_at": now, "updated_at": now,
        }

    @staticmethod
    def _information_gain(before: dict, after: dict, task: dict) -> float:
        gain = 0.0
        gain += max(after.get("passage_count", 0) - before.get("passage_count", 0), 0) * 0.05
        gain += max(after.get("supported_claim_count", 0) - before.get("supported_claim_count", 0), 0) * 0.2
        gain += max(after.get("citation_source_count", 0) - before.get("citation_source_count", 0), 0) * 0.2
        gain += max(before.get("contested_claim_count", 0) - after.get("contested_claim_count", 0), 0) * 0.2
        gain += max(after.get("publishable_experiment_count", 0) - before.get("publishable_experiment_count", 0), 0) * 0.3
        gain += max(after.get("verified_analysis_count", 0) - before.get("verified_analysis_count", 0), 0) * 0.3
        gain += max(before.get("high_uncertainty_count", 0) - after.get("high_uncertainty_count", 0), 0) * 0.2
        return round(min(gain, 1.0), 4)

    @staticmethod
    def _consecutive_no_progress(events: list[dict]) -> int:
        count = 0
        rounds = {}
        for event in events:
            payload = event.get("payload", {})
            rounds.setdefault(int(payload.get("round") or 0), []).append(bool(payload.get("success")))
        for round_number in sorted(rounds, reverse=True):
            if any(rounds[round_number]):
                break
            count += 1
        return count

    @staticmethod
    def _budget_reason(state: dict, rounds: int) -> str:
        if rounds >= settings.research_loop_max_auto_rounds:
            return f"已达到最大自动研究轮次 {settings.research_loop_max_auto_rounds}"
        if state["total_tokens"] >= settings.research_loop_max_tokens:
            return f"已达到研究循环 token 预算 {settings.research_loop_max_tokens}"
        if state["total_cost_usd"] >= settings.research_loop_max_cost_usd:
            return f"已达到研究循环成本预算 ${settings.research_loop_max_cost_usd}"
        return ""

    @staticmethod
    def _action_budget(state: dict, action_count: int) -> dict:
        divisor = max(action_count, 1)
        return {
            "max_tokens": max((settings.research_loop_max_tokens - state["total_tokens"]) // divisor, 0),
            "max_cost_usd": round(max(settings.research_loop_max_cost_usd - state["total_cost_usd"], 0) / divisor, 4),
            "max_time_seconds": settings.research_loop_action_timeout_seconds,
        }

    @staticmethod
    def _emit_stop(run_id: str, snapshot: dict) -> None:
        if snapshot["terminal_state"] == "continue":
            return
        previous = RunEventRepository.get_by_run(run_id, limit=500, phase="research_loop")
        marker = f"{snapshot['terminal_state']}:{snapshot['state']['signature']}:{snapshot['loop_rounds']}"
        if any(item["event_type"] == "research_loop.stopped" and item.get("payload", {}).get("marker") == marker for item in previous):
            return
        run_event_service.emit(
            run_id, "research_loop.stopped", "research_loop", "受控研究循环已停止",
            snapshot["stop_reason"], payload={
                "marker": marker, "terminal_state": snapshot["terminal_state"],
                "reason": snapshot["stop_reason"], "state": snapshot["state"],
            },
        )


research_loop_service = ResearchLoopService()
