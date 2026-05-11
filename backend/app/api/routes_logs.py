import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..core.logger import BACKEND_LOG_DIR, logger

router = APIRouter(prefix="/api/logs", tags=["logs"])


class FrontendLogEntry(BaseModel):
    timestamp: str
    level: str
    file: str
    func: str
    line: int
    message: str
    run_id: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)


class FrontendLogBatch(BaseModel):
    entries: list[FrontendLogEntry]


class FrontendLogResponse(BaseModel):
    saved: int
    log_file: str


def _get_frontend_log_path() -> Path:
    now = datetime.now()
    date_folder = f"{now.month}.{now.day}"
    day_dir = BACKEND_LOG_DIR / date_folder
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / "frontend.log"


@router.post("", response_model=FrontendLogResponse)
async def receive_frontend_logs(batch: FrontendLogBatch):
    log_path = _get_frontend_log_path()
    saved = 0
    with open(log_path, "a", encoding="utf-8") as f:
        for entry in batch.entries:
            line = (
                f"{entry.timestamp} | {entry.level:8} | "
                f"{entry.file}:{entry.func}:{entry.line} | "
                f"{entry.message}"
            )
            if entry.run_id:
                line += f" | run_id={entry.run_id}"
            if entry.extra:
                line += f" | extra={json.dumps(entry.extra, ensure_ascii=False)}"
            f.write(line + "\n")
            saved += 1
            _ = saved

    logger.info("Received %d frontend log entries | file=%s", saved, log_path)
    return FrontendLogResponse(saved=saved, log_file=str(log_path))
