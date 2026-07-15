from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from ..storage.repositories import (
    EvidenceRepository,
    ExperimentResultRepository,
    LLMUsageRepository,
    OutputRepository,
    ResearchBriefRepository,
    ResearchClaimRepository,
    RunRepository,
    TaskRepository,
)
from .artifact_manifest_service import artifact_manifest_service
from .grounding_audit_service import grounding_audit_service
from .scientific_quality_gate_service import scientific_quality_gate_service


class CrossDisciplinaryThesisBenchmarkService:
    """Audit real completed runs; fixture-only success can never satisfy this benchmark."""

    REQUIRED_PARADIGMS = {
        "computational_engineering",
        "social_science_quantitative",
        "systematic_review",
        "humanities_or_theoretical",
        "qualitative_or_mixed",
    }
    REQUIRED_TASK_GROUPS = (
        {"literature_survey"},
        {"research_design", "experiment_design"},
        {"data_acquisition", "experiment_design"},
        {"result_analysis"},
        {"thesis_chapter"},
        {"report_writing"},
    )
    RESERVED_HOSTS = {
        "localhost", "127.0.0.1", "0.0.0.0",
        "example.com", "example.org", "example.net",
    }

    def run(self, registry_path: Path) -> dict:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        specs = registry.get("projects") or []
        results = [self.audit_project(spec) for spec in specs]
        paradigms = [str(item.get("paradigm") or "") for item in specs]
        run_ids = [str(item.get("run_id") or "") for item in specs if item.get("run_id")]
        passed = [item for item in results if item["passed"]]
        global_issues: list[str] = []
        missing = sorted(self.REQUIRED_PARADIGMS - set(paradigms))
        extra = sorted(set(paradigms) - self.REQUIRED_PARADIGMS)
        if missing:
            global_issues.append("missing_paradigms:" + ",".join(missing))
        if extra:
            global_issues.append("unsupported_paradigms:" + ",".join(extra))
        if len(specs) != len(self.REQUIRED_PARADIGMS) or len(set(paradigms)) != len(paradigms):
            global_issues.append("registry_must_contain_each_required_paradigm_once")
        if len(run_ids) != len(set(run_ids)):
            global_issues.append("duplicate_run_ids")
        passed_families = {item.get("method_family") for item in passed if item.get("method_family")}
        passed_fields = {item.get("broad_field") for item in passed if item.get("broad_field")}
        if len(passed) == len(self.REQUIRED_PARADIGMS) and len(passed_families) < 4:
            global_issues.append("insufficient_method_family_diversity")
        if len(passed) == len(self.REQUIRED_PARADIGMS) and len(passed_fields) < 3:
            global_issues.append("insufficient_discipline_diversity")
        return {
            "benchmark": registry.get("name") or "cross_disciplinary_master_thesis",
            "passed": len(passed) == len(self.REQUIRED_PARADIGMS) and not global_issues,
            "completed_projects": len(passed),
            "required_projects": len(self.REQUIRED_PARADIGMS),
            "global_issues": global_issues,
            "projects": results,
            "policy": "five_real_runs_all_checks_required",
        }

    def audit_project(self, spec: dict, snapshot: dict | None = None) -> dict:
        issues: list[str] = []
        run_id = str(spec.get("run_id") or "").strip()
        allowed_families = set(spec.get("allowed_method_families") or [])
        if not run_id:
            return self._result(spec, issues=["run_id_not_assigned"])
        try:
            data = snapshot or self._load_snapshot(run_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._result(spec, issues=[f"snapshot_unreadable:{type(exc).__name__}"])

        run = data.get("run") or {}
        brief = data.get("brief") or {}
        tasks = data.get("tasks") or []
        evidence = data.get("evidence") or {}
        outputs = data.get("outputs") or []
        usages = data.get("usages") or []
        experiments = data.get("experiments") or []
        claims = data.get("claims") or []
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
        discipline = brief.get("discipline") or {}

        if run.get("id") != run_id or run.get("status") != "completed":
            issues.append("run_not_completed")
        if allowed_families and family not in allowed_families:
            issues.append(f"method_family_not_allowed:{family or 'missing'}")
        if (brief.get("thesis_requirements") or {}).get("status") != "confirmed":
            issues.append("thesis_requirements_unconfirmed")
        ethics = brief.get("ethics_plan") or {}
        if ethics.get("required") and ethics.get("status") != "approved":
            issues.append("ethics_approval_missing")
        if any(
            item.get("required") and item.get("status") != "available"
            for item in brief.get("resource_plan") or []
        ):
            issues.append("required_resource_unavailable")

        self._audit_llm_usage(usages, issues)
        self._audit_tasks(tasks, brief, issues)
        self._audit_sources(evidence, brief, issues)

        run_dir = self._owned_run_dir(run, run_id, issues)
        report = self._audit_artifacts(run_dir, outputs, issues) if run_dir else ""
        self._audit_method_artifacts(run_dir, data.get("manifest") or {}, experiments, family, issues)
        self._audit_quality(outputs, data, report, issues)

        supported = [item for item in claims if item.get("status") == "supported"]
        minimum_claims = int((brief.get("thesis_requirements") or {}).get("minimum_supported_claims") or 1)
        if len(supported) < minimum_claims:
            issues.append(f"insufficient_supported_claims:{len(supported)}/{minimum_claims}")
        return self._result(
            spec, issues=issues, method_family=family,
            broad_field=discipline.get("broad_field"), run_id=run_id,
        )

    @staticmethod
    def _load_snapshot(run_id: str) -> dict:
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise ValueError("run_not_found")
        run_dir = Path(str(run.get("artifact_dir") or ""))
        return {
            "run": run,
            "brief": ResearchBriefRepository.get_by_run(run_id) or {},
            "tasks": TaskRepository.get_all(run_id=run_id),
            "evidence": EvidenceRepository.get_by_run(run_id),
            "outputs": OutputRepository.get_by_run(run_id),
            "usages": LLMUsageRepository.get_by_run(run_id),
            "experiments": ExperimentResultRepository.get_by_run(run_id),
            "claims": ResearchClaimRepository.get_by_run(run_id),
            "manifest": artifact_manifest_service.read(run_dir),
        }

    @staticmethod
    def _audit_llm_usage(usages: list[dict], issues: list[str]) -> None:
        if not usages:
            issues.append("llm_usage_missing")
            return
        if any(
            str(item.get("provider") or "").lower() in {"", "mock"}
            or "mock" in str(item.get("model") or "").lower()
            or not item.get("success")
            for item in usages
        ):
            issues.append("mock_or_failed_llm_usage")

    def _audit_tasks(self, tasks: list[dict], brief: dict, issues: list[str]) -> None:
        completed_types = {item.get("task_type") for item in tasks if item.get("status") == "completed"}
        for alternatives in self.REQUIRED_TASK_GROUPS:
            if not completed_types.intersection(alternatives):
                issues.append("missing_completed_task:" + "|".join(sorted(alternatives)))
        expected_chapters = len((brief.get("thesis_requirements") or {}).get("required_chapters") or [])
        actual_chapters = sum(
            item.get("status") == "completed" and item.get("task_type") == "thesis_chapter"
            for item in tasks
        )
        if actual_chapters < expected_chapters:
            issues.append(f"incomplete_thesis_chapters:{actual_chapters}/{expected_chapters}")
        for task in tasks:
            if task.get("status") != "completed" or task.get("task_type") == "report_writing":
                continue
            review = ((task.get("review_result") or {}).get("quality_gates") or {})
            independent = (review.get("layers") or {}).get("independent_review") or {}
            reviewer = str(independent.get("reviewer") or "").lower()
            if (
                not review.get("passed") or not independent.get("passed")
                or independent.get("simulation") or not reviewer
                or "mock" in reviewer or "not_called" in reviewer
            ):
                issues.append(f"unverified_independent_review:{task.get('id')}")

    def _audit_sources(self, evidence: dict, brief: dict, issues: list[str]) -> None:
        excerpts = evidence.get("excerpts") or []
        passage_sources = {
            item.get("source_id") for item in excerpts
            if item.get("excerpt_type") not in {"metadata_only", "summary"} and str(item.get("excerpt") or "").strip()
        }
        eligible = [
            source for source in evidence.get("sources") or []
            if (source.get("metadata") or {}).get("citation_eligible")
            and source.get("id") in passage_sources and self._external_identifier(source)
        ]
        minimum = int((brief.get("thesis_requirements") or {}).get("minimum_references") or 20)
        if len({item.get("id") for item in eligible}) < minimum:
            issues.append(f"insufficient_verified_external_sources:{len(eligible)}/{minimum}")

    def _external_identifier(self, source: dict) -> bool:
        doi = str(source.get("doi") or "").strip().lower()
        if doi.startswith("10.") and "/" in doi:
            return True
        parsed = urlparse(str(source.get("url") or ""))
        host = (parsed.hostname or "").lower()
        return parsed.scheme in {"http", "https"} and bool(host) and host not in self.RESERVED_HOSTS

    @staticmethod
    def _owned_run_dir(run: dict, run_id: str, issues: list[str]) -> Path | None:
        raw_path = str(run.get("artifact_dir") or "").strip()
        if not raw_path:
            issues.append("artifact_dir_missing")
            return None
        path = Path(raw_path).resolve()
        try:
            if not path.is_dir() or (path / ".run_id").read_text(encoding="utf-8").strip() != run_id:
                issues.append("artifact_dir_not_owned_by_run")
                return None
        except OSError:
            issues.append("artifact_dir_not_owned_by_run")
            return None
        return path

    def _audit_artifacts(self, run_dir: Path, outputs: list[dict], issues: list[str]) -> str:
        report_outputs = [item for item in outputs if item.get("output_type") == "final_report"]
        if not report_outputs:
            issues.append("final_report_output_missing")
            return ""
        report = str(report_outputs[-1].get("content") or "")
        report_path = run_dir / "final_report.md"
        if not report_path.is_file() or report_path.read_text(encoding="utf-8") != report:
            issues.append("final_report_file_mismatch")
            return report
        if "`master_thesis`" not in report:
            issues.append("master_thesis_delivery_marker_missing")
        manifest = artifact_manifest_service.read(run_dir)
        if manifest.get("run_id") != (run_dir / ".run_id").read_text(encoding="utf-8").strip():
            issues.append("artifact_manifest_run_mismatch")
        if not self._registered_hash_valid(run_dir, manifest, report_path, {"report"}):
            issues.append("final_report_hash_unregistered_or_mismatch")
        input_entries = [item for item in manifest.get("artifacts") or [] if item.get("kind") == "input"]
        if not input_entries or not all(self._entry_hash_valid(run_dir, item) for item in input_entries):
            issues.append("real_input_artifact_missing_or_invalid")
        return report

    def _audit_method_artifacts(
        self, run_dir: Path | None, manifest: dict, experiments: list[dict], family: str | None, issues: list[str]
    ) -> None:
        if not run_dir:
            return
        method_entries = [
            item for item in manifest.get("artifacts") or []
            if item.get("kind") in {"method_analysis", "experiment"}
        ]
        valid_method_entries = [item for item in method_entries if self._entry_hash_valid(run_dir, item)]
        publishable = [item for item in experiments if (item.get("metrics") or {}).get("publishable") is True]
        if not valid_method_entries and not publishable:
            issues.append("method_artifact_missing_or_invalid")
        if family in {"computational", "experimental"} and not publishable:
            issues.append("publishable_experiment_missing")

    def _audit_quality(self, outputs: list[dict], data: dict, report: str, issues: list[str]) -> None:
        quality_outputs = [item for item in outputs if item.get("output_type") == "scientific_quality_gate"]
        if not quality_outputs:
            issues.append("scientific_quality_gate_output_missing")
            return
        try:
            stored = json.loads(quality_outputs[-1].get("content") or "{}")
        except json.JSONDecodeError:
            issues.append("scientific_quality_gate_output_invalid")
            return
        if not (
            stored.get("passed") and stored.get("master_thesis_ready")
            and stored.get("deliverable_level") == "master_thesis"
            and (stored.get("thesis_quality") or {}).get("passed")
            and not stored.get("master_thesis_blockers")
        ):
            issues.append("stored_master_thesis_gate_failed")
        if not report:
            return
        recomputed = self._recompute_quality(data, report)
        if not recomputed.get("master_thesis_ready") or not (recomputed.get("thesis_quality") or {}).get("passed"):
            issues.append("recomputed_master_thesis_gate_failed")

    @staticmethod
    def _recompute_quality(data: dict, report: str) -> dict:
        audit = grounding_audit_service.audit_report(report)
        run_id = (data.get("run") or {}).get("id")
        return scientific_quality_gate_service.evaluate_report(run_id, report, audit)

    def _registered_hash_valid(self, run_dir: Path, manifest: dict, path: Path, kinds: set[str]) -> bool:
        resolved = path.resolve()
        return any(
            item.get("kind") in kinds
            and Path(str(item.get("path") or "")).resolve() == resolved
            and self._entry_hash_valid(run_dir, item)
            for item in manifest.get("artifacts") or []
        )

    @staticmethod
    def _entry_hash_valid(run_dir: Path, entry: dict) -> bool:
        try:
            path = Path(str(entry.get("path") or "")).resolve()
            expected = (entry.get("metadata") or {}).get("sha256")
            return (
                path.is_file() and path.is_relative_to(run_dir)
                and bool(expected) and hashlib.sha256(path.read_bytes()).hexdigest() == expected
            )
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def _result(
        spec: dict, *, issues: list[str], method_family: str | None = None,
        broad_field: str | None = None, run_id: str | None = None,
    ) -> dict:
        return {
            "id": spec.get("id"), "paradigm": spec.get("paradigm"),
            "run_id": run_id or spec.get("run_id") or None,
            "passed": not issues, "issues": issues,
            "method_family": method_family, "broad_field": broad_field,
        }


cross_disciplinary_thesis_benchmark_service = CrossDisciplinaryThesisBenchmarkService()
