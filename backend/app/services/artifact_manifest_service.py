from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..core.config import settings


class ArtifactManifestService:
    def initialize(self, run_dir: Path, *, run_id: str, display_name: str) -> Path:
        path = self._path(run_dir)
        if path.exists():
            return path
        path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "display_name": display_name,
                    "created_at": datetime.now().isoformat(),
                    "artifacts": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def register(self, run_dir: Path, *, kind: str, path: str, metadata: dict | None = None) -> dict:
        manifest_path = self._path(run_dir)
        manifest = self.read(run_dir)
        entry = {
            "kind": kind,
            "path": path,
            "metadata": metadata or {},
            "registered_at": datetime.now().isoformat(),
        }
        if not any(item["path"] == path for item in manifest["artifacts"]):
            manifest["artifacts"].append(entry)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return entry

    def read(self, run_dir: Path) -> dict:
        path = self._path(run_dir)
        if not path.exists():
            return {"artifacts": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"artifacts": []}

    @staticmethod
    def _path(run_dir: Path) -> Path:
        return run_dir / settings.artifact_manifest_filename


artifact_manifest_service = ArtifactManifestService()
