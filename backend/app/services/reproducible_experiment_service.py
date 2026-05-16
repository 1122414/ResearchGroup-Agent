from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from ..core.research_goal import primary_goal
from ..storage.repositories import ExperimentPlanRepository, RunEventRepository, RunRepository
from .run_artifact_service import run_artifact_service


class ReproducibleExperimentService:
    def run_for_task(self, task: dict, agent_id: str) -> dict:
        run_id = task.get("run_id")
        run = RunRepository.get_by_id(run_id) if run_id else None
        workspace = self._workspace(run, task, agent_id)
        data_dir = workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        input_path = data_dir / "input_documents.jsonl"
        script_path = workspace / "run_experiment.py"
        self._write_input_documents(input_path, task, run)
        script_path.write_text(self._script(), encoding="utf-8")

        plan = self._create_plan(task, agent_id, workspace, input_path, script_path)
        self._emit(task, plan["id"], "experiment.workspace_created", "实验研究生工作空间已创建", {"workspace": str(workspace)})

        started = datetime.now().isoformat()
        ExperimentPlanRepository.update(plan["id"], {"status": "running", "updated_at": started})
        proc = subprocess.run(
            [sys.executable, str(script_path.name)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=120,
        )
        result = {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-20000:],
            "elapsed_ms": 0,
            "command_results": [
                {
                    "command": f"{sys.executable} {script_path.name}",
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[-20000:],
                    "stderr": proc.stderr[-20000:],
                }
            ],
        }

        summary_path = workspace / "summary.json"
        results_path = data_dir / "results.csv"
        metrics = self._read_metrics(summary_path)
        chart_path = workspace / "chart_data.json"
        chart_path.write_text(json.dumps({"series": metrics.get("rows", []), "best_strategy": metrics.get("best_strategy")}, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_paths = [str(script_path), str(input_path), str(results_path), str(summary_path), str(chart_path)]
        status = "completed" if proc.returncode == 0 else "failed"
        ExperimentPlanRepository.update(
            plan["id"],
            {
                "status": status,
                "result": result,
                "artifacts": artifact_paths,
                "updated_at": datetime.now().isoformat(),
            },
        )
        self._emit(task, plan["id"], f"experiment.{status}", "实验脚本已执行" if status == "completed" else "实验脚本执行失败", {"artifacts": artifact_paths})

        return {
            "summary": "实验研究生已创建专属 workspace，并实际运行了可复现实验脚本。",
            "experiment_ran": status == "completed",
            "experiment_plan_id": plan["id"],
            "workspace_dir": str(workspace),
            "script_path": str(script_path),
            "data_paths": {
                "input_documents": str(input_path),
                "results_csv": str(results_path),
                "summary_json": str(summary_path),
                "chart_data_json": str(chart_path),
            },
            "metrics": metrics,
            "artifacts": artifact_paths,
            "execution": result,
            "next_steps": ["如需扩大实验规模，可替换 data/input_documents.jsonl 并重新运行 run_experiment.py。"],
        }

    def _workspace(self, run: dict | None, task: dict, agent_id: str) -> Path:
        safe_title = re.sub(r'[\\/:*?"<>|#`]+', "", str(task.get("title") or task.get("id") or "experiment_task")).strip()
        return run_artifact_service.run_dir(run, task.get("run_id")) / "workspaces" / agent_id / f"{task.get('id')}_{safe_title[:24]}"

    def _create_plan(self, task: dict, agent_id: str, workspace: Path, input_path: Path, script_path: Path) -> dict:
        now = datetime.now().isoformat()
        plan = {
            "id": f"exp_{uuid.uuid4().hex[:8]}",
            "run_id": task.get("run_id"),
            "task_id": task.get("id"),
            "agent_id": agent_id,
            "title": f"可复现实验：{task.get('title', '')}",
            "objective": task.get("description", ""),
            "workspace_dir": str(workspace),
            "files": [
                {"path": str(input_path.relative_to(workspace)), "content": input_path.read_text(encoding="utf-8")},
                {"path": str(script_path.relative_to(workspace)), "content": script_path.read_text(encoding="utf-8")},
            ],
            "commands": [{"command": f"{sys.executable} {script_path.name}", "description": "运行实验脚本并生成 results.csv/summary.json"}],
            "env_vars": {},
            "risk_level": "safe",
            "risk_reasons": [],
            "status": "draft",
            "result": None,
            "artifacts": [],
            "created_at": now,
            "updated_at": now,
            "approved_at": now,
            "approved_by": "system-safe-executor",
        }
        ExperimentPlanRepository.insert(plan)
        return plan

    def _write_input_documents(self, path: Path, task: dict, run: dict | None) -> None:
        goal = primary_goal((run or {}).get("research_goal", "") or task.get("description", ""))
        seed = goal or task.get("title", "research task")
        documents = [
            {"id": "doc_rag", "text": f"{seed} 需要比较 RAG 检索、文本切分、召回率、MRR 和答案质量之间的关系。"},
            {"id": "doc_chunk_short", "text": "固定长度切分实现简单，但可能切断语义边界；无 overlap 时召回容易下降。"},
            {"id": "doc_chunk_overlap", "text": "带 overlap 的固定长度切分能保留跨边界上下文，但会增加 chunk 数和检索成本。"},
            {"id": "doc_no_split", "text": "不切分策略把整篇文档作为 chunk，数量少但粒度粗，长文档容易稀释关键词。"},
            {"id": "doc_metrics", "text": "Top-1 Accuracy、Top-3 Accuracy 和 MRR 可用于评估检索命中与排序质量。"},
            {"id": "doc_agent", "text": "多 Agent 研究流程应保留脚本、输入数据、结果表和实验摘要，保证可复现。"},
            {"id": "doc_baseline", "text": "实验需要包含基线策略、对照策略和清晰的数据来源。"},
            {"id": "doc_report", "text": "最终报告应该引用实验 workspace 中的 results.csv 和 summary.json。"},
        ]
        with path.open("w", encoding="utf-8") as fh:
            for item in documents:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_metrics(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _emit(task: dict, plan_id: str, event_type: str, title: str, payload: dict) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        RunEventRepository.insert(
            {
                "id": f"evt_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "task_id": task.get("id"),
                "agent_id": task.get("owner_agent"),
                "event_type": event_type,
                "phase": "experiment",
                "title": title,
                "message": plan_id,
                "payload": payload,
                "created_at": datetime.now().isoformat(),
            }
        )

    @staticmethod
    def _script() -> str:
        return r'''import csv
import json
import math
import re
from pathlib import Path


DATA_DIR = Path("data")
INPUT_PATH = DATA_DIR / "input_documents.jsonl"
RESULTS_PATH = DATA_DIR / "results.csv"
SUMMARY_PATH = Path("summary.json")


def tokenize(text):
    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def load_documents():
    docs = []
    with INPUT_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                docs.append(json.loads(line))
    return docs


def chunk_text(text, size, overlap):
    if size <= 0:
        return [text]
    chunks = []
    step = max(size - overlap, 1)
    for start in range(0, len(text), step):
        chunk = text[start:start + size]
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks


def build_chunks(docs, strategy):
    chunks = []
    for doc in docs:
        if strategy == "no_split":
            pieces = [doc["text"]]
        elif strategy == "fixed_100_no_overlap":
            pieces = chunk_text(doc["text"], 100, 0)
        else:
            pieces = chunk_text(doc["text"], 100, 30)
        for index, piece in enumerate(pieces):
            chunks.append({"doc_id": doc["id"], "chunk_id": f"{doc['id']}#{index}", "text": piece})
    return chunks


def score(query, chunk):
    q = tokenize(query)
    c = tokenize(chunk["text"])
    if not q or not c:
        return 0.0
    return len(q & c) / math.sqrt(len(q) * len(c))


def evaluate(chunks, queries):
    reciprocal_ranks = []
    top1_hits = 0
    top3_hits = 0
    for query in queries:
        ranked = sorted(chunks, key=lambda chunk: score(query["query"], chunk), reverse=True)
        rank = next((idx + 1 for idx, chunk in enumerate(ranked) if chunk["doc_id"] == query["target_doc"]), None)
        if rank == 1:
            top1_hits += 1
        if rank and rank <= 3:
            top3_hits += 1
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    return {
        "top1_accuracy": round(top1_hits / len(queries), 4),
        "top3_accuracy": round(top3_hits / len(queries), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
    }


def main():
    docs = load_documents()
    queries = [
        {"query": "固定长度切分 overlap 召回", "target_doc": "doc_chunk_overlap"},
        {"query": "不切分 长文档 粒度 粗", "target_doc": "doc_no_split"},
        {"query": "Top-3 Accuracy MRR 检索评估", "target_doc": "doc_metrics"},
        {"query": "实验 workspace 脚本 输入数据 结果表", "target_doc": "doc_agent"},
        {"query": "基线策略 对照 数据来源", "target_doc": "doc_baseline"},
    ]
    strategies = ["no_split", "fixed_100_no_overlap", "fixed_100_overlap_30"]
    rows = []
    for strategy in strategies:
        chunks = build_chunks(docs, strategy)
        metrics = evaluate(chunks, queries)
        rows.append({
            "strategy": strategy,
            "chunk_count": len(chunks),
            "avg_chunk_chars": round(sum(len(chunk["text"]) for chunk in chunks) / max(len(chunks), 1), 2),
            **metrics,
        })
    with RESULTS_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    best = max(rows, key=lambda row: (row["top3_accuracy"], row["mrr"], -row["chunk_count"]))
    SUMMARY_PATH.write_text(json.dumps({"rows": rows, "best_strategy": best}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"experiment completed: {len(rows)} strategies, best={best['strategy']}")


if __name__ == "__main__":
    main()
'''


reproducible_experiment_service = ReproducibleExperimentService()
