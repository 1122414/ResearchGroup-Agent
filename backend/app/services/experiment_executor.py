from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from ..core.config import settings
from ..core.logger import logger
from ..models.experiment import ExperimentApproval, ExperimentPlanCreate, ExperimentPlanUpdate, ExperimentReject
from ..storage.repositories import ExperimentPlanRepository, RunEventRepository
from .command_risk_scanner import command_risk_scanner
from .experiment_workspace_service import experiment_workspace_service


class ExperimentExecutorService:
    def list(self, run_id: str | None = None, task_id: str | None = None, status: str | None = None) -> list[dict]:
        return ExperimentPlanRepository.get_all(run_id=run_id, task_id=task_id, status=status)

    def get(self, plan_id: str) -> dict:
        plan = ExperimentPlanRepository.get_by_id(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="实验计划不存在")
        return plan

    def create_plan(self, body: ExperimentPlanCreate) -> dict:
        now = datetime.now().isoformat()
        plan = {
            "id": f"exp_{uuid.uuid4().hex[:8]}",
            "run_id": body.run_id,
            "task_id": body.task_id,
            "agent_id": body.agent_id,
            "title": body.title,
            "objective": body.objective,
            "workspace_dir": str(experiment_workspace_service.resolve_workspace(body.workspace_dir)),
            "files": [item.model_dump() for item in body.files],
            "commands": [item.model_dump() for item in body.commands],
            "env_vars": body.env_vars,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        }
        plan.update(command_risk_scanner.scan(plan))
        if plan["risk_level"] != "safe" or settings.experiment_require_review:
            plan["status"] = "needs_review"
        ExperimentPlanRepository.insert(plan)
        self._emit(plan, "experiment.plan_created", "实验计划已创建", {"risk_level": plan["risk_level"]})
        return self.get(plan["id"])

    def update_plan(self, plan_id: str, body: ExperimentPlanUpdate) -> dict:
        plan = self.get(plan_id)
        if plan["status"] in {"running", "completed"}:
            raise HTTPException(status_code=409, detail="运行中或已完成的实验计划不能直接修改")

        updates = body.model_dump(exclude_unset=True)
        if "workspace_dir" in updates:
            updates["workspace_dir"] = str(experiment_workspace_service.resolve_workspace(updates["workspace_dir"]))
        if "files" in updates and updates["files"] is not None:
            updates["files"] = [item.model_dump() for item in body.files or []]
        if "commands" in updates and updates["commands"] is not None:
            updates["commands"] = [item.model_dump() for item in body.commands or []]

        merged = {**plan, **updates}
        scan = command_risk_scanner.scan(merged)
        updates.update(scan)
        updates["status"] = "needs_review" if settings.experiment_require_review or scan["risk_level"] != "safe" else "draft"
        updates["approved_at"] = None
        updates["approved_by"] = None
        updates["updated_at"] = datetime.now().isoformat()
        ExperimentPlanRepository.update(plan_id, updates)
        self._emit(self.get(plan_id), "experiment.plan_updated", "实验计划已更新", {"risk_level": scan["risk_level"]})
        return self.get(plan_id)

    def scan_plan(self, plan_id: str) -> dict:
        plan = self.get(plan_id)
        scan = command_risk_scanner.scan(plan)
        next_status = plan["status"]
        if plan["status"] in {"draft", "needs_review"} and (settings.experiment_require_review or scan["risk_level"] != "safe"):
            next_status = "needs_review"
        updates = {
            **scan,
            "status": next_status,
            "updated_at": datetime.now().isoformat(),
        }
        ExperimentPlanRepository.update(plan_id, updates)
        self._emit(self.get(plan_id), "experiment.scanned", "实验风险扫描完成", scan)
        return self.get(plan_id)

    def approve_plan(self, plan_id: str, body: ExperimentApproval) -> dict:
        plan = self.scan_plan(plan_id)
        now = datetime.now().isoformat()
        ExperimentPlanRepository.update(
            plan_id,
            {"status": "approved", "approved_at": now, "approved_by": body.approved_by, "updated_at": now},
        )
        approved = self.get(plan_id)
        self._emit(approved, "experiment.approved", "实验计划已批准", {"approved_by": body.approved_by})
        return approved

    def reject_plan(self, plan_id: str, body: ExperimentReject) -> dict:
        now = datetime.now().isoformat()
        ExperimentPlanRepository.update(plan_id, {"status": "rejected", "updated_at": now})
        plan = self.get(plan_id)
        self._emit(plan, "experiment.rejected", "实验计划已驳回", {"reason": body.reason})
        return plan

    def execute_plan(self, plan_id: str) -> dict:
        if not settings.experiment_execution_enabled:
            raise HTTPException(status_code=403, detail="实验执行器未启用，请先在设置中开启")
        if settings.experiment_execution_backend != "local":
            raise HTTPException(status_code=501, detail="当前版本仅实现本地实验执行，远程/队列后端预留中")

        plan = self.scan_plan(plan_id)
        if settings.experiment_require_review and plan["status"] != "approved":
            raise HTTPException(status_code=409, detail="实验计划需要用户审查并批准后才能执行")
        if plan["risk_level"] == "dangerous" and plan["status"] != "approved":
            raise HTTPException(status_code=409, detail="危险实验计划必须先获得用户批准")

        workspace = experiment_workspace_service.resolve_workspace(plan["workspace_dir"])
        artifacts_dir = experiment_workspace_service.artifacts_dir(plan)
        self._write_files(workspace, plan.get("files", []))
        now = datetime.now().isoformat()
        ExperimentPlanRepository.update(plan_id, {"status": "running", "updated_at": now})
        self._emit(plan, "experiment.started", "实验开始执行", {"workspace": str(workspace)})

        result = self._run_commands(workspace, plan)
        status = "completed" if result["exit_code"] == 0 else "failed"
        artifacts = self._write_artifacts(artifacts_dir, plan, result)
        now = datetime.now().isoformat()
        ExperimentPlanRepository.update(
            plan_id,
            {
                "status": status,
                "result": result,
                "artifacts": artifacts,
                "updated_at": now,
            },
        )
        completed = self.get(plan_id)
        self._emit(completed, f"experiment.{status}", "实验执行完成" if status == "completed" else "实验执行失败", result)
        logger.info("[ExperimentExecutor] plan executed | plan_id=%s | status=%s", plan_id, status)
        return completed

    def _write_files(self, workspace, files: list[dict]):
        for file_item in files:
            path = experiment_workspace_service.safe_child(workspace, file_item["path"])
            path.write_text(file_item.get("content", ""), encoding="utf-8")

    def _run_commands(self, workspace, plan: dict) -> dict:
        env = os.environ.copy()
        env.update({"HOME": str(workspace), "MPLCONFIGDIR": str(workspace / ".mplconfig")})
        (workspace / ".mplconfig").mkdir(exist_ok=True)
        env.update({str(key): str(value) for key, value in plan.get("env_vars", {}).items()})
        command_results: list[dict] = []
        started = time.perf_counter()
        final_exit = 0
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        for item in plan.get("commands", []):
            command = item["command"] if isinstance(item, dict) else str(item)
            command_started = time.perf_counter()
            try:
                execution_command, shell, sandboxed = self._sandbox_command(command, workspace)
                if not sandboxed:
                    command_results.append(
                        {
                            "command": command, "exit_code": 126, "stdout": "",
                            "stderr": "Execution sandbox is unavailable; command was not executed.",
                            "elapsed_ms": 0, "sandboxed": False,
                        }
                    )
                    final_exit = 126
                    stderr_parts.append("Execution sandbox is unavailable; command was not executed.")
                    break
                proc = subprocess.run(
                    execution_command,
                    shell=shell,
                    cwd=str(workspace),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=settings.experiment_command_timeout_seconds,
                )
                stdout = self._truncate(proc.stdout or "")
                stderr = self._truncate(proc.stderr or "")
                exit_code = proc.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = self._truncate(exc.stdout or "")
                stderr = self._truncate((exc.stderr or "") + "\nCommand timed out")
                exit_code = 124
            elapsed_ms = int((time.perf_counter() - command_started) * 1000)
            command_result = {
                "command": command, "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
                "elapsed_ms": elapsed_ms, "sandboxed": sandboxed,
            }
            command_results.append(command_result)
            stdout_parts.append(stdout)
            stderr_parts.append(stderr)
            final_exit = exit_code
            if exit_code != 0:
                break

        return {
            "exit_code": final_exit,
            "stdout": self._truncate("\n".join(stdout_parts)),
            "stderr": self._truncate("\n".join(stderr_parts)),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "command_results": command_results,
            "sandboxed": bool(command_results) and all(item.get("sandboxed") for item in command_results),
        }

    @staticmethod
    def _sandbox_command(command: str, workspace) -> tuple[str | list[str], bool, bool]:
        if platform.system() != "Darwin" or not shutil.which("sandbox-exec"):
            return command, True, False
        runtime_root = str(Path(sys.executable).resolve().parent.parent)
        venv_root = str(Path(sys.prefix).resolve())
        profile = "".join(
            [
                "(version 1)(deny default)(allow process*)(allow sysctl-read)",
                "(allow mach-lookup)(allow ipc*)",
                "(allow file-read*)",
                f'(deny file-read* (subpath "{Path.home()}"))',
                f'(allow file-read* (subpath "{runtime_root}") (subpath "{venv_root}") (subpath "{workspace}"))',
                f'(allow file-write* (subpath "{workspace}"))',
                "(allow network*)" if settings.experiment_allow_network else "(deny network*)",
            ]
        )
        return ["sandbox-exec", "-p", profile, "/bin/sh", "-lc", command], False, True

    def _write_artifacts(self, artifacts_dir, plan: dict, result: dict) -> list[str]:
        files = {
            "plan.json": json.dumps(plan, ensure_ascii=False, indent=2),
            "result.json": json.dumps(result, ensure_ascii=False, indent=2),
            "stdout.log": result.get("stdout", ""),
            "stderr.log": result.get("stderr", ""),
            "summary.md": self._summary(plan, result),
        }
        artifact_paths: list[str] = []
        for name, content in files.items():
            path = artifacts_dir / name
            path.write_text(content, encoding="utf-8")
            artifact_paths.append(str(path))
        return artifact_paths

    def _summary(self, plan: dict, result: dict) -> str:
        return "\n".join(
            [
                f"# 实验执行摘要：{plan.get('title', '')}",
                "",
                f"- Plan: {plan.get('id')}",
                f"- Agent: {plan.get('agent_id')}",
                f"- Exit code: {result.get('exit_code')}",
                f"- Elapsed: {result.get('elapsed_ms')} ms",
                "",
                "## Stdout",
                "",
                "```text",
                result.get("stdout", ""),
                "```",
                "",
                "## Stderr",
                "",
                "```text",
                result.get("stderr", ""),
                "```",
            ]
        )

    def _emit(self, plan: dict, event_type: str, title: str, payload: dict):
        if not plan.get("run_id"):
            return
        RunEventRepository.insert(
            {
                "id": f"evt_{uuid.uuid4().hex[:10]}",
                "run_id": plan["run_id"],
                "task_id": plan.get("task_id"),
                "agent_id": plan.get("agent_id"),
                "event_type": event_type,
                "phase": "experiment",
                "title": title,
                "message": plan.get("title", ""),
                "payload": payload,
                "created_at": datetime.now().isoformat(),
            }
        )

    def _truncate(self, text: str) -> str:
        limit = settings.experiment_max_output_chars
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...[truncated]"


experiment_executor_service = ExperimentExecutorService()
