import asyncio
import base64
import hashlib
import json
import shutil
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.logger import logger
from ..core.research_goal import merge_goal_with_attachments
from ..core.state_machine import assert_run_transition, can_delete_run
from ..models.run import RunStatus
from ..services.run_artifact_service import run_artifact_service
from ..services.artifact_manifest_service import artifact_manifest_service
from ..services.run_event_service import run_event_service
from ..services.run_execution_service import run_execution_service
from ..services.approval_service import approval_service
from ..services.claim_evaluation_service import claim_evaluation_service
from ..services.evidence_pipeline_service import evidence_pipeline_service
from ..services.evidence_provider import evidence_provider
from ..services.research_state_service import research_state_service
from ..services.research_contract_service import research_contract_service
from ..services.research_loop_service import research_loop_service
from ..services.task_graph_service import task_graph_service
from ..storage.repositories import (
    ApprovalRequestRepository,
    EvidenceRepository,
    FullTextDocumentRepository,
    LiteratureSearchRepository,
    LLMUsageRepository,
    MemoryRecordRepository,
    ReviewDecisionRepository,
    RunEventRepository,
    RunRepository,
    ResearchClaimRepository,
    TaskAttemptRepository,
    TaskRepository,
)


async def _safe_execute_run(run_id: str) -> None:
    await asyncio.sleep(0)
    try:
        await run_execution_service.execute(run_id)
    except Exception:
        traceback.print_exc()


class SeedSource(BaseModel):
    title: str
    authors: str = ""
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    url: str | None = None
    source_type: str = "paper"


class RunCreateRequest(BaseModel):
    research_goal: str
    attachments: list[dict] = Field(default_factory=list)
    seed_sources: list[SeedSource] = Field(default_factory=list)


class CancelRequest(BaseModel):
    reason: str | None = None


class ApprovalResolutionRequest(BaseModel):
    approved: bool = True
    resolved_by: str = "user"


class EvidenceSourceCreateRequest(BaseModel):
    task_id: str | None = None
    title: str
    authors: str = ""
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    url: str | None = None
    source_type: str = "paper"


class EvidenceSearchRequest(BaseModel):
    query: str


class EvidenceExcerptCreateRequest(BaseModel):
    excerpt: str
    locator: str = ""
    excerpt_type: str = "summary"


class EvidenceLinkCreateRequest(BaseModel):
    claim_id: str
    source_id: str
    excerpt_id: str | None = None
    relation_type: str = "supports"
    confidence: float = Field(default=0.8, ge=0, le=1)
    rationale: str = ""


class ResearchClaimCreateRequest(BaseModel):
    hypothesis_id: str | None = None
    statement: str


router = APIRouter(prefix="/api/runs", tags=["runs"])


def _decode_data_url(data_url: str) -> bytes:
    if "," in data_url:
        _, data_url = data_url.split(",", 1)
    return base64.b64decode(data_url)


def _pdf_extractor_available() -> bool:
    try:
        import pypdf  # noqa: F401

        return True
    except Exception:
        try:
            import PyPDF2  # noqa: F401

            return True
        except Exception:
            return False


def _extract_pdf_text(path: Path) -> str:
    try:
        try:
            from pypdf import PdfReader
        except Exception:
            from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page.strip() for page in pages if page.strip())
    except Exception as exc:
        logger.warning("[API] pdf extract failed | path=%s | error=%s", path, exc)
        return ""


