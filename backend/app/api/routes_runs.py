import asyncio
import base64
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
from ..services.run_event_service import run_event_service
from ..services.run_execution_service import run_execution_service
from ..storage.repositories import LLMUsageRepository, RunEventRepository, RunRepository, TaskRepository


async def _safe_execute_run(run_id: str) -> None:
    await asyncio.sleep(0)
    try:
        await run_execution_service.execute(run_id)
    except Exception:
        traceback.print_exc()


class RunCreateRequest(BaseModel):
    research_goal: str
    attachments: list[dict] = Field(default_factory=list)


class CancelRequest(BaseModel):
    reason: str | None = None


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


def _save_and_extract_attachments(run_id: str, attachments: list[dict]) -> list[dict]:
    if not attachments:
        return []
    input_dir = settings.artifacts_dir / "runs" / run_id / "inputs"
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
        text = _extract_attachment_text(path, mime_type)
        if text and (path.suffix.lower() == ".pdf" or mime_type == "application/pdf"):
            path.with_suffix(".md").write_text(f"# {name}\n\n{text}", encoding="utf-8")
        extracted.append(
            {
                "name": name,
                "mime_type": mime_type,
                "size": item.get("size"),
                "path": str(path),
                "extracted_markdown": text,
            }
        )

    (input_dir / "attachments.json").write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
    return extracted


@router.post("")
async def create_run(req: RunCreateRequest):
    preflight = _preflight_attachments(req.attachments)
    if not preflight["ok"]:
        raise HTTPException(status_code=400, detail="；".join(preflight["errors"]))

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    extracted_attachments = _save_and_extract_attachments(run_id, req.attachments)
    research_goal = merge_goal_with_attachments(req.research_goal, extracted_attachments, settings.attachment_extract_max_chars)
    logger.info("[API] create_run | run_id=%s | goal=%s | attachments=%d", run_id, req.research_goal[:80], len(extracted_attachments))

    now = datetime.now().isoformat()
    run = {
        "id": run_id,
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
    run_event_service.emit(run_id, "run.created", "run", "运行已创建", "已保存研究目标，等待启动")
    return {"run_id": run_id, "status": RunStatus.created.value, "preflight": preflight}


@router.post("/preflight")
async def preflight_run(req: RunCreateRequest):
    return _preflight_attachments(req.attachments)


@router.get("")
async def get_runs():
    logger.debug("[API] get_runs")
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
    run_dir = settings.artifacts_dir / "runs" / run_id
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
