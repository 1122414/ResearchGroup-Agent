from __future__ import annotations


class ExperimentBackend:
    def list_capabilities(self) -> list[dict]:
        return [
            {"name": "local", "enabled": True},
            {"name": "docker", "enabled": False},
            {"name": "remote_host", "enabled": False},
            {"name": "queue", "enabled": False},
        ]

    def prepare(self, plan: dict) -> dict:
        return {"backend": "local", "plan_id": plan.get("id"), "status": "ready"}

    def execute(self, plan: dict) -> dict:
        raise NotImplementedError("当前版本由 ReproducibleExperimentService 负责本地执行")

    def collect_artifacts(self, plan: dict) -> list[str]:
        return list(plan.get("artifacts", []))


experiment_backend = ExperimentBackend()