def _extract_attachment_text(path: Path, mime_type: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".csv", ".json"} or mime_type.startswith("text/"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf" or mime_type == "application/pdf":
        return _extract_pdf_text(path)
    if mime_type.startswith("image/"):
        return "图片附件已保存；需要配置多模态视觉模型后才能提取图片语义。"
    return f"附件 {path.name} 已保存，但当前类型未配置文本提取器。"


def _preflight_attachments(attachments: list[dict]) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    max_bytes = settings.attachment_max_file_size_mb * 1024 * 1024
    has_pdf = False
    has_image = False

    for item in attachments:
        name = str(item.get("name") or "附件")
        mime_type = str(item.get("mime_type") or "")
        size = int(item.get("size") or 0)
        has_pdf = has_pdf or mime_type == "application/pdf" or name.lower().endswith(".pdf")
        has_image = has_image or mime_type.startswith("image/")
        if size > max_bytes:
            errors.append(f"{name} 超过附件大小限制 {settings.attachment_max_file_size_mb}MB")

    if has_pdf and not _pdf_extractor_available():
        warnings.append("当前环境未安装 pypdf/PyPDF2，PDF 只能保存原文件，无法自动提取为 Markdown。")
    if has_image:
        if not settings.multimodal_enabled:
            errors.append("检测到图片附件，但 MULTIMODAL_ENABLED=false。请在系统设置中开启多模态输入。")
        elif not settings.vision_model_name:
            errors.append("检测到图片附件，但未配置 VISION_MODEL_NAME。")
        elif settings.mock_mode:
            warnings.append("当前为 Mock 模式，图片语义会以占位说明进入任务上下文。")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "supports_pdf_extract": _pdf_extractor_available(),
        "supports_image": bool(settings.multimodal_enabled and settings.vision_model_name),
        "limits": {
            "attachment_max_file_size_mb": settings.attachment_max_file_size_mb,
            "attachment_extract_max_chars": settings.attachment_extract_max_chars,
        },
    }


def _save_and_extract_attachments(run_id: str, attachments: list[dict], artifact_dir: Path | None = None) -> list[dict]:
    if not attachments:
        return []
    input_dir = (artifact_dir or settings.artifacts_dir / "runs" / run_id) / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[dict] = []

    for index, item in enumerate(attachments, start=1):
        name = Path(str(item.get("name") or f"attachment_{index}")).name
        mime_type = str(item.get("mime_type") or "")
        data_url = str(item.get("data_url") or "")
        if not data_url:
            continue
        path = input_dir / f"{index:02d}_{name}"
        path.write_bytes(_decode_data_url(data_url))
        artifact_manifest_service.register(input_dir.parent, kind="input", path=str(path), metadata={"mime_type": mime_type})
        text = _extract_attachment_text(path, mime_type)
        if text and (path.suffix.lower() == ".pdf" or mime_type == "application/pdf"):
            path.with_suffix(".md").write_text(f"# {name}\n\n{text}", encoding="utf-8")
            artifact_manifest_service.register(input_dir.parent, kind="input_extract", path=str(path.with_suffix(".md")))
        extracted.append(
            {
                "name": name,
                "mime_type": mime_type,
                "size": item.get("size"),
                "path": str(path),
                "extracted_markdown": text,
                "source_url": item.get("source_url"),
                "license": item.get("license"),
                "provenance": item.get("provenance") or item.get("source_url"),
            }
        )

    attachments_index = input_dir / "attachments.json"
    attachments_index.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_manifest_service.register(input_dir.parent, kind="input_index", path=str(attachments_index))
    return extracted


def _persist_attachment_sources(run_id: str, attachments: list[dict]) -> int:
    """Register traceable uploaded snapshots as local primary evidence."""
    count = 0
    for item in attachments:
        source_url = str(item.get("source_url") or "").strip()
        text = str(item.get("extracted_markdown") or "").strip()
        if not source_url or len(text) < 200:
            continue
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            continue
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        snapshot_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata = _attachment_bibliography(item, text)
        source = evidence_pipeline_service._normalize_source(
            {
                "title": metadata["title"], "authors": metadata["authors"],
                "year": metadata["year"], "venue": metadata["venue"],
                "doi": None, "url": source_url, "source_type": metadata["source_type"],
                "metadata": {
                    "provider": "local_attachment", "origin": "user_attachment",
                    "attachment_integrity_verified": True, "content_hash": content_hash,
                    "snapshot_sha256": snapshot_hash,
                    "local_snapshot": f"inputs/{path.name}", "license": item.get("license"),
                    "declared_provenance": item.get("provenance") or source_url,
                    "verification_status": "user_attachment_integrity_verified",
                    "citation_eligible": True, "content": text[:2000],
                },
            },
            {"run_id": run_id, "id": None},
        )
        source_id = source["id"]
        document_id = f"attachment_document_{run_id.removeprefix('run_')}_{content_hash[:10]}"
        now = datetime.now().isoformat()
        EvidenceRepository.upsert_source(
            {
                **source, "run_id": run_id, "task_id": None, "created_at": now,
            }
        )
        FullTextDocumentRepository.insert(
            {
                "id": document_id, "run_id": run_id, "source_id": source_id,
                "url": f"inputs/{path.name}", "content_hash": content_hash,
                "parser": "uploaded_snapshot", "status": "parsed",
                "char_count": len(text), "created_at": now,
            }
        )
        for index, start in enumerate(range(0, len(text), settings.evidence_excerpt_max_chars)):
            passage = text[start : start + settings.evidence_excerpt_max_chars].strip()
            if not passage:
                continue
            EvidenceRepository.insert_excerpt(
                {
                    "id": f"attachment_excerpt_{uuid.uuid4().hex[:10]}", "run_id": run_id,
                    "source_id": source_id, "excerpt": passage,
                    "locator": f"inputs/{path.name}#chars={start}-{start + len(passage)}",
                    "excerpt_type": "fulltext", "captured_at": now,
                    "document_id": document_id, "section": "", "page_number": None,
                    "paragraph_index": index, "content_hash": content_hash,
                }
            )
        count += 1
    return count


