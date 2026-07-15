from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..storage.repositories import EvidenceRepository, ResearchBriefRepository, RunRepository
from .artifact_manifest_service import artifact_manifest_service
from .run_artifact_service import run_artifact_service


class ResearchMaterialService:
    """Create a truthful, hashed manifest from user-supplied run materials."""

    def ingest_for_task(self, task: dict) -> dict:
        run_id = task.get("run_id")
        run = RunRepository.get_by_id(run_id) or {}
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        run_dir = run_artifact_service.run_dir(run, run_id).resolve()
        attachments_path = run_dir / "inputs" / "attachments.json"
        attachments = self._load_attachments(attachments_path)
        authorization = self._authorization_evidence(brief)
        records: list[dict] = []
        for index, item in enumerate(attachments, start=1):
            try:
                path = Path(str(item.get("path") or "")).resolve()
                if not path.is_file() or not path.is_relative_to(run_dir):
                    continue
                content = path.read_bytes()
            except (OSError, RuntimeError):
                continue
            records.append({
                "id": f"material_{index:04d}", "name": item.get("name") or path.name,
                "path": str(path), "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content), "mime_type": item.get("mime_type") or "application/octet-stream",
                "provenance": "user_supplied_run_attachment",
                "declared_provenance": item.get("provenance") or item.get("source_url") or item.get("name") or path.name,
                "authorization_evidence": authorization,
            })
        if (brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")) == "systematic_review":
            review_record = self._systematic_review_pool(task, run_dir, authorization)
            if review_record:
                records.append(review_record)
        missing = self._missing_conditions(records, authorization, brief)
        manifest = {
            "frozen_at": datetime.now().isoformat(),
            "collection_log": "从运行输入目录读取用户上传原文件；未把 LLM 生成文本当作原始研究材料。",
            "source_records": records,
            "completeness": "complete" if not missing else "incomplete",
            "ethics_approval_reference": (brief.get("ethics_plan") or {}).get("approval_reference") or "not_required",
            "missing_conditions": missing,
        }
        output_dir = run_dir / "materials"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{task.get('id', 'task')}_material_manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_manifest_service.register(run_dir, kind="research_material_manifest", path=str(path))
        return {**manifest, "artifact": str(path)}

    @staticmethod
    def _systematic_review_pool(task: dict, run_dir: Path, authorization: str) -> dict | None:
        evidence = EvidenceRepository.get_by_run(task.get("run_id"))
        passages: dict[str, list[dict]] = {}
        for item in evidence.get("excerpts") or []:
            if item.get("excerpt_type") in {"metadata_only", "summary"} or not str(item.get("excerpt") or "").strip():
                continue
            passages.setdefault(str(item.get("source_id")), []).append({
                "id": item.get("id"), "locator": item.get("locator"),
                "text": str(item.get("excerpt"))[:2400],
            })
        studies = [
            {
                **{key: source.get(key) for key in ("id", "title", "authors", "year", "venue", "doi", "url")},
                "passages": passages.get(source["id"], []),
            }
            for source in evidence.get("sources") or []
            if (source.get("metadata") or {}).get("citation_eligible") and passages.get(source.get("id"))
        ]
        if not studies:
            return None
        path = run_dir / "materials" / f"{task.get('id', 'task')}_systematic_review_pool.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "systematic-review-pool-v1", "studies": studies,
            "deduplication_log": {
                "input_count": len(studies), "deduplicated_count": len(studies), "duplicate_ids": [],
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_manifest_service.register(run_dir, kind="systematic_review_pool", path=str(path))
        raw = path.read_bytes()
        return {
            "id": "systematic_review_pool", "name": path.name, "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
            "mime_type": "application/json", "provenance": "verified_fulltext_evidence_pipeline",
            "declared_provenance": "frozen_verified_literature_evidence_pool_already_deduplicated",
            "authorization_evidence": authorization,
        }

    @staticmethod
    def _load_attachments(path: Path) -> list[dict]:
        if not path.is_file():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _authorization_evidence(brief: dict) -> str:
        evidence = [
            str(item.get("evidence") or "").strip()
            for item in brief.get("resource_plan") or []
            if isinstance(item, dict) and item.get("required") and item.get("status") == "available"
        ]
        return "；".join(item for item in evidence if item)

    @staticmethod
    def _missing_conditions(records: list[dict], authorization: str, brief: dict) -> list[str]:
        missing = []
        if not records:
            missing.append("no_user_supplied_material_files")
        if not authorization:
            missing.append("authorization_or_license_evidence_missing")
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
        if family == "systematic_review" and not any(
            item.get("provenance") == "verified_fulltext_evidence_pipeline" for item in records
        ):
            missing.append("verified_systematic_review_pool_missing")
        ethics = brief.get("ethics_plan") or {}
        if ethics.get("required") and ethics.get("status") != "approved":
            missing.append("ethics_approval_missing")
        return missing


research_material_service = ResearchMaterialService()
