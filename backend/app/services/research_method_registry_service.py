from __future__ import annotations


class ResearchMethodRegistryService:
    """Method-specific work-package contracts without discipline keyword hard-coding."""

    ANALYSIS_CHECKS = {
        "quantitative": {"measurement_validity", "missing_data", "effect_size", "uncertainty", "robustness"},
        "computational": {"baseline", "data_split", "effect_size", "uncertainty", "reproduction"},
        "experimental": {"controls", "protocol_deviations", "effect_size", "uncertainty", "raw_record_audit"},
        "qualitative": {
            "material_traceability", "codebook", "coding_coverage", "audit_trail",
            "negative_cases", "reflexivity", "saturation_or_information_power",
        },
        "systematic_review": {
            "study_identity", "deduplication", "screening_integrity", "dual_screening",
            "quality_appraisal", "appraisal_coverage", "flow_accounting", "synthesis_method",
        },
        "humanities": {
            "material_integrity", "primary_source_criticism", "contextualization",
            "interpretive_framework", "interpretation_traceability", "counterarguments", "source_triangulation",
        },
        "theoretical": {"definitions", "assumptions", "dependency_graph", "proof_or_derivation_check", "counterexample_search"},
        "design_science": {"requirements_traceability", "artifact_description", "evaluation", "alternatives", "limitations"},
        "mixed_methods": {"component_quality", "integration_design", "joint_display", "discordance_analysis", "meta_inference"},
    }

    def requirements_for(self, brief: dict) -> dict:
        profile = brief.get("methodology_profile") or {}
        family = brief.get("methodology_family") or profile.get("family") or ""
        return {
            "family": family,
            "research_design": {
                "required_object": "method_package",
                "required_fields": [
                    "family", "study_design", "sampling_or_corpus_plan", "data_or_material_protocol",
                    "analysis_plan", "quality_controls", "stopping_rule", "deviation_policy",
                ],
            },
            "data_acquisition": {
                "required_object": "material_manifest",
                "required_fields": ["frozen_at", "collection_log", "source_records", "completeness"],
                "record_fields": [
                    "id", "path", "sha256", "provenance", "authorization_evidence", "size_bytes",
                ],
            },
            "result_analysis": {
                "required_object": "analysis_artifact",
                "required_fields": [
                    "family", "input_hashes", "procedure", "findings", "limitations", "method_checks",
                ],
                "required_method_checks": sorted(self.ANALYSIS_CHECKS.get(family, set())),
            },
        }

    def validate_task(self, task: dict, latest: dict, brief: dict) -> list[str]:
        task_type = task.get("task_type")
        requirements = self.requirements_for(brief)
        if task_type not in {"research_design", "data_acquisition", "result_analysis"}:
            return []
        # Legacy computational result_analysis is already protected by the
        # reproducible-experiment gate; apply this registry after generic work packages exist.
        if task_type == "result_analysis" and requirements["family"] == "computational" and latest.get(
            "reproducible_experiment"
        ):
            return []
        spec = requirements[task_type]
        payload = latest.get(spec["required_object"])
        if not isinstance(payload, dict):
            return [f"{spec['required_object']}_missing"]
        issues = [f"{spec['required_object']}.{field}_missing" for field in spec["required_fields"] if not payload.get(field)]
        if payload.get("family") and payload.get("family") != requirements["family"]:
            issues.append("methodology_family_mismatch")
        if task_type == "research_design":
            controls = payload.get("quality_controls")
            if not isinstance(controls, list) or len(controls) < 2:
                issues.append("method_package.quality_controls_insufficient")
        elif task_type == "data_acquisition":
            records = payload.get("source_records")
            if not isinstance(records, list) or not records:
                issues.append("material_manifest.source_records_empty")
            for index, record in enumerate(records if isinstance(records, list) else []):
                for field in spec["record_fields"]:
                    if record.get(field) in (None, ""):
                        issues.append(f"material_manifest.source_records[{index}].{field}_missing")
                digest = str(record.get("sha256") or "")
                if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
                    issues.append(f"material_manifest.source_records[{index}].sha256_invalid")
            if payload.get("completeness") != "complete":
                issues.append("material_manifest_not_complete")
        else:
            checks = payload.get("method_checks") or {}
            for check in spec["required_method_checks"]:
                result = checks.get(check)
                if not isinstance(result, dict) or result.get("status") not in {"passed", "not_applicable"}:
                    issues.append(f"analysis_artifact.method_checks.{check}_not_passed")
                elif not str(result.get("evidence") or "").strip():
                    issues.append(f"analysis_artifact.method_checks.{check}_evidence_missing")
            hashes = payload.get("input_hashes")
            if not isinstance(hashes, list) or not hashes:
                issues.append("analysis_artifact.input_hashes_empty")
        return list(dict.fromkeys(issues))


research_method_registry_service = ResearchMethodRegistryService()