def _attachment_bibliography(item: dict, text: str) -> dict:
    payload = {}
    if str(item.get("mime_type") or "") == "application/json" or str(item.get("name") or "").endswith(".json"):
        try:
            parsed = json.loads(text)
            payload = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    title = str(payload.get("title") or item.get("name") or "uploaded research material").strip()
    authors = payload.get("authors") or payload.get("author") or ""
    if isinstance(authors, list):
        authors = ", ".join(str(author) for author in authors)
    year = payload.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    suffix = Path(str(item.get("name") or "")).suffix.lower()
    return {
        "title": title, "authors": str(authors), "year": year,
        "venue": str(payload.get("publisher") or payload.get("venue") or ""),
        "source_type": "dataset" if suffix in {".json", ".csv", ".tsv"} else "primary_source",
    }


@router.post("")
async def create_run(req: RunCreateRequest):
    preflight = _preflight_attachments(req.attachments)
    if not preflight["ok"]:
        raise HTTPException(status_code=400, detail="；".join(preflight["errors"]))

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    artifact_meta = run_artifact_service.allocate(run_id, req.research_goal, now)
    extracted_attachments = _save_and_extract_attachments(run_id, req.attachments, Path(artifact_meta["artifact_dir"]))
    research_goal = merge_goal_with_attachments(req.research_goal, extracted_attachments, settings.attachment_extract_max_chars)
    logger.info("[API] create_run | run_id=%s | goal=%s | attachments=%d", run_id, req.research_goal[:80], len(extracted_attachments))

    run = {
        "id": run_id,
        "display_name": artifact_meta["display_name"],
        "artifact_dir": artifact_meta["artifact_dir"],
        "research_goal": research_goal,
        "status": RunStatus.created.value,
        "current_step": "已创建，等待启动",
        "task_ids": [],
        "agent_assignments": {},
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "cancel_requested_at": None,
        "cancel_reason": None,
        "total_cost_usd": 0,
        "total_tokens": 0,
        "total_llm_calls": 0,
        "last_event_id": None,
    }
    RunRepository.insert(run)
    attachment_sources = _persist_attachment_sources(run_id, extracted_attachments)
    research_state_service.ensure_initialized(run)
    seeded = _persist_seed_sources(run_id, req.seed_sources)
    run_event_service.emit(run_id, "run.created", "run", "运行已创建", "已保存研究目标，等待启动")
    if seeded:
        run_event_service.emit(run_id, "run.seed_sources", "run", "已导入种子文献", f"用户提供 {seeded} 篇种子文献作为研究起点")
    if attachment_sources:
        run_event_service.emit(run_id, "run.attachment_sources", "evidence", "已冻结附件证据", f"登记 {attachment_sources} 个带来源 URL 的本地一手快照")
    return {"run_id": run_id, "status": RunStatus.created.value, "display_name": artifact_meta["display_name"], "artifact_dir": artifact_meta["artifact_dir"], "seed_sources": seeded, "attachment_sources": attachment_sources, "preflight": preflight}


