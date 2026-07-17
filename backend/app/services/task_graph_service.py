from __future__ import annotations

from collections import defaultdict, deque

from fastapi import HTTPException

from ..storage.repositories import TaskDependencyRepository, TaskRepository


class TaskGraphService:
    def build_default_graph(self, tasks: list[dict]) -> None:
        by_type: dict[str, list[dict]] = defaultdict(list)
        for task in tasks:
            by_type[task.get("task_type", "")].append(task)

        literature = [task["id"] for task in by_type.get("literature_survey", [])]
        design = [task["id"] for task in by_type.get("research_design", [])]
        system = [task["id"] for task in by_type.get("system_design", [])]
        acquisition = [task["id"] for task in by_type.get("data_acquisition", [])]
        experiments = [task["id"] for task in by_type.get("experiment_design", [])]
        analysis = [task["id"] for task in by_type.get("result_analysis", [])]

        for task in tasks:
            deps: list[str] = []
            task_type = task.get("task_type")
            if task_type in {"system_design", "research_design"}:
                deps = literature
            elif task_type == "data_acquisition":
                deps = literature + design + system
            elif task_type == "experiment_design":
                deps = literature + design + system
            elif task_type == "result_analysis":
                deps = acquisition or experiments or design or system or literature
            elif task_type == "report_writing":
                deps = [item["id"] for item in tasks if item["id"] != task["id"] and item.get("task_type") != "report_writing"]
            TaskDependencyRepository.replace_for_task(task["id"], list(dict.fromkeys(deps)))

        self.recompute_critical_path(tasks[0]["run_id"] if tasks else "")

    def set_dependencies(self, task_id: str, dependencies: list[str]) -> dict:
        task = TaskRepository.get_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        run_tasks = TaskRepository.get_all(run_id=task.get("run_id"))
        valid_ids = {item["id"] for item in run_tasks}
        if task_id in dependencies:
            raise HTTPException(status_code=400, detail="任务不能依赖自身")
        unknown = [item for item in dependencies if item not in valid_ids]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知依赖任务: {', '.join(unknown)}")

        original = TaskDependencyRepository.get_for_task(task_id)
        TaskDependencyRepository.replace_for_task(task_id, dependencies)
        if self._has_cycle(run_tasks):
            TaskDependencyRepository.replace_for_task(task_id, original)
            raise HTTPException(status_code=400, detail="任务依赖不能形成环")
        self.recompute_critical_path(task.get("run_id"))
        return self.get_graph(task.get("run_id"))

    def get_graph(self, run_id: str) -> dict:
        tasks = TaskRepository.get_all(run_id=run_id)
        dependencies = TaskDependencyRepository.get_by_run(run_id)
        adjacency: dict[str, list[str]] = defaultdict(list)
        for item in dependencies:
            adjacency[item["depends_on_task_id"]].append(item["task_id"])
        return {
            "nodes": tasks,
            "edges": dependencies,
            "ready_task_ids": [task["id"] for task in self.ready_tasks(tasks)],
            "critical_path_task_ids": [task["id"] for task in tasks if task.get("is_critical_path")],
            "adjacency": dict(adjacency),
        }

    def ready_tasks(self, tasks: list[dict]) -> list[dict]:
        status_map = {task["id"]: task.get("status") for task in tasks}
        latest_thesis_revisions: dict[str, dict] = {}
        for task in tasks:
            root_id = task.get("revision_of_task_id")
            if not root_id or task.get("task_type") != "thesis_chapter":
                continue
            current = latest_thesis_revisions.get(root_id)
            if not current or (
                str(task.get("created_at") or ""), task["id"]
            ) > (
                str(current.get("created_at") or ""), current["id"]
            ):
                latest_thesis_revisions[root_id] = task
        pending_revisions = {
            task["revision_of_task_id"]
            for task in tasks
            if task.get("revision_of_task_id")
            and task.get("status") in {
                "pending", "assigned", "blocked", "running",
                "waiting_subagent", "waiting_review", "need_revision",
            }
        }
        ready: list[dict] = []
        for task in tasks:
            # need_revision means the reviewed attempt is waiting for a newer
            # revision task. Re-running that same attempt creates a revision
            # cycle and bypasses the configured round limit.
            if task.get("status") not in {"pending", "assigned", "blocked"}:
                continue
            root_id = task.get("revision_of_task_id")
            root_status = status_map.get(root_id)
            recoverable_latest_thesis = (
                root_status == "failed"
                and task.get("task_type") == "thesis_chapter"
                and latest_thesis_revisions.get(root_id, {}).get("id") == task["id"]
            )
            if (
                root_id
                and root_status in {"completed", "failed", "archived"}
                and not recoverable_latest_thesis
            ):
                TaskRepository.update_status(
                    task["id"],
                    "archived",
                    blocked_reason="根任务已终态，该返工分支已失效。",
                )
                continue
            if task["id"] in pending_revisions:
                continue
            deps = TaskDependencyRepository.get_for_task(task["id"])
            incomplete = [dep for dep in deps if status_map.get(dep) != "completed"]
            if incomplete:
                TaskRepository.update_status(task["id"], "blocked", blocked_reason=f"等待前置任务完成: {', '.join(incomplete)}")
                continue
            if task.get("status") == "blocked":
                TaskRepository.update_status(task["id"], "pending", blocked_reason=None)
                task = TaskRepository.get_by_id(task["id"]) or task
            ready.append(task)
        return ready

    def topological_order(self, tasks: list[dict]) -> list[dict]:
        task_map = {task["id"]: task for task in tasks}
        edges = TaskDependencyRepository.get_by_run(tasks[0]["run_id"]) if tasks else []
        indegree = {task_id: 0 for task_id in task_map}
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge["depends_on_task_id"]].append(edge["task_id"])
            indegree[edge["task_id"]] += 1
        queue = deque(sorted([task_id for task_id, degree in indegree.items() if degree == 0]))
        ordered: list[dict] = []
        while queue:
            task_id = queue.popleft()
            ordered.append(task_map[task_id])
            for child in adjacency[task_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if len(ordered) != len(tasks):
            raise HTTPException(status_code=400, detail="任务依赖存在环")
        return ordered

    def descendants(self, run_id: str, task_id: str) -> list[str]:
        edges = TaskDependencyRepository.get_by_run(run_id)
        children: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            children[edge["depends_on_task_id"]].append(edge["task_id"])
        result: list[str] = []
        queue = deque(children.get(task_id, []))
        seen: set[str] = set()
        while queue:
            child = queue.popleft()
            if child in seen:
                continue
            seen.add(child)
            result.append(child)
            queue.extend(children.get(child, []))
        return result

    def recompute_critical_path(self, run_id: str) -> None:
        if not run_id:
            return
        tasks = TaskRepository.get_all(run_id=run_id)
        if not tasks:
            return
        edges = TaskDependencyRepository.get_by_run(run_id)
        parents: dict[str, list[str]] = defaultdict(list)
        children: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            parents[edge["task_id"]].append(edge["depends_on_task_id"])
            children[edge["depends_on_task_id"]].append(edge["task_id"])
        order = self.topological_order(tasks)
        distance: dict[str, int] = {}
        predecessor: dict[str, str | None] = {}
        for task in order:
            task_id = task["id"]
            if not parents[task_id]:
                distance[task_id] = task.get("complexity", 1)
                predecessor[task_id] = None
                continue
            parent = max(parents[task_id], key=lambda item: distance.get(item, 0))
            distance[task_id] = distance.get(parent, 0) + task.get("complexity", 1)
            predecessor[task_id] = parent
        tail = max(distance, key=distance.get)
        path: set[str] = set()
        current: str | None = tail
        while current:
            path.add(current)
            current = predecessor.get(current)
        for task in tasks:
            TaskRepository.update_status(task["id"], task.get("status"), is_critical_path=task["id"] in path)

    def _has_cycle(self, tasks: list[dict]) -> bool:
        try:
            self.topological_order(tasks)
            return False
        except HTTPException:
            return True


task_graph_service = TaskGraphService()
