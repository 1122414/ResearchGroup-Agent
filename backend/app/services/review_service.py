import json
import uuid
from datetime import datetime
from pathlib import Path

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import (
    EvidenceRepository, OutputRepository, ResearchBriefRepository,
    ResearchClaimRepository, ResearchHypothesisRepository,
    ResearchMilestoneRepository, ResearchUncertaintyRepository,
    ReviewDecisionRepository, RunRepository, TaskRepository,
)
from .artifact_manifest_service import artifact_manifest_service
from .claim_evaluation_service import claim_evaluation_service
from .scientific_quality_gate_service import scientific_quality_gate_service
from .thesis_chapter_service import thesis_chapter_service


class ReviewService:
    async def review(self, task: dict) -> dict:
        logger.info("[ReviewService] review started | task_id=%s | title=%s", task.get("id"), task.get("title", "")[:40])
        latest = self._latest_output(task)
        if task.get("task_type") == "literature_survey" and (
            latest.get("insufficient_evidence") or latest.get("integrity_blocked")
        ):
            return self._review_insufficient_evidence(task, latest)
        quality_gates = await scientific_quality_gate_service.evaluate_task(task, latest)
        if not quality_gates["passed"]:
            return self._review_quality_gate_failure(task, quality_gates)
        system_prompt = prompt_loader.load("advisor_agent")
        advisor_payload = self._advisor_payload(latest)
        cumulative_context = self._incremental_literature_context(task, latest)
        cumulative_instruction = (
            "\n闭环增量证据口径：" + json.dumps(
                cumulative_context, ensure_ascii=False, separators=(",", ":")
            )
            + "\n这是全论文证据池的增量任务，不得要求本次输出单独达到全论文最低数量；"
            "应按 prior_supported 与 current_hard_gate_passed 的去重并集判断。"
            "若 cumulative_meets_contract=true，不得仅因本次输出自身少于最低数量而拒绝。"
            if cumulative_context else ""
        )
        user_prompt = f"""请作为导师 Agent 审核以下任务产出。
任务标题：{task.get('title', '')}
任务类型：{task.get('task_type', '')}
任务描述：{str(task.get('description', ''))[:12000]}
任务输出：{json.dumps(advisor_payload, ensure_ascii=False, separators=(',', ':'))}
{cumulative_instruction}

结构、来源、claim-passage 蕴含、实验工件与独立反方审稿均已通过硬门；
本次只按任务完成度、范围、方法映射与表达清晰度审核，不要重复索取已省略的原始全文 passage。

请返回 JSON：{{"approved": true/false, "feedback": "审核意见"}}"""

        llm = create_llm_provider()
        logger.info("[ReviewService] calling LLM | task_id=%s | role=advisor_review", task.get("id"))
        raw_response = await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            schema={
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean"},
                    "feedback": {"type": "string"},
                },
                "required": ["approved", "feedback"],
            },
            role="advisor_review",
            run_id=task.get("run_id"),
            task_id=task["id"],
            agent_id=task.get("owner_agent"),
        )

        llm_review = self._parse_review(raw_response)
        if llm_review.get("review_transport_failed"):
            raw_response = await llm.generate(
                prompt=(
                    f"{system_prompt}\n\n---\n\n{user_prompt}\n"
                    "上次审核响应为空或 JSON 非法。只重试审核，不重做研究；严格返回所要求的两字段 JSON。"
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "approved": {"type": "boolean"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["approved", "feedback"],
                },
                role="advisor_review",
                run_id=task.get("run_id"),
                task_id=task["id"],
                agent_id=task.get("owner_agent"),
            )
            llm_review = self._parse_review(raw_response)
        if llm_review.get("review_transport_failed"):
            return self._review_advisor_transport_failure(task, quality_gates)
        llm_review = self._arbitrate_advisor(task, latest, llm_review, quality_gates)
        rubric = self._rubric_for_task(task.get("task_type", ""))
        scores = self._score_task(task, llm_review, rubric)
        average_score = round(sum(scores.values()) / max(len(scores), 1), 4)
        approved = bool(llm_review.get("approved", False)) and average_score >= rubric["threshold"]
        review = {
            **llm_review,
            "approved": approved,
            "rubric": rubric,
            "scores": scores,
            "average_score": average_score,
            "requires_revision": not approved,
            "quality_gates": quality_gates,
            "revision_plan": [] if approved else [{
                "layer": "advisor_rubric", "issue": llm_review.get("feedback", "rubric rejected"),
                "required_change": "按导师 rubric 修订后重新执行全部质量门",
            }],
        }
        logger.info(
            "[ReviewService] review result | task_id=%s | approved=%s | score=%.4f",
            task.get("id"),
            approved,
            average_score,
        )
        self._persist_review(task, review)
        if approved:
            self._promote_reviewed_graph(latest)
            self._promote_artifact_claims(task, latest)
        return review

    @staticmethod
    def _promote_reviewed_graph(latest: dict) -> None:
        graph = latest.get("knowledge_graph") or {}
        now = datetime.now().isoformat()
        for claim_id in graph.get("claim_ids") or []:
            claim_evaluation_service.evaluate(claim_id)
        for hypothesis_id in graph.get("hypothesis_ids") or []:
            ResearchHypothesisRepository.update(
                hypothesis_id, status="proposed", updated_at=now,
            )
        for uncertainty_id in graph.get("uncertainty_ids") or []:
            ResearchUncertaintyRepository.update_status(uncertainty_id, "open")

    @staticmethod
    def _arbitrate_advisor(task: dict, latest: dict, review: dict, quality_gates: dict) -> dict:
        if (
            task.get("task_type") == "thesis_chapter"
            and quality_gates.get("passed") is True
            and review.get("approved") is False
            and thesis_chapter_service.advisor_feedback_conflicts_with_artifact(
                task, latest, str(review.get("feedback") or ""),
            )
        ):
            return {
                "approved": True,
                "feedback": (
                    "导师否决要求与冻结实验工件的单位合同冲突，已由更强的工件一致性硬门仲裁为通过。"
                    f" 原意见：{str(review.get('feedback') or '')[:500]}"
                ),
                "advisor_artifact_conflict_overridden": True,
            }
        return review

    @staticmethod
    def _promote_artifact_claims(task: dict, latest: dict) -> None:
        """Promote only artifact claims that already passed all hard and independent gates."""
        claims = {
            " ".join(str(item.get("statement") or "").lower().split()): item
            for item in ResearchClaimRepository.get_by_run(task.get("run_id"))
        }
        now = datetime.now().isoformat()
        experiment_evidence = ReviewService._verified_experiment_evidence(task, latest)
        for item in latest.get("claims") or []:
            provenance = item.get("provenance") or {}
            method_evidence = all(provenance.get(key) for key in (
                "method_family", "input_hashes", "analysis_artifact", "analysis_artifact_sha256",
            ))
            experiment_claim = all(provenance.get(key) for key in (
                "protocol_id", "raw_results", "raw_results_sha256",
            ))
            if not method_evidence and not (experiment_claim and experiment_evidence):
                continue
            claim = claims.get(" ".join(str(item.get("statement") or "").lower().split()))
            if not claim:
                continue
            evidence_ids = experiment_evidence if experiment_claim else [
                provenance["analysis_artifact"], provenance["analysis_artifact_sha256"],
                *provenance["input_hashes"],
                *filter(None, (
                    provenance.get("method_package_artifact"),
                    provenance.get("method_package_artifact_sha256"),
                )),
            ]
            ResearchClaimRepository.update(
                claim["id"], status="supported", confidence=float(item.get("confidence") or 0.8),
                evidence_ids=evidence_ids,
                updated_at=now,
            )

    @staticmethod
    def _verified_experiment_evidence(task: dict, latest: dict) -> list[str]:
        experiment = latest.get("reproducible_experiment") or {}
        metrics = experiment.get("metrics") or {}
        if not (
            experiment.get("publishable") is True
            and (experiment.get("reproduction") or {}).get("passed") is True
            and (metrics.get("statistical_analysis") or {}).get("passed") is True
        ):
            return []
        run = RunRepository.get_by_id(task.get("run_id")) or {}
        run_dir = Path(str(run.get("artifact_dir") or ""))
        manifest = artifact_manifest_service.read(run_dir)
        artifact_paths = {str(path) for path in experiment.get("artifacts") or []}
        evidence_ids: list[str] = []
        for entry in manifest.get("artifacts") or []:
            path = str(entry.get("path") or "")
            digest = str((entry.get("metadata") or {}).get("sha256") or "")
            if path in artifact_paths and digest:
                evidence_ids.extend([path, digest])
        return evidence_ids

    def _review_quality_gate_failure(self, task: dict, quality_gates: dict) -> dict:
        rubric = self._rubric_for_task(task.get("task_type", ""))
        scores = {name: 0.0 for name in rubric["dimensions"]}
        failed_layers = [name for name, result in quality_gates["layers"].items() if not result["passed"]]
        transport_failure = self._is_independent_review_transport_failure(quality_gates)
        review = {
            "approved": False,
            "feedback": "科学质量硬门未通过：" + "、".join(failed_layers),
            "rubric": rubric, "scores": scores, "average_score": 0.0,
            "requires_revision": not transport_failure,
            "review_mode": (
                "independent_review_transport_failure" if transport_failure else "scientific_quality_gate"
            ),
            "quality_gates": quality_gates, "revision_plan": quality_gates["revision_plan"],
        }
        self._persist_review(task, review)
        return review

    def _review_advisor_transport_failure(self, task: dict, quality_gates: dict) -> dict:
        rubric = self._rubric_for_task(task.get("task_type", ""))
        review = {
            "approved": False,
            "feedback": "导师审核连续返回空响应或非法 JSON；已停止自动返工，仅需重试审核或转人工审核。",
            "rubric": rubric,
            "scores": {name: 0.0 for name in rubric["dimensions"]},
            "average_score": 0.0,
            "requires_revision": False,
            "review_mode": "advisor_review_transport_failure",
            "quality_gates": quality_gates,
            "revision_plan": [],
        }
        self._persist_review(task, review)
        return review

    def _review_insufficient_evidence(self, task: dict, latest: dict) -> dict:
        rubric = self._rubric_for_task(task.get("task_type", ""))
        feedback = (
            "系统未检索到足够的可核验来源，当前输出已按学术诚信策略标记为证据不足。"
            "请先扩大或修复检索链路，再继续文献综述；不得基于模型记忆、常识或不可核验来源补写参考文献。"
        )
        scores = self._score_task(task, {"approved": False}, rubric)
        average_score = round(sum(scores.values()) / max(len(scores), 1), 4)
        review = {
            "approved": False,
            "feedback": feedback,
            "rubric": rubric,
            "scores": scores,
            "average_score": average_score,
            "requires_revision": True,
            "review_mode": "insufficient_evidence_guardrail",
            "source_mode": latest.get("source_mode"),
            "revision_plan": [{
                "layer": "provenance", "issue": "insufficient_grounded_evidence",
                "required_change": "扩大检索范围或补充可核验全文 passage；禁止用模型记忆补写",
            }],
        }
        logger.info(
            "[ReviewService] insufficient evidence guardrail | task_id=%s | score=%.4f",
            task.get("id"),
            average_score,
        )
        self._persist_review(task, review)
        return review

    def _persist_review(self, task: dict, review: dict) -> None:
        ReviewDecisionRepository.insert(
            {
                "id": f"review_decision_{uuid.uuid4().hex[:10]}",
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "rubric": review["rubric"],
                "scores": review["scores"],
                "approved": review["approved"],
                "feedback": review.get("feedback", ""),
                "requires_revision": review["requires_revision"],
                "created_at": datetime.now().isoformat(),
            }
        )
        transport_failure = str(review.get("review_mode") or "").endswith("transport_failure")
        TaskRepository.update_status(
            task["id"],
            (
                "completed" if review["approved"]
                else "failed" if transport_failure
                else "need_revision"
            ),
            review_result=review,
            review_feedback=review.get("feedback", ""),
            blocked_reason=(
                "审稿传输失败；停止自动返工，请仅重试审稿或转人工审核。"
                if transport_failure else None
            ),
        )
        if review["approved"]:
            self._advance_milestone(task)
        if review["approved"] and task.get("revision_of_task_id"):
            parent = TaskRepository.get_by_id(task["revision_of_task_id"])
            if parent:
                TaskRepository.update_status(
                    parent["id"],
                    "completed",
                    blocked_reason=None,
                    review_result=review,
                    review_feedback=f"返工任务 {task['id']} 已通过审核。",
                )
        OutputRepository.insert(
            {
                "id": f"review_{task['id']}",
                "output_type": "review",
                "title": f"导师审核：{task.get('title', '')}",
                "content": json.dumps(review, ensure_ascii=False, indent=2),
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "agent_id": task.get("owner_agent"),
                "created_at": datetime.now().isoformat(),
            }
        )

    @staticmethod
    def _advance_milestone(task: dict) -> None:
        milestone_id = task.get("milestone_id")
        if not milestone_id:
            return
        milestones = ResearchMilestoneRepository.get_by_run(task.get("run_id"))
        milestone = next((item for item in milestones if item["id"] == milestone_id), None)
        if not milestone or milestone["milestone_key"] == "report_verified":
            return
        related = [item for item in TaskRepository.get_all(run_id=task.get("run_id")) if item.get("milestone_id") == milestone_id]
        statuses = {item["id"]: item.get("status") for item in related}
        statuses[task["id"]] = "completed"
        if related and all(statuses.get(item["id"]) == "completed" for item in related):
            now = datetime.now().isoformat()
            ResearchMilestoneRepository.update(milestone_id, status="passed", completed_at=now, updated_at=now)

    @staticmethod
    def _latest_output(task: dict) -> dict:
        outputs = task.get("outputs", []) or []
        return outputs[-1] if outputs and isinstance(outputs[-1], dict) else {}

    @staticmethod
    def _is_independent_review_transport_failure(quality_gates: dict) -> bool:
        failed = [name for name, result in quality_gates.get("layers", {}).items() if not result.get("passed")]
        issues = quality_gates.get("layers", {}).get("independent_review", {}).get("issues") or []
        return failed == ["independent_review"] and bool(issues) and all(
            isinstance(issue, dict) and issue.get("target") == "review_transport" for issue in issues
        )

    def _parse_review(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict) and isinstance(parsed.get("approved"), bool):
                return {"approved": parsed["approved"], "feedback": str(parsed.get("feedback") or "")}
        except json.JSONDecodeError:
            pass
        return {
            "approved": False,
            "feedback": "导师审核返回缺失或非法结构，已按不通过处理；请人工检查或有限重试。",
            "review_transport_failed": True,
        }

    @staticmethod
    def _advisor_payload(latest: dict) -> dict:
        """Keep rubric context while excluding passages already checked by hard gates."""
        payload = {
            key: value for key, value in latest.items()
            if key not in {"evidence_excerpts", "evidence_assessments"}
        }
        papers = payload.get("papers_read") or []
        if isinstance(papers, list):
            payload["papers_read"] = [
                {
                    key: paper.get(key)
                    for key in ("id", "title", "authors", "year", "venue", "doi", "url")
                    if paper.get(key) not in (None, "")
                }
                for paper in papers[: settings.literature_source_limit]
                if isinstance(paper, dict)
            ]
        return payload

    @staticmethod
    def _incremental_literature_context(task: dict, latest: dict) -> dict:
        if (
            task.get("task_type") != "literature_survey"
            or not str(task.get("title") or "").startswith("[循环R")
        ):
            return {}
        run_id = task.get("run_id")
        eligible_source_ids = {
            item["id"] for item in ((EvidenceRepository.get_by_run(run_id) or {}).get("sources") or [])
            if (item.get("metadata") or {}).get("citation_eligible")
        }
        prior_claims = [
            item for item in ResearchClaimRepository.get_by_run(run_id)
            if item.get("status") == "supported"
        ]
        prior_source_ids = {
            evidence_id for item in prior_claims
            for evidence_id in item.get("evidence_ids") or []
            if evidence_id in eligible_source_ids
        }
        current_claims = [
            item for item in latest.get("claims") or []
            if item.get("entailment_verdict") == "entailed"
        ]
        current_source_ids = {
            source_id for item in current_claims
            for source_id in item.get("evidence_source_ids") or []
            if source_id in eligible_source_ids
        }
        statements = {
            " ".join(str(item.get("statement") or "").lower().split())
            for item in [*prior_claims, *current_claims]
            if str(item.get("statement") or "").strip()
        }
        requirements = (
            (ResearchBriefRepository.get_by_run(run_id) or {}).get("thesis_requirements") or {}
        )
        required_claims = int(requirements.get("minimum_supported_claims") or 1)
        required_sources = int(requirements.get("minimum_references") or 1)
        cumulative_sources = prior_source_ids | current_source_ids
        return {
            "prior_supported_claim_count": len(prior_claims),
            "prior_supported_source_ids": sorted(prior_source_ids),
            "current_hard_gate_passed_claim_count": len(current_claims),
            "current_hard_gate_passed_source_ids": sorted(current_source_ids),
            "novel_source_ids": sorted(current_source_ids - prior_source_ids),
            "cumulative_distinct_claim_count": len(statements),
            "cumulative_distinct_source_count": len(cumulative_sources),
            "required_supported_claim_count": required_claims,
            "required_reference_count": required_sources,
            "cumulative_meets_contract": (
                len(statements) >= required_claims
                and len(cumulative_sources) >= required_sources
            ),
        }

    def _rubric_for_task(self, task_type: str) -> dict:
        dimensions = {
            "literature_survey": {"coverage": 0.25, "traceability": 0.35, "method_mapping": 0.25, "clarity": 0.15},
            "research_design": {"method_fit": 0.3, "sampling_or_corpus": 0.2, "quality_control": 0.3, "feasibility": 0.2},
            "data_acquisition": {"provenance": 0.35, "integrity": 0.3, "authorization": 0.2, "completeness": 0.15},
            "system_design": {"feasibility": 0.35, "interfaces": 0.25, "risk_control": 0.2, "clarity": 0.2},
            "experiment_design": {"reproducibility": 0.35, "baseline": 0.2, "metrics": 0.25, "safety": 0.2},
            "result_analysis": {"completeness": 0.3, "interpretation": 0.3, "evidence": 0.2, "clarity": 0.2},
            "thesis_chapter": {"structure": 0.2, "evidence": 0.35, "completeness": 0.25, "clarity": 0.2},
            "report_writing": {"structure": 0.25, "evidence": 0.3, "completeness": 0.25, "clarity": 0.2},
        }.get(task_type, {"quality": 1.0})
        return {"dimensions": dimensions, "threshold": settings.review_pass_threshold}

    def _score_task(self, task: dict, review: dict, rubric: dict) -> dict[str, float]:
        outputs = task.get("outputs", []) or []
        latest = outputs[-1] if outputs and isinstance(outputs[-1], dict) else {}
        scores: dict[str, float] = {}
        for dimension in rubric["dimensions"]:
            score = settings.review_default_approved_score if review.get("approved", True) else settings.review_default_rejected_score
            if dimension == "traceability":
                score = 1.0 if latest.get("papers_read") or latest.get("insufficient_evidence") else settings.review_traceability_missing_score
            elif dimension == "method_mapping":
                score = 1.0 if latest.get("methods_found") or latest.get("insufficient_evidence") else settings.review_missing_score
            elif dimension == "reproducibility":
                score = 1.0 if latest.get("reproducible_experiment", {}).get("reproduction", {}).get("passed") else 0.0
            elif dimension == "baseline":
                metrics = latest.get("reproducible_experiment", {}).get("metrics", {})
                score = 1.0 if metrics.get("rows") else settings.review_missing_score
            elif dimension == "metrics":
                stats = latest.get("reproducible_experiment", {}).get("metrics", {}).get("statistical_analysis", {})
                score = 1.0 if stats.get("passed") else settings.review_missing_score
            elif dimension in {"method_fit", "sampling_or_corpus", "quality_control"}:
                package = latest.get("method_package") or {}
                required = {
                    "method_fit": "family", "sampling_or_corpus": "sampling_or_corpus_plan",
                    "quality_control": "quality_controls",
                }[dimension]
                score = 1.0 if package.get(required) else settings.review_missing_score
            elif dimension in {"provenance", "integrity", "authorization", "completeness"}:
                manifest = latest.get("material_manifest") or {}
                records = manifest.get("source_records") or []
                checks = {
                    "provenance": bool(records) and all(item.get("provenance") for item in records),
                    "integrity": bool(records) and all(item.get("sha256") for item in records),
                    "authorization": bool(records) and all(item.get("authorization_evidence") for item in records),
                    "completeness": manifest.get("completeness") == "complete",
                }
                score = 1.0 if checks[dimension] else settings.review_missing_score
            elif dimension == "evidence":
                if task.get("task_type") == "report_writing":
                    score = settings.review_report_evidence_score if latest else settings.review_default_rejected_score
                elif task.get("task_type") == "thesis_chapter":
                    chapter = latest.get("chapter") or {}
                    paragraphs = [
                        paragraph for section in chapter.get("sections") or []
                        for paragraph in section.get("paragraphs") or []
                    ]
                    score = 1.0 if paragraphs and all(
                        item.get("support_ids") or item.get("paragraph_type") in {"transition", "limitation"}
                        for item in paragraphs
                    ) else settings.review_default_rejected_score
                elif task.get("task_type") == "result_analysis":
                    experiment_metrics = latest.get("reproducible_experiment", {}).get("metrics", {})
                    score = 1.0 if (
                        latest.get("analysis_artifact") or latest.get("key_metrics")
                        or latest.get("metrics") or experiment_metrics.get("rows")
                    ) else settings.review_default_rejected_score
                else:
                    score = 1.0 if latest.get("papers_read") or latest.get("reproducible_experiment") else settings.review_default_rejected_score
            scores[dimension] = round(score, 4)
        return scores


review_service = ReviewService()