def _persist_seed_sources(run_id: str, seeds: list[SeedSource]) -> int:
    count = 0
    for seed in seeds:
        if not seed.title.strip():
            continue
        EvidenceRepository.upsert_source(
            {
                "id": f"seed_source_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "task_id": None,
                "title": seed.title,
                "authors": seed.authors,
                "year": seed.year,
                "venue": seed.venue,
                "doi": seed.doi,
                "url": seed.url,
                "source_type": seed.source_type,
                "metadata": {"origin": "user_seed"},
                "created_at": datetime.now().isoformat(),
            }
        )
        count += 1
    return count


@router.post("/preflight")
async def preflight_run(req: RunCreateRequest):
    return _preflight_attachments(req.attachments)


@router.get("")
async def get_runs():
    logger.debug("[API] get_runs")
    for run in RunRepository.get_all():
        if run.get("status") == RunStatus.cancelling.value:
            run_execution_service.get_summary(run["id"])
    return {"runs": RunRepository.get_all()}


@router.get("/{run_id}")
async def get_run(run_id: str):
    logger.debug("[API] get_run | run_id=%s", run_id)
    run = RunRepository.get_by_id(run_id)
    if not run:
        logger.warning("[API] get_run | run_id=%s not found", run_id)
        raise HTTPException(status_code=404, detail="运行不存在")
    return {"run": run, "tasks": TaskRepository.get_all(run_id=run_id)}


@router.post("/{run_id}/start")
async def start_run(run_id: str, background_tasks: BackgroundTasks):
    logger.info("[API] start_run | run_id=%s", run_id)
    run = RunRepository.get_by_id(run_id)
    if not run:
        logger.warning("[API] start_run | run_id=%s not found", run_id)
        raise HTTPException(status_code=404, detail="运行不存在")
    if run.get("status") not in (RunStatus.created.value, RunStatus.queued.value):
        logger.info("[API] start_run | run_id=%s already in status=%s", run_id, run.get("status"))
        return {"status": run.get("status"), "message": "运行已经启动或结束"}

    assert_run_transition(run.get("status"), RunStatus.queued.value)
    started_at = datetime.now().isoformat()
    RunRepository.update_status(run_id, RunStatus.queued.value, current_step="已排队，等待执行", started_at=started_at)
    run_event_service.emit(run_id, "run.started", "run", "运行已启动", "后台执行链路已排队")
    background_tasks.add_task(_safe_execute_run, run_id)
    logger.info("[API] start_run | run_id=%s queued and background task added", run_id)
    return {"status": RunStatus.queued.value, "message": "运行已排队"}


@router.post("/{run_id}/run_all")
async def run_all(run_id: str):
    return await run_execution_service.execute(run_id)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, req: CancelRequest | None = None):
    reason = req.reason if req and req.reason else "用户取消运行"
    logger.info("[API] cancel_run | run_id=%s | reason=%s", run_id, reason)
    return {"run": run_execution_service.request_cancel(run_id, reason)}


@router.delete("/{run_id}")
async def delete_run(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    if not can_delete_run(str(run.get("status"))):
        raise HTTPException(status_code=400, detail="运行正在执行中，请先取消或等待结束后再删除。")
    RunRepository.delete(run_id)
    run_dir = Path(str(run.get("artifact_dir") or "")) if run.get("artifact_dir") else settings.artifacts_dir / "runs" / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    return {"deleted": True, "run_id": run_id}


@router.get("/{run_id}/summary")
async def get_run_summary(run_id: str):
    logger.debug("[API] get_run_summary | run_id=%s", run_id)
    return run_execution_service.get_summary(run_id)


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str,
    limit: int = Query(default=settings.run_event_default_limit, ge=1),
    after_id: str | None = None,
    phase: str | None = None,
    task_id: str | None = None,
):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    safe_limit = min(limit, settings.run_event_max_limit)
    events = RunEventRepository.get_by_run(run_id, limit=safe_limit, after_id=after_id, phase=phase, task_id=task_id)
    return {"events": events, "next_after_id": events[-1]["id"] if events else after_id}


