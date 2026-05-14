from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import RunRepository


class RunArtifactService:
    def allocate(self, run_id: str, research_goal: str, created_at: str) -> dict:
        created = datetime.fromisoformat(created_at)
        day_key = created.date().isoformat()
        day_label = f"{created.month}.{created.day}"
        sequence = RunRepository.count_created_on(day_key) + 1
        title = self.summarize_goal(research_goal)
        display_name = f"{day_label}-{sequence}-{title}"
        artifact_dir = settings.artifacts_dir / "runs" / day_label / f"{sequence}.{title}"
        artifact_dir = self._dedupe(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / ".run_id").write_text(run_id, encoding="utf-8")
        return {
            "display_name": display_name,
            "artifact_dir": str(artifact_dir),
        }

    def run_dir(self, run: dict | None, run_id: str | None = None) -> Path:
        if run and run.get("artifact_dir"):
            path = Path(str(run["artifact_dir"]))
            path.mkdir(parents=True, exist_ok=True)
            return path
        fallback = settings.artifacts_dir / "runs" / str(run_id or (run or {}).get("id") or "unknown_run")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def summarize_goal(self, research_goal: str) -> str:
        text = primary_goal(research_goal)
        text = re.sub(r"[\r\n\t]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.split(r"[。；;.!?？]|要求：|任务目标：", text, maxsplit=1)[0].strip()
        text = re.sub(r'[\\/:*?"<>|#`]+', "", text)
        text = text.strip(" -_，,")
        if not text:
            text = "未命名课题"
        if len(text) > 28:
            text = text[:28].rstrip()
        if not any(word in text for word in ("调研", "研究", "实验", "分析", "报告")):
            text = f"{text}的调研"
        return text

    @staticmethod
    def _dedupe(path: Path) -> Path:
        if not path.exists():
            return path
        parent = path.parent
        stem = path.name
        for index in range(2, 100):
            candidate = parent / f"{stem}-{index}"
            if not candidate.exists():
                return candidate
        return parent / f"{stem}-{datetime.now().strftime('%H%M%S')}"


run_artifact_service = RunArtifactService()
