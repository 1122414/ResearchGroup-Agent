from __future__ import annotations

import json
import hashlib
import math
import statistics
from datetime import datetime
from pathlib import Path

from ..storage.repositories import ResearchBriefRepository, RunRepository
from .artifact_manifest_service import artifact_manifest_service
from .run_artifact_service import run_artifact_service


class ResearchAnalysisService:
    """Deterministic adapters over hashed, user-supplied method data packages."""

    SCHEMA_VERSION = "research-method-data-v1"

    def analyze_for_task(self, task: dict, material_manifest: dict) -> dict:
        run_id = task.get("run_id")
        run = RunRepository.get_by_id(run_id) or {}
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        run_dir = run_artifact_service.run_dir(run, run_id).resolve()
        package = self._load_package(material_manifest, run_dir)
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family") or ""
        artifact = self.analyze_package(package, family, [
            record.get("sha256") for record in material_manifest.get("source_records") or [] if record.get("sha256")
        ])
        output_dir = run_dir / "analysis"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{task.get('id', 'task')}_analysis.json"
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        entry = artifact_manifest_service.register(run_dir, kind="method_analysis", path=str(path))
        return {
            **artifact, "artifact": str(path),
            "artifact_sha256": (entry.get("metadata") or {}).get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    @staticmethod
    def claims_for_artifact(artifact: dict) -> list[dict]:
        checks = artifact.get("method_checks") or {}
        if not checks or any(item.get("status") != "passed" for item in checks.values() if isinstance(item, dict)):
            return []
        findings = artifact.get("findings") or []
        finding = findings[0] if findings and isinstance(findings[0], dict) else {}
        family = artifact.get("family") or "unknown"
        statement = (
            f"在冻结的 {family} 材料与预声明分析程序下，确定性分析得到："
            f"{json.dumps(finding, ensure_ascii=False, sort_keys=True)[:520]}。"
            "该陈述仅描述当前已哈希材料，不外推到未观察总体或其他语境。"
        )
        return [{
            "statement": statement, "evidence_source_ids": [], "evidence_passage_ids": [],
            "relation": "supports", "confidence": 0.9,
            "provenance": {
                "method_family": family, "input_hashes": artifact.get("input_hashes") or [],
                "analysis_artifact": artifact.get("artifact"),
                "analysis_artifact_sha256": artifact.get("artifact_sha256"),
            },
        }]

    def analyze_package(self, package: dict, family: str, input_hashes: list[str]) -> dict:
        if not isinstance(package, dict) or package.get("schema_version") != self.SCHEMA_VERSION:
            return self._blocked(family, input_hashes, "method_data_package_missing_or_schema_invalid")
        if package.get("family") != family:
            return self._blocked(family, input_hashes, "method_data_package_family_mismatch")
        adapter = {
            "quantitative": self._numeric,
            "computational": self._numeric,
            "experimental": self._numeric,
            "qualitative": self._qualitative,
            "systematic_review": self._systematic_review,
            "humanities": self._humanities,
            "theoretical": self._theoretical,
            "design_science": self._design_science,
            "mixed_methods": self._mixed_methods,
        }.get(family)
        if not adapter:
            return self._blocked(family, input_hashes, "analysis_adapter_missing")
        findings, checks, limitations, procedure = adapter(package)
        return {
            "family": family, "input_hashes": input_hashes,
            "procedure": procedure, "findings": findings,
            "limitations": limitations or ["结论仅适用于冻结材料与预声明方法范围"],
            "method_checks": checks, "schema_version": self.SCHEMA_VERSION,
            "generated_at": datetime.now().isoformat(),
        }

    @staticmethod
    def _load_package(material_manifest: dict, run_dir: Path) -> dict:
        allowed_hashes = {
            str(item.get("sha256")) for item in material_manifest.get("source_records") or [] if item.get("sha256")
        }
        for record in material_manifest.get("source_records") or []:
            try:
                path = Path(str(record.get("path") or "")).resolve()
                if not path.is_file() or not path.is_relative_to(run_dir) or path.suffix.lower() != ".json":
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() not in allowed_hashes:
                    continue
                value = json.loads(path.read_text(encoding="utf-8"))
                package = value.get("method_data_package") if isinstance(value, dict) else None
                if isinstance(package, dict):
                    return package
                if isinstance(value, dict) and value.get("schema_version") == ResearchAnalysisService.SCHEMA_VERSION:
                    return value
            except (OSError, json.JSONDecodeError, RuntimeError):
                continue
        return {}

    def _numeric(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        family = package["family"]
        records = package.get("records") or []
        outcome = str(package.get("outcome_field") or "outcome")
        group_field = str(package.get("group_field") or "group")
        groups: dict[str, list[float]] = {}
        missing = 0
        for record in records if isinstance(records, list) else []:
            try:
                value = float(record.get(outcome))
                if not math.isfinite(value):
                    raise ValueError
                groups.setdefault(str(record.get(group_field)), []).append(value)
            except (AttributeError, TypeError, ValueError):
                missing += 1
        baseline = str(package.get("baseline_group") or "")
        treatment = str(package.get("treatment_group") or "")
        baseline_values, treatment_values = groups.get(baseline, []), groups.get(treatment, [])
        valid = bool(baseline_values and treatment_values)
        delta = statistics.mean(treatment_values) - statistics.mean(baseline_values) if valid else None
        se = None
        ci = None
        if len(baseline_values) >= 2 and len(treatment_values) >= 2:
            se = math.sqrt(
                statistics.variance(baseline_values) / len(baseline_values)
                + statistics.variance(treatment_values) / len(treatment_values)
            )
            ci = [delta - 1.96 * se, delta + 1.96 * se]
        median_delta = (
            statistics.median(treatment_values) - statistics.median(baseline_values) if valid else None
        )
        findings = [{
            "baseline": baseline, "treatment": treatment,
            "n_baseline": len(baseline_values), "n_treatment": len(treatment_values),
            "mean_difference": delta, "standard_error": se, "confidence_interval_95_normal": ci,
            "median_difference_sensitivity": median_delta, "missing_or_invalid_records": missing,
        }]
        checks = {}
        if family == "quantitative":
            checks = {
                "measurement_validity": self._check(bool(package.get("measurement_definition")), "冻结测量定义"),
                "missing_data": self._check(bool(package.get("missing_data_policy")), f"无效/缺失记录={missing}"),
                "effect_size": self._check(delta is not None, f"原始均值差={delta}"),
                "uncertainty": self._check(ci is not None, f"95% normal interval={ci}"),
                "robustness": self._check(median_delta is not None, f"中位数差敏感性={median_delta}"),
            }
        elif family == "computational":
            reproduction_runs = package.get("reproduction_runs") or []
            checks = {
                "baseline": self._check(bool(baseline_values), f"baseline={baseline}"),
                "data_split": self._check(bool(package.get("data_split")), str(package.get("data_split") or "")),
                "effect_size": self._check(delta is not None, f"原始均值差={delta}"),
                "uncertainty": self._check(ci is not None, f"95% normal interval={ci}"),
                "reproduction": self._check(len(reproduction_runs) >= 2 and len(set(reproduction_runs)) == 1, str(reproduction_runs)),
            }
        else:
            checks = {
                "controls": self._check(bool(package.get("control_description")), str(package.get("control_description") or "")),
                "protocol_deviations": self._check("protocol_deviations" in package, str(package.get("protocol_deviations"))),
                "effect_size": self._check(delta is not None, f"原始均值差={delta}"),
                "uncertainty": self._check(ci is not None, f"95% normal interval={ci}"),
                "raw_record_audit": self._check(bool(records), f"原始记录数={len(records)}"),
            }
        return findings, checks, list(package.get("limitations") or []), "标准库确定性分组统计；未用 LLM 生成或修改数值"

    def _qualitative(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        segments = package.get("coded_segments") or []
        materials = package.get("source_materials") or []
        material_ids = {str(item.get("id")) for item in materials if item.get("id")}
        segment_ids = {str(item.get("id")) for item in segments if item.get("id")}
        defined_codes = {
            str(item.get("code")) for item in package.get("codebook") or []
            if item.get("code") and item.get("definition")
        }
        used_codes = {
            str(code) for segment in segments if isinstance(segment, dict)
            for code in segment.get("codes") or []
        }
        counts: dict[str, int] = {}
        source_ids: set[str] = set()
        for segment in segments if isinstance(segments, list) else []:
            source_ids.add(str(segment.get("source_id") or ""))
            for code in segment.get("codes") or []:
                counts[str(code)] = counts.get(str(code), 0) + 1
        checks = {
            "material_traceability": self._check(
                bool(materials) and all(
                    item.get("id") and item.get("locator") and self._valid_hash(item.get("sha256"))
                    for item in materials
                ) and all(
                    str(item.get("source_id")) in material_ids and self._valid_hash(item.get("text_sha256"))
                    for item in segments
                ),
                f"原始材料={len(materials)}，编码片段={len(segments)}",
            ),
            "codebook": self._check(bool(defined_codes), f"有效codebook条目={len(defined_codes)}"),
            "coding_coverage": self._check(
                bool(segments) and len(segment_ids) == len(segments) and used_codes <= defined_codes,
                f"已定义代码={sorted(defined_codes)}，已使用代码={sorted(used_codes)}",
            ),
            "audit_trail": self._check(
                isinstance(package.get("audit_trail"), list) and bool(package.get("audit_trail"))
                and all(isinstance(item, dict) and item.get("coder_id") and item.get("action") for item in package.get("audit_trail")),
                f"结构化审计事件={len(package.get('audit_trail') or [])}",
            ),
            "negative_cases": self._check(
                bool(package.get("negative_cases"))
                and set(map(str, package.get("negative_cases") or [])) <= segment_ids,
                f"负例数={len(package.get('negative_cases') or [])}",
            ),
            "reflexivity": self._check(bool(package.get("reflexivity_statement")), str(package.get("reflexivity_statement") or "")),
            "saturation_or_information_power": self._check(bool(package.get("saturation_assessment")), str(package.get("saturation_assessment") or "")),
        }
        findings = [{"code_frequencies": counts, "coded_segment_count": len(segments), "source_count": len(source_ids - {""})}]
        return findings, checks, list(package.get("limitations") or []), "对用户提供的编码片段做确定性计数并审计质性质量记录"

    def _systematic_review(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        records = package.get("screening_records") or []
        studies = package.get("studies") or []
        study_ids = {str(item.get("id")) for item in studies if item.get("id")}
        decisions: dict[str, set[str]] = {}
        flow: dict[str, int] = {}
        for item in records if isinstance(records, list) else []:
            study_id = str(item.get("study_id") or "")
            decisions.setdefault(study_id, set()).add(str(item.get("reviewer") or ""))
            key = f"{item.get('stage')}:{item.get('decision')}"
            flow[key] = flow.get(key, 0) + 1
        dual = bool(decisions) and all(len(reviewers - {""}) >= 2 for reviewers in decisions.values())
        dedup = package.get("deduplication_log") or {}
        input_count = int(dedup.get("input_count") or 0) if isinstance(dedup, dict) else 0
        deduplicated_count = int(dedup.get("deduplicated_count") or 0) if isinstance(dedup, dict) else 0
        duplicates = (dedup.get("duplicate_ids") or []) if isinstance(dedup, dict) else []
        included_ids = {
            str(item.get("study_id")) for item in records
            if str(item.get("decision") or "").lower() == "include"
        }
        appraisal_ids = {
            str(item.get("study_id")) for item in package.get("quality_appraisals") or []
            if item.get("rating")
        }
        checks = {
            "study_identity": self._check(
                bool(studies) and all(
                    item.get("id") and item.get("title") and (item.get("doi") or item.get("url"))
                    for item in studies
                ), f"可识别研究={len(studies)}",
            ),
            "deduplication": self._check(
                input_count >= deduplicated_count > 0 and input_count - deduplicated_count == len(duplicates),
                f"输入={input_count}，去重后={deduplicated_count}，重复={len(duplicates)}",
            ),
            "screening_integrity": self._check(
                bool(records) and set(decisions) <= study_ids,
                f"筛选研究={len(decisions)}，已登记研究={len(study_ids)}",
            ),
            "dual_screening": self._check(dual, f"双人记录覆盖={sum(len(v - {''}) >= 2 for v in decisions.values())}/{len(decisions)}"),
            "quality_appraisal": self._check(bool(package.get("quality_appraisals")), f"评价数={len(package.get('quality_appraisals') or [])}"),
            "appraisal_coverage": self._check(
                bool(included_ids) and included_ids <= appraisal_ids,
                f"纳入={sorted(included_ids)}，已评价={sorted(appraisal_ids)}",
            ),
            "flow_accounting": self._check(bool(flow), json.dumps(flow, ensure_ascii=False)),
            "synthesis_method": self._check(bool(package.get("synthesis_method")), str(package.get("synthesis_method") or "")),
        }
        return [{"screening_flow": flow, "unique_studies": len(decisions)}], checks, list(package.get("limitations") or []), "确定性核算去重、双人筛选、质量评价与研究流转"

    def _humanities(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        sources = package.get("primary_sources") or []
        source_ids = {str(item.get("id")) for item in sources if item.get("id")}
        interpretations = package.get("interpretations") or []
        counterarguments = package.get("counterarguments") or []
        interpretation_links_valid = bool(interpretations) and all(
            isinstance(item, dict) and item.get("statement") and item.get("source_ids")
            and set(map(str, item.get("source_ids") or [])) <= source_ids
            for item in interpretations
        )
        checks = {
            "material_integrity": self._check(
                bool(sources) and all(
                    item.get("id") and item.get("locator") and self._valid_hash(item.get("sha256"))
                    for item in sources
                ), f"哈希一手来源={len(sources)}",
            ),
            "primary_source_criticism": self._check(bool(sources) and all(item.get("criticism") for item in sources), f"一手来源数={len(sources)}"),
            "contextualization": self._check(bool(package.get("historical_or_textual_context")), str(package.get("historical_or_textual_context") or "")),
            "interpretive_framework": self._check(bool(package.get("interpretive_framework")), str(package.get("interpretive_framework") or "")),
            "interpretation_traceability": self._check(
                interpretation_links_valid, f"可追溯解释={len(interpretations)}",
            ),
            "counterarguments": self._check(
                bool(counterarguments) and all(
                    isinstance(item, dict) and item.get("statement")
                    and set(map(str, item.get("source_ids") or [])) <= source_ids
                    for item in counterarguments
                ), f"反论证数={len(counterarguments)}",
            ),
            "source_triangulation": self._check(len({item.get("provenance") for item in sources if item.get("provenance")}) >= 2, "独立出处至少2类"),
        }
        findings = [{"primary_source_count": len(sources), "interpretations": interpretations}]
        return findings, checks, list(package.get("limitations") or []), "核对一手来源批判、语境、解释框架、反论证和多出处互证"

    def _theoretical(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        steps = package.get("proof_steps") or []
        ids = {str(item.get("id")) for item in steps if item.get("id")}
        dependencies_valid = all(set(map(str, item.get("depends_on") or [])) <= ids for item in steps)
        acyclic = self._acyclic(steps)
        checks = {
            "definitions": self._check(bool(package.get("definitions")), f"定义数={len(package.get('definitions') or [])}"),
            "assumptions": self._check("assumptions" in package, f"假设数={len(package.get('assumptions') or [])}"),
            "dependency_graph": self._check(bool(steps) and dependencies_valid and acyclic, f"步骤数={len(steps)}, acyclic={acyclic}"),
            "proof_or_derivation_check": self._check(bool(steps) and all(item.get("justification") for item in steps), "每步均需 justification"),
            "counterexample_search": self._check(bool(package.get("counterexample_search")), str(package.get("counterexample_search") or "")),
        }
        return [{"proof_step_count": len(steps), "dependency_graph_acyclic": acyclic}], checks, list(package.get("limitations") or []), "确定性检查定义、假设、证明依赖、逐步依据与反例搜索记录"

    def _design_science(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        checks = {
            "requirements_traceability": self._check(bool(package.get("requirements_trace")), "需求到artifact映射"),
            "artifact_description": self._check(bool(package.get("artifact")), "artifact已描述"),
            "evaluation": self._check(bool(package.get("evaluations")), f"评价数={len(package.get('evaluations') or [])}"),
            "alternatives": self._check(bool(package.get("alternatives")), f"备选数={len(package.get('alternatives') or [])}"),
            "limitations": self._check(bool(package.get("limitations")), "局限已声明"),
        }
        return [{"artifact": package.get("artifact"), "evaluations": package.get("evaluations") or []}], checks, list(package.get("limitations") or []), "检查需求追溯、artifact、评价、替代方案与局限"

    def _mixed_methods(self, package: dict) -> tuple[list[dict], dict, list[str], str]:
        components = package.get("component_results") or []
        checks = {
            "component_quality": self._check(len(components) >= 2 and all(item.get("quality_passed") for item in components), f"组件数={len(components)}"),
            "integration_design": self._check(bool(package.get("integration_design")), str(package.get("integration_design") or "")),
            "joint_display": self._check(bool(package.get("joint_display")), f"联合展示项={len(package.get('joint_display') or [])}"),
            "discordance_analysis": self._check("discordances" in package, f"不一致数={len(package.get('discordances') or [])}"),
            "meta_inference": self._check(bool(package.get("meta_inferences")), f"整合推论数={len(package.get('meta_inferences') or [])}"),
        }
        return [{"component_count": len(components), "meta_inferences": package.get("meta_inferences") or []}], checks, list(package.get("limitations") or []), "审计组成方法质量、整合设计、联合展示、不一致和整合推论"

    @staticmethod
    def _check(passed: bool, evidence: str) -> dict:
        return {"status": "passed" if passed else "failed", "evidence": evidence or "未提供"}

    @staticmethod
    def _valid_hash(value) -> bool:
        digest = str(value or "").lower()
        return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)

    @staticmethod
    def _acyclic(steps: list[dict]) -> bool:
        graph = {str(item.get("id")): list(map(str, item.get("depends_on") or [])) for item in steps if item.get("id")}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return False
            if node in visited:
                return True
            visiting.add(node)
            if any(not visit(parent) for parent in graph.get(node, [])):
                return False
            visiting.remove(node)
            visited.add(node)
            return True

        return all(visit(node) for node in graph)

    @staticmethod
    def _blocked(family: str, input_hashes: list[str], reason: str) -> dict:
        return {
            "family": family, "input_hashes": input_hashes, "procedure": "blocked",
            "findings": [{"status": "blocked", "reason": reason}],
            "limitations": [reason], "method_checks": {},
            "schema_version": ResearchAnalysisService.SCHEMA_VERSION,
            "generated_at": datetime.now().isoformat(),
        }


research_analysis_service = ResearchAnalysisService()