@router.get("/{run_id}/usage")
async def get_run_usage(run_id: str):
    logger.debug("[API] get_run_usage | run_id=%s", run_id)
    run = RunRepository.get_by_id(run_id)
    if not run:
        logger.warning("[API] get_run_usage | run_id=%s not found", run_id)
        raise HTTPException(status_code=404, detail="运行不存在")
    return {"summary": LLMUsageRepository.get_summary(run_id), "items": LLMUsageRepository.get_by_run(run_id)}


@router.get("/{run_id}/graph")
async def get_run_graph(run_id: str):
    return task_graph_service.get_graph(run_id)


@router.get("/{run_id}/memory")
async def get_run_memory(run_id: str):
    return {"items": MemoryRecordRepository.get_by_run(run_id)}


@router.get("/{run_id}/evidence")
async def get_run_evidence(run_id: str):
    return EvidenceRepository.get_by_run(run_id)


@router.get("/evidence/providers")
async def get_evidence_providers():
    return {"items": evidence_provider.list_capabilities()}


@router.post("/{run_id}/evidence/search")
async def search_run_evidence(run_id: str, body: EvidenceSearchRequest):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return await evidence_pipeline_service.collect_for_query(run_id, body.query)


@router.post("/{run_id}/claims")
async def create_run_claim(run_id: str, body: ResearchClaimCreateRequest):
    if not RunRepository.get_by_id(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    now = datetime.now().isoformat()
    claim = {
        "id": f"claim_{uuid.uuid4().hex[:10]}",
        "run_id": run_id,
        "hypothesis_id": body.hypothesis_id,
        "statement": body.statement,
        "status": "draft",
        "evidence_ids": [],
        "confidence": 0.0,
        "created_at": now,
        "updated_at": now,
    }
    ResearchClaimRepository.insert(claim)
    return {"claim": claim}


@router.get("/{run_id}/research-state")
async def get_run_research_state(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="è¿è¡Œä¸å­˜åœ¨")
    research_state_service.ensure_initialized(run)
    return research_state_service.get_state(run_id)


@router.patch("/{run_id}/research-contract")
async def revise_run_research_contract(run_id: str, body: dict, background_tasks: BackgroundTasks):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    revised = research_contract_service.revise(run_id, body)
    if revised["ready"]:
        pending = ApprovalRequestRepository.find_pending(run_id, "research_contract_revision")
        if pending:
            approval_service.resolve(pending["id"], True, resolved_by="user:contract_edit")
        if run.get("status") == RunStatus.waiting_confirmation.value:
            RunRepository.update_status(run_id, RunStatus.executing.value, current_step="研究契约已修订，继续执行")
            background_tasks.add_task(_safe_execute_run, run_id)
    return revised


@router.get("/{run_id}/research-loop")
async def get_run_research_loop(run_id: str):
    if not RunRepository.get_by_id(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return research_loop_service.snapshot(run_id)


@router.get("/{run_id}/literature-search")
async def get_run_literature_search(run_id: str):
    if not RunRepository.get_by_id(run_id):
        raise HTTPException(status_code=404, detail="运行不存在")
    return {
        **LiteratureSearchRepository.get_by_run(run_id),
        "fulltext_documents": FullTextDocumentRepository.get_by_run(run_id),
    }


@router.get("/{run_id}/artifact-manifest")
async def get_run_artifact_manifest(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run_dir = run_artifact_service.run_dir(run, run_id)
    return artifact_manifest_service.read(run_dir)


@router.post("/{run_id}/evidence/sources")
async def create_run_evidence_source(run_id: str, body: EvidenceSourceCreateRequest):
    if not RunRepository.get_by_id(run_id):
        raise HTTPException(status_code=404, detail="运行不存在")
    source_id = f"manual_source_{uuid.uuid4().hex[:10]}"
    EvidenceRepository.upsert_source(
        {
            "id": source_id,
            "run_id": run_id,
            "task_id": body.task_id,
            "title": body.title,
            "authors": body.authors,
            "year": body.year,
            "venue": body.venue,
            "doi": body.doi,
            "url": body.url,
            "source_type": body.source_type,
            "metadata": {"origin": "manual"},
            "created_at": datetime.now().isoformat(),
        }
    )
    return {"source": next(item for item in EvidenceRepository.get_by_run(run_id)["sources"] if item["id"] == source_id)}


@router.post("/{run_id}/evidence/sources/{source_id}/excerpts")
async def create_run_evidence_excerpt(run_id: str, source_id: str, body: EvidenceExcerptCreateRequest):
    if not EvidenceRepository.get_source(run_id, source_id):
        raise HTTPException(status_code=404, detail="source not found")
    excerpt = {
        "id": f"excerpt_{uuid.uuid4().hex[:10]}",
        "run_id": run_id,
        "source_id": source_id,
        "excerpt": body.excerpt,
        "locator": body.locator,
        "excerpt_type": body.excerpt_type,
        "captured_at": datetime.now().isoformat(),
    }
    EvidenceRepository.insert_excerpt(excerpt)
    return {"excerpt": excerpt}


@router.post("/{run_id}/evidence/links")
async def create_run_evidence_link(run_id: str, body: EvidenceLinkCreateRequest):
    claim = ResearchClaimRepository.get_by_id(body.claim_id)
    source = EvidenceRepository.get_source(run_id, body.source_id)
    excerpt = EvidenceRepository.get_excerpt(run_id, body.excerpt_id) if body.excerpt_id else None
    if not claim or claim["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="claim not found")
    if not source:
        raise HTTPException(status_code=404, detail="source not found")
    if body.excerpt_id and (not excerpt or excerpt["source_id"] != body.source_id):
        raise HTTPException(status_code=400, detail="excerpt does not belong to source")
    if body.relation_type not in {"supports", "opposes", "context"}:
        raise HTTPException(status_code=400, detail="invalid relation_type")
    link = {
        "id": f"link_{uuid.uuid4().hex[:10]}",
        "run_id": run_id,
        "claim_id": body.claim_id,
        "source_id": body.source_id,
        "excerpt_id": body.excerpt_id,
        "relation_type": body.relation_type,
        "confidence": body.confidence,
        "rationale": body.rationale,
        "created_at": datetime.now().isoformat(),
    }
    EvidenceRepository.insert_link(link)
    updated_claim = claim_evaluation_service.evaluate(body.claim_id)
    return {"link": link, "claim": updated_claim}


@router.get("/{run_id}/reviews")
async def get_run_reviews(run_id: str):
    return {"items": ReviewDecisionRepository.get_by_run(run_id)}


@router.get("/{run_id}/attempts")
async def get_run_attempts(run_id: str):
    return {"items": TaskAttemptRepository.get_by_run(run_id)}


@router.get("/{run_id}/approvals")
async def get_run_approvals(run_id: str):
    return {"items": ApprovalRequestRepository.get_by_run(run_id)}


@router.post("/approvals/{request_id}/resolve")
async def resolve_approval(request_id: str, body: ApprovalResolutionRequest, background_tasks: BackgroundTasks):
    request = approval_service.resolve(request_id, body.approved, body.resolved_by)
    if body.approved:
        if request["request_type"] == "revision_required":
            payload = request.get("payload", {})
            revision_task_ids = list(payload.get("revision_task_ids") or [])
            if payload.get("revision_task_id"):
                revision_task_ids.append(payload["revision_task_id"])
            if revision_task_ids:
                for revision_task_id in dict.fromkeys(revision_task_ids):
                    revision_task = TaskRepository.get_by_id(revision_task_id)
                    if revision_task and revision_task.get("status") in {"blocked", "need_revision"}:
                        TaskRepository.update_status(revision_task_id, "pending", blocked_reason=None)
            elif request.get("task_id"):
                TaskRepository.update_status(
                    request["task_id"],
                    "pending",
                    review_result=None,
                    review_feedback=None,
                    blocked_reason=None,
                )
        run = RunRepository.get_by_id(request["run_id"])
        if run and run.get("status") == RunStatus.waiting_confirmation.value:
            RunRepository.update_status(run["id"], RunStatus.executing.value, current_step="已确认，继续执行")
            background_tasks.add_task(_safe_execute_run, run["id"])
    return {"request": request}
