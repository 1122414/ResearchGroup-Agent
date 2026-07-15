from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..storage.repositories import (
    EvidenceRepository,
    ExperimentResultRepository,
    ResearchBriefRepository,
    ResearchClaimRepository,
    RunRepository,
    TaskRepository,
)
from .artifact_manifest_service import artifact_manifest_service
from .independent_reviewer_service import independent_reviewer_service
from .run_artifact_service import run_artifact_service


class ScientificQualityGateService:
    async def evaluate_task(self, task: dict, latest: dict) -> dict:
        evidence = EvidenceRepository.get_by_run(task.get("run_id"))
        layers = {
            "schema": self._schema_gate(task, latest),
            "provenance": self._provenance_gate(task, latest, evidence),
            "semantic": self._semantic_gate(task, latest),
            "method": self._method_gate(task, latest),
        }
        deterministic_passed = all(item["passed"] for item in layers.values())
        independent = (
            await independent_reviewer_service.review_task(task, latest, evidence)
            if deterministic_passed
            else {
                "approved": False, "issues": [],
                "summary": "deterministic hard gate failed; independent model call skipped",
                "reviewer": "not_called_after_hard_gate_failure",
            }
        )
        layers["independent_review"] = {
            "passed": bool(independent.get("approved")),
            "issues": independent.get("issues") or [],
            "reviewer": independent.get("reviewer"),
            "simulation": bool(independent.get("simulation")),
        }
        passed = all(item["passed"] for item in layers.values())
        return {
            "passed": passed, "layers": layers,
            "revision_plan": self._revision_plan(layers),
            "hard_gate_policy": "all_layers_required",
        }

    def evaluate_report(self, run_id: str, report: str, grounding_audit: dict) -> dict:
        evidence = EvidenceRepository.get_by_run(run_id)
        claims = ResearchClaimRepository.get_by_run(run_id)
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        results = ExperimentResultRepository.get_by_run(run_id)
        tasks = TaskRepository.get_all(run_id=run_id)
        issues = {
            "schema": [] if report.startswith("# ") and "参考文献" in report else ["report_structure_incomplete"],
            "provenance": [] if grounding_audit.get("passed") else ["grounding_audit_failed"],
            "semantic": [],
            "method": [],
            "independent_review": [],
        }
        sources = {item["id"]: item for item in evidence["sources"]}
        excerpts = {item["id"]: item for item in evidence["excerpts"]}
        links_by_claim = {}
        for link in evidence["links"]:
            links_by_claim.setdefault(link["claim_id"], []).append(link)
        for claim in claims:
            if claim["status"] != "supported":
                continue
            valid_links = [
                link for link in links_by_claim.get(claim["id"], [])
                if link.get("relation_type") == "supports"
                and link.get("excerpt_id") in excerpts
                and excerpts[link["excerpt_id"]].get("excerpt_type") not in {"metadata_only", "summary"}
                and (sources.get(link["source_id"], {}).get("metadata") or {}).get("citation_eligible")
            ]
            if not valid_links:
                issues["semantic"].append(f"supported_claim_without_verified_link:{claim['id']}")
        if brief.get("research_type") in {"empirical", "mixed"} and not any(
            (item.get("metrics") or {}).get("publishable") is True for item in results
        ):
            issues["method"].append("empirical_report_without_publishable_experiment")
        for task in tasks:
            if task.get("task_type") == "report_writing" or task.get("status") != "completed":
                continue
            quality = (task.get("review_result") or {}).get("quality_gates") or {}
            if not quality.get("passed"):
                issues["independent_review"].append(f"task_without_full_quality_gate:{task['id']}")
        layers = {
            name: {"passed": not layer_issues, "issues": layer_issues, "verifier": f"report_{name}_gate_v1"}
            for name, layer_issues in issues.items()
        }
        passed = all(item["passed"] for item in layers.values())
        simulated_reviews = any(
            ((task.get("review_result") or {}).get("quality_gates") or {}).get("layers", {})
            .get("independent_review", {}).get("simulation")
            for task in tasks if task.get("status") == "completed"
        )
        return {
            "passed": passed,
            "publication_ready": passed and not simulated_reviews,
            "publication_blockers": ["mock_or_simulated_independent_review"] if passed and simulated_reviews else [],
            "layers": layers, "revision_plan": self._revision_plan(layers),
            "hard_gate_policy": "all_layers_required",
        }

    @staticmethod
    def _schema_gate(task: dict, latest: dict) -> dict:
        errors = []
        if not isinstance(latest, dict):
            errors.append("output_root_not_object")
        if not str(latest.get("summary") or "").strip():
            errors.append("summary_missing")
        if not isinstance(latest.get("claims"), list):
            errors.append("claims_not_array")
        if task.get("task_type") == "experiment_design" and not isinstance(latest.get("reproducible_experiment"), dict):
            errors.append("experiment_result_missing")
        return {"passed": not errors, "issues": errors, "verifier": "schema_gate_v1"}

    def _provenance_gate(self, task: dict, latest: dict, evidence: dict) -> dict:
        issues: list[str] = []
        sources = {item["id"]: item for item in evidence["sources"]}
        excerpts = {item["id"]: item for item in evidence["excerpts"]}
        claims_to_check = (
            latest.get("claims") or []
            if task.get("task_type") in {"literature_survey", "result_analysis"}
            else []
        )
        for index, claim in enumerate(claims_to_check):
            provenance = claim.get("provenance") or {}
            if task.get("task_type") == "result_analysis" and all(
                provenance.get(key) for key in ("protocol_id", "raw_results", "raw_results_sha256")
            ):
                continue
            source_ids = set(claim.get("evidence_source_ids") or [])
            passage_ids = claim.get("evidence_passage_ids") or []
            if not source_ids or not passage_ids:
                issues.append(f"claim_{index}:missing_source_or_passage")
                continue
            for passage_id in passage_ids:
                excerpt = excerpts.get(passage_id)
                if not excerpt or excerpt.get("excerpt_type") in {"metadata_only", "summary"}:
                    issues.append(f"claim_{index}:invalid_passage:{passage_id}")
                elif excerpt.get("source_id") not in source_ids:
                    issues.append(f"claim_{index}:passage_source_mismatch:{passage_id}")
            if any(not (sources.get(source_id, {}).get("metadata") or {}).get("citation_eligible") for source_id in source_ids):
                issues.append(f"claim_{index}:ineligible_source")

        if task.get("task_type") == "experiment_design":
            issues.extend(self._artifact_issues(task, latest))
        return {"passed": not issues, "issues": issues, "verifier": "provenance_gate_v1"}

    @staticmethod
    def _semantic_gate(task: dict, latest: dict) -> dict:
        issues = []
        claims = latest.get("claims") or []
        if task.get("task_type") == "literature_survey" and not claims:
            issues.append("literature_review_without_verified_claim")
        if task.get("task_type") == "literature_survey" and claims:
            audit = latest.get("entailment_audit") or {}
            if not audit.get("checked"):
                issues.append("entailment_audit_missing")
            for index, claim in enumerate(claims):
                if claim.get("entailment_verdict") not in {"entailed", "partially_entailed"}:
                    issues.append(f"claim_{index}:entailment_not_verified")
                statement = str(claim.get("statement") or "").lower()
                # A paper may report a statistically significant result from its
                # own experiment. Require corroboration only when the wording
                # makes a causal/proof claim that extrapolates beyond that source.
                high_risk = any(marker in statement for marker in ("导致", "证明", "证实")) or bool(
                    re.search(r"\b(?:cause|causes|caused|prove|proves|proven)\b", statement)
                )
                attributed = any(marker in statement for marker in (
                    "该研究", "该论文", "该文", "作者报告", "作者观察",
                    "the study", "the paper", "the authors report", "the authors observe",
                ))
                if high_risk and not attributed and len(set(claim.get("evidence_source_ids") or [])) < 2:
                    issues.append(f"claim_{index}:high_risk_requires_two_sources")
        return {"passed": not issues, "issues": issues, "verifier": "semantic_gate_v1"}

    @staticmethod
    def _method_gate(task: dict, latest: dict) -> dict:
        issues = []
        if task.get("task_type") == "experiment_design":
            experiment = latest.get("reproducible_experiment") or {}
            metrics = experiment.get("metrics") or {}
            if not experiment.get("publishable"):
                issues.append("experiment_not_publishable")
            if not metrics.get("trusted_evaluator"):
                issues.append("untrusted_metric_evaluator")
            if not (metrics.get("statistical_analysis") or {}).get("passed"):
                issues.append("statistical_requirements_failed")
            if not (metrics.get("reproduction") or {}).get("passed"):
                issues.append("independent_reproduction_failed")
        return {"passed": not issues, "issues": issues, "verifier": "method_gate_v1"}

    @staticmethod
    def _revision_plan(layers: dict) -> list[dict]:
        plan = []
        for layer, result in layers.items():
            for issue in result.get("issues") or []:
                reason = issue.get("reason") if isinstance(issue, dict) else str(issue)
                if isinstance(issue, dict):
                    required_change = issue.get("required_change")
                elif "high_risk_requires_two_sources" in reason:
                    required_change = (
                        "该主张若只由一篇论文支持，必须明确写成‘该研究/该论文在其设置下报告……’；"
                        "只有找到第二个独立来源及其 passage 时，才可保留无归因的跨来源因果表述。"
                    )
                else:
                    required_change = "修复该层问题并重新运行验证"
                plan.append({"layer": layer, "issue": reason, "required_change": required_change})
        return plan

    @staticmethod
    def _artifact_issues(task: dict, latest: dict) -> list[str]:
        experiment = latest.get("reproducible_experiment") or {}
        paths = experiment.get("artifacts") or []
        run = RunRepository.get_by_id(task.get("run_id")) or {}
        run_dir = run_artifact_service.run_dir(run, task.get("run_id"))
        manifest = artifact_manifest_service.read(run_dir)
        entries = {item["path"]: item for item in manifest.get("artifacts") or []}
        issues = []
        for raw_path in paths:
            path = Path(raw_path)
            entry = entries.get(str(path))
            expected = (entry or {}).get("metadata", {}).get("sha256")
            if not path.is_file() or not expected:
                issues.append(f"artifact_missing_or_unregistered:{path}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                issues.append(f"artifact_hash_mismatch:{path}")
        if not paths:
            issues.append("experiment_artifacts_missing")
        return issues


scientific_quality_gate_service = ScientificQualityGateService()
