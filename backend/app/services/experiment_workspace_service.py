from pathlib import Path

from fastapi import HTTPException

from ..core.config import PROJECT_ROOT, settings
from ..storage.repositories import RunRepository
from .run_artifact_service import run_artifact_service


class ExperimentWorkspaceService:
    def resolve_workspace(self, requested: str | None = None) -> Path:
        raw = (requested or settings.experiment_workspace_dir).strip() or settings.experiment_workspace_dir
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        resolved = path.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def safe_child(self, workspace: Path, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise HTTPException(status_code=400, detail="实验文件路径必须是工作区内的相对路径")
        target = (workspace / relative_path).resolve()
        if not self._is_relative_to(target, workspace):
            raise HTTPException(status_code=400, detail="实验文件路径越过了工作区边界")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def artifacts_dir(self, plan: dict) -> Path:
        run_id = plan.get("run_id")
        if run_id:
            run = RunRepository.get_by_id(run_id)
            path = run_artifact_service.run_dir(run, run_id) / "experiments" / plan["id"]
        else:
            path = settings.artifacts_dir / "experiments" / plan["id"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


experiment_workspace_service = ExperimentWorkspaceService()
