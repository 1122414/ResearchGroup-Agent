from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import ResearchBriefRepository, RunRepository
from .run_artifact_service import run_artifact_service


class MethodMaterialAnalysisService:
    """Create traceable qualitative/humanities packages from hashed raw materials."""

    SUPPORTED = {"qualitative", "humanities"}

    async def build_for_task(self, task: dict, manifest: dict) -> dict | None:
        run_id = task.get("run_id")
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
        if family not in self.SUPPORTED or not self._processing_allowed(brief):
            return None
        run = RunRepository.get_by_id(run_id) or {}
        run_dir = run_artifact_service.run_dir(run, run_id).resolve()
        materials, segments = self._materials(manifest, run_dir)
        if not materials or not segments or self._contains_prebuilt_package(manifest, run_dir):
            return None
        payload = {
            "family": family,
            "research_question": brief.get("research_question"),
            "methodology_profile": brief.get("methodology_profile"),
            "materials": materials,
            "segments": segments,
        }
        candidate = await self._ask("analyst", family, payload, task)
        review = await self._ask("reviewer", family, {**payload, "candidate_analysis": candidate}, task)
        if family == "qualitative":
            return self._qualitative_package(candidate, review, materials, segments)
        return self._humanities_package(candidate, review, materials)

    async def _ask(self, stage: str, family: str, payload: dict, task: dict) -> dict:
        prompt_name = "method_material_analyst" if stage == "analyst" else "method_material_reviewer"
        schema = self._schema(family, stage)
        raw = await create_llm_provider().generate(
            prompt=f"{prompt_loader.load(prompt_name)}\n\n输入：\n{json.dumps(payload, ensure_ascii=False)}",
            schema=schema,
            role="graduate" if stage == "analyst" else "independent_reviewer",
            run_id=task.get("run_id"), task_id=task.get("id"),
        )
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _schema(family: str, stage: str) -> dict:
        if stage == "reviewer":
            return {
                "type": "object", "properties": {
                    "approved": {"type": "boolean"}, "feedback": {"type": "string"},
                    "checked_ids": {"type": "array", "items": {"type": "string"}},
                }, "required": ["approved", "feedback", "checked_ids"],
            }
        if family == "qualitative":
            return {
                "type": "object", "properties": {
                    "codebook": {"type": "array", "items": {"type": "object"}},
                    "coding": {"type": "array", "items": {"type": "object"}},
                    "negative_case_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "reflexivity_statement": {"type": "string"},
                    "saturation_assessment": {"type": "string"},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                }, "required": [
                    "codebook", "coding", "negative_case_segment_ids", "reflexivity_statement",
                    "saturation_assessment", "limitations",
                ],
            }
        return {
            "type": "object", "properties": {
                "source_criticisms": {"type": "array", "items": {"type": "object"}},
                "historical_or_textual_context": {"type": "string"},
                "interpretive_framework": {"type": "string"},
                "interpretations": {"type": "array", "items": {"type": "object"}},
                "counterarguments": {"type": "array", "items": {"type": "object"}},
                "limitations": {"type": "array", "items": {"type": "string"}},
            }, "required": [
                "source_criticisms", "historical_or_textual_context", "interpretive_framework",
                "interpretations", "counterarguments", "limitations",
            ],
        }

    def _qualitative_package(
        self, candidate: dict, review: dict, materials: list[dict], segments: list[dict],
    ) -> dict:
        segment_map = {item["id"]: item for item in segments}
        codebook = [
            {"code": str(item.get("code") or "").strip(), "definition": str(item.get("definition") or "").strip()}
            for item in candidate.get("codebook") or [] if isinstance(item, dict)
            and item.get("code") and item.get("definition")
        ]
        allowed_codes = {item["code"] for item in codebook}
        coded = []
        for item in candidate.get("coding") or []:
            segment = segment_map.get(str(item.get("segment_id") or "")) if isinstance(item, dict) else None
            codes = [str(code) for code in item.get("codes") or [] if str(code) in allowed_codes] if segment else []
            if segment and codes:
                coded.append({
                    "id": segment["id"], "source_id": segment["source_id"],
                    "text_sha256": segment["text_sha256"], "codes": list(dict.fromkeys(codes)),
                })
        coded_ids = {item["id"] for item in coded}
        checked = set(map(str, review.get("checked_ids") or []))
        return {
            "schema_version": "research-method-data-v1", "family": "qualitative",
            "source_materials": [{key: item[key] for key in ("id", "locator", "sha256")} for item in materials],
            "coded_segments": coded, "codebook": codebook,
            "audit_trail": [
                {"coder_id": "method_analyst", "action": "grounded first-pass coding"},
                {"coder_id": "independent_method_reviewer", "action": str(review.get("feedback") or "review failed")},
            ],
            "negative_cases": [
                item for item in map(str, candidate.get("negative_case_segment_ids") or []) if item in coded_ids
            ],
            "reflexivity_statement": candidate.get("reflexivity_statement"),
            "saturation_assessment": candidate.get("saturation_assessment"),
            "independent_review": {
                "approved": review.get("approved") is True,
                "checked_ids": sorted(checked & coded_ids), "feedback": review.get("feedback"),
            },
            "limitations": candidate.get("limitations") or ["模型辅助编码需由责任研究者复核"],
        }

    def _humanities_package(self, candidate: dict, review: dict, materials: list[dict]) -> dict:
        source_ids = {item["id"] for item in materials}
        criticisms = {
            str(item.get("source_id")): str(item.get("criticism") or "").strip()
            for item in candidate.get("source_criticisms") or [] if isinstance(item, dict)
            and str(item.get("source_id")) in source_ids and item.get("criticism")
        }
        def grounded(items: list) -> list[dict]:
            return [
                {"statement": str(item.get("statement") or "").strip(),
                 "source_ids": sorted(set(map(str, item.get("source_ids") or [])) & source_ids)}
                for item in items if isinstance(item, dict) and item.get("statement")
                and set(map(str, item.get("source_ids") or [])) & source_ids
            ]
        checked = set(map(str, review.get("checked_ids") or []))
        return {
            "schema_version": "research-method-data-v1", "family": "humanities",
            "primary_sources": [{
                "id": item["id"], "locator": item["locator"], "sha256": item["sha256"],
                "provenance": item.get("declared_provenance") or item["locator"],
                "criticism": criticisms.get(item["id"], ""),
            } for item in materials],
            "historical_or_textual_context": candidate.get("historical_or_textual_context"),
            "interpretive_framework": candidate.get("interpretive_framework"),
            "interpretations": grounded(candidate.get("interpretations") or []),
            "counterarguments": grounded(candidate.get("counterarguments") or []),
            "independent_review": {
                "approved": review.get("approved") is True,
                "checked_ids": sorted(checked & source_ids), "feedback": review.get("feedback"),
            },
            "limitations": candidate.get("limitations") or ["模型辅助解释需由责任研究者复核"],
        }

    def _materials(self, manifest: dict, run_dir: Path) -> tuple[list[dict], list[dict]]:
        materials, segments = [], []
        for record in manifest.get("source_records") or []:
            try:
                path = Path(str(record.get("path") or "")).resolve()
                if not path.is_file() or not path.is_relative_to(run_dir):
                    continue
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != record.get("sha256"):
                    continue
                text = raw.decode("utf-8", errors="replace").strip()
            except (OSError, RuntimeError):
                continue
            if not text:
                continue
            material = {
                "id": str(record.get("id")), "locator": str(path.relative_to(run_dir)),
                "sha256": record["sha256"], "declared_provenance": record.get("declared_provenance"),
            }
            materials.append(material)
            for chunk in self._chunks(text[:12000], 900):
                segment_id = f"seg_{len(segments) + 1:04d}"
                segments.append({
                    "id": segment_id, "source_id": material["id"], "locator": material["locator"],
                    "text": chunk, "text_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                })
                if len(segments) >= 24:
                    break
            if len(segments) >= 24:
                break
        return materials, segments

    @staticmethod
    def _chunks(text: str, size: int) -> list[str]:
        return [text[start:start + size].strip() for start in range(0, len(text), size) if text[start:start + size].strip()]

    @staticmethod
    def _contains_prebuilt_package(manifest: dict, run_dir: Path) -> bool:
        for record in manifest.get("source_records") or []:
            try:
                path = Path(str(record.get("path") or "")).resolve()
                if path.suffix.lower() == ".json" and path.is_file() and path.is_relative_to(run_dir):
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict) and (value.get("method_data_package") or value.get("schema_version") == "research-method-data-v1"):
                        return True
            except (OSError, RuntimeError, json.JSONDecodeError):
                continue
        return False

    @staticmethod
    def _processing_allowed(brief: dict) -> bool:
        ethics = brief.get("ethics_plan") or {}
        sensitivity = str(ethics.get("data_sensitivity") or "").lower()
        sensitive = any(marker in sensitivity for marker in ("sensitive", "personal", "confidential", "敏感", "个人"))
        return not sensitive or ethics.get("external_model_processing_approved") is True


method_material_analysis_service = MethodMaterialAnalysisService()
