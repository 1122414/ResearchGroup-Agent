from __future__ import annotations

import json
from pathlib import Path

from .research_contract_service import research_contract_service
from .scientific_quality_gate_service import scientific_quality_gate_service


class ResearchBenchmarkService:
    def run(self, fixture_path: Path) -> dict:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        citation_results = [self._citation_case(item, fixture["citation_evidence"]) for item in fixture["citation_cases"]]
        planning_results = [self._planning_case(item) for item in fixture["planning_cases"]]
        experiment_results = [self._experiment_case(item) for item in fixture["experiment_cases"]]
        all_results = [*citation_results, *planning_results, *experiment_results]
        negatives = [item for item in all_results if not item["expected_pass"]]
        positives = [item for item in all_results if item["expected_pass"]]
        false_accepts = [item for item in negatives if item["predicted_pass"]]
        false_rejects = [item for item in positives if not item["predicted_pass"]]
        accepted_citations = [item for item in citation_results if item["predicted_pass"]]
        correct_accepted_citations = [item for item in accepted_citations if item["expected_pass"]]
        citation_precision = len(correct_accepted_citations) / len(accepted_citations) if accepted_citations else 0.0
        citation_completeness = sum(item["traceable"] for item in citation_results if item["expected_pass"]) / max(
            len([item for item in citation_results if item["expected_pass"]]), 1
        )
        metrics = {
            "case_count": len(all_results),
            "citation_precision": round(citation_precision, 4),
            "citation_completeness": round(citation_completeness, 4),
            "false_accept_rate": round(len(false_accepts) / max(len(negatives), 1), 4),
            "false_reject_rate": round(len(false_rejects) / max(len(positives), 1), 4),
            "planning_accuracy": self._accuracy(planning_results),
            "experiment_gate_accuracy": self._accuracy(experiment_results),
        }
        targets = fixture["targets"]
        target_checks = {
            "citation_precision": metrics["citation_precision"] >= targets["citation_precision"],
            "citation_completeness": metrics["citation_completeness"] >= targets["citation_completeness"],
            "false_accept_rate": metrics["false_accept_rate"] <= targets["false_accept_rate"],
            "planning_accuracy": metrics["planning_accuracy"] >= targets["planning_accuracy"],
            "experiment_gate_accuracy": metrics["experiment_gate_accuracy"] >= targets["experiment_gate_accuracy"],
        }
        return {
            "benchmark": fixture.get("name"), "metrics": metrics, "targets": targets,
            "target_checks": target_checks, "passed": all(target_checks.values()),
            "cases": all_results,
        }

    @staticmethod
    def _citation_case(case: dict, default_evidence: dict) -> dict:
        task = {"task_type": "literature_survey", "run_id": "benchmark"}
        latest = case["latest"]
        evidence = case.get("evidence") or default_evidence
        gates = [
            scientific_quality_gate_service._schema_gate(task, latest),
            scientific_quality_gate_service._provenance_gate(task, latest, evidence),
            scientific_quality_gate_service._semantic_gate(task, latest),
        ]
        claims = latest.get("claims") or []
        traceable = bool(claims) and all(
            claim.get("evidence_source_ids") and claim.get("evidence_passage_ids") for claim in claims
        )
        return {
            "id": case["id"], "category": "citation", "expected_pass": case["expected_pass"],
            "predicted_pass": all(item["passed"] for item in gates), "traceable": traceable,
            "issues": [issue for gate in gates for issue in gate["issues"]],
        }

    @staticmethod
    def _planning_case(case: dict) -> dict:
        errors = research_contract_service.validate(case["brief"], case["hypotheses"])
        return {
            "id": case["id"], "category": "planning", "expected_pass": case["expected_pass"],
            "predicted_pass": not errors, "traceable": True, "issues": errors,
        }

    @staticmethod
    def _experiment_case(case: dict) -> dict:
        gate = scientific_quality_gate_service._method_gate(
            {"task_type": "experiment_design"}, {"reproducible_experiment": case["experiment"]}
        )
        return {
            "id": case["id"], "category": "experiment", "expected_pass": case["expected_pass"],
            "predicted_pass": gate["passed"], "traceable": True, "issues": gate["issues"],
        }

    @staticmethod
    def _accuracy(results: list[dict]) -> float:
        return round(sum(item["predicted_pass"] == item["expected_pass"] for item in results) / max(len(results), 1), 4)


research_benchmark_service = ResearchBenchmarkService()
