from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import (
    ExperimentPlanRepository,
    ExperimentRunRepository,
    ResearchHypothesisRepository,
    RunEventRepository,
    RunRepository,
)
from .experiment_code_generator import experiment_code_generator
from .experiment_domain_service import experiment_domain_service
from .experiment_executor import experiment_executor_service
from .experiment_protocol_service import experiment_protocol_service
from .experiment_result_service import experiment_result_service
from .experiment_statistics_service import experiment_statistics_service
from .artifact_manifest_service import artifact_manifest_service
from .run_artifact_service import run_artifact_service


class ReproducibleExperimentService:
    async def run_for_task(self, task: dict, agent_id: str) -> dict:
        run_id = task.get("run_id")
        run = RunRepository.get_by_id(run_id) if run_id else None
        capability = experiment_domain_service.classify(task, run)
        if not capability["supported"]:
            return {
                "summary": capability["reason"], "experiment_ran": False, "publishable": False,
                "artifact_class": "unsupported", "unsupported_experiment_domain": True,
                "experiment_domain": capability["domain"], "metrics": {}, "artifacts": [],
                "next_steps": ["缩小课题到受支持实验域，或由人工提供领域实验模板与可信评测器。"],
            }
        protocol = experiment_protocol_service.ensure_for_task(task)
        workspace = self._workspace(run, task, agent_id)
        data_dir = workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        input_path = data_dir / "input_documents.jsonl"
        queries_path = data_dir / "evaluation_queries.json"
        metadata_path = data_dir / "dataset_metadata.json"
        repeat_path = data_dir / "repeat_metrics.jsonl"
        if repeat_path.exists():
            repeat_path.unlink()
        script_path = workspace / "run_experiment.py"
        artifact_class = self._write_input_documents(input_path, queries_path, metadata_path, task, run)
        script_source, generated = await self._resolve_script(task, run, protocol)
        script_path.write_text(script_source, encoding="utf-8")
        requirements_path = workspace / "requirements.txt"
        requirements_path.write_text(
            "# Core experiment uses Python standard library only.\n", encoding="utf-8"
        )
        environment_path = workspace / "environment.json"
        environment_path.write_text(
            json.dumps(
                {
                    "python_version": sys.version.split()[0],
                    "python_implementation": sys.implementation.name,
                    "required_third_party_packages": [],
                    "core_runtime": "python_standard_library",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        preregistration_path = workspace / "preregistration.md"
        preregistration_path.write_text(
            self._preregistration(protocol, input_path, queries_path), encoding="utf-8"
        )

        plan = self._create_plan(
            task, agent_id, workspace, input_path, queries_path, metadata_path, script_path,
            preregistration_path, requirements_path, environment_path, protocol,
        )
        experiment_run = self._create_run(task, protocol, plan, input_path)
        self._emit(task, plan["id"], "experiment.workspace_created", "实验研究生工作空间已创建", {"workspace": str(workspace)})

        started = datetime.now().isoformat()
        ExperimentRunRepository.update(experiment_run["id"], status="running", started_at=started)
        executed_plan = experiment_executor_service.execute_plan(plan["id"])
        result = executed_plan.get("result") or {}

        summary_path = workspace / "summary.json"
        results_path = data_dir / "results.csv"
        metrics = self._read_metrics(summary_path)
        statistics_result = experiment_statistics_service.analyze(self._read_jsonl(repeat_path), metrics)
        reproduction = self._reproduce(
            task, agent_id, workspace, input_path, queries_path, metadata_path, script_path, metrics
        )
        metrics["randomness_audit"] = {
            "retrieval_and_metrics": "deterministic; no random source is used",
            "execution_seeds": "reproduction labels only; they do not alter query sampling or scores",
            "bootstrap": "the only stochastic operation; isolated in analysis with seed 20260714",
            "optional_plot": "matplotlib/font cache is excluded from metric computation and pass criteria",
        }
        metrics.update(
            {
                "artifact_class": artifact_class,
                "trusted_evaluator": not generated,
                "statistical_analysis": statistics_result,
                "reproduction": reproduction,
                "publishable": (
                    artifact_class == "external" and not generated and statistics_result["passed"]
                    and result.get("sandboxed") is True and reproduction["passed"] and reproduction["sandboxed"]
                ),
            }
        )
        summary_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        chart_path = workspace / "chart_data.json"
        chart_path.write_text(json.dumps({"series": metrics.get("rows", []), "best_strategy": metrics.get("best_strategy")}, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_paths = [
            str(preregistration_path), str(requirements_path), str(environment_path),
            str(script_path), str(input_path), str(queries_path), str(metadata_path),
            str(repeat_path), str(results_path), str(summary_path), str(chart_path),
        ]
        strategy_metrics_path = data_dir / "strategy_metrics.csv"
        if strategy_metrics_path.exists():
            artifact_paths.append(str(strategy_metrics_path))
        artifact_paths.extend(reproduction.get("artifacts") or [])
        figure_path = workspace / "figure.png"
        has_figure = figure_path.exists()
        if has_figure:
            artifact_paths.append(str(figure_path))
        artifact_paths = [path for path in artifact_paths if Path(path).exists()]
        artifact_hashes = {
            str(Path(path).relative_to(workspace)): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in artifact_paths
            if (
                Path(path).is_file()
                and Path(path).is_relative_to(workspace)
                and Path(path) != summary_path
            )
        }
        hashes_path = workspace / "hashes.json"
        metrics["artifact_hashes"] = artifact_hashes
        metrics["artifact_integrity_manifest"] = str(hashes_path)
        metrics["preregistration_trace"] = {
            "path": str(preregistration_path),
            "workspace_relative_path": str(preregistration_path.relative_to(workspace)),
            "sha256": artifact_hashes[str(preregistration_path.relative_to(workspace))],
            "protocol_id": protocol["id"],
            "correspondence": [
                "research_question", "datasets", "metrics", "baselines", "method_details",
                "stopping_conditions", "expected_risks",
            ],
            "generated_before_execution": True,
        }
        # summary.json embeds this manifest, so hashing itself would be recursive.
        # Raw inputs, code, preregistration and result files remain fully hashed.
        summary_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        hashes_path.write_text(json.dumps(artifact_hashes, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_paths.append(str(hashes_path))
        for artifact_path in artifact_paths:
            artifact_manifest_service.register(
                run_artifact_service.run_dir(run, run_id),
                kind="experiment",
                path=artifact_path,
                metadata={"task_id": task.get("id"), "protocol_id": protocol["id"]},
            )
        status = executed_plan["status"]
        ExperimentRunRepository.update(experiment_run["id"], status=status, completed_at=datetime.now().isoformat())
        recorded = experiment_result_service.record(
            protocol=protocol,
            experiment_run={**experiment_run, "status": status},
            status=status,
            result=result,
            metrics=metrics,
            artifacts=artifact_paths,
        )
        self._emit(task, plan["id"], f"experiment.{status}", "实验脚本已执行" if status == "completed" else "实验脚本执行失败", {"artifacts": artifact_paths})

        return {
            "summary": "实验研究生已创建专属 workspace，并实际运行了可复现实验脚本。"
            + ("（脚本由 LLM 针对假设生成）" if generated else "（使用内置可复现脚本）"),
            "generated_code": generated,
            "experiment_ran": status == "completed",
            "protocol": protocol,
            "experiment_run": {**experiment_run, "status": status},
            "experiment_result": recorded["result"],
            "finding": recorded["finding"],
            "experiment_plan_id": plan["id"],
            "workspace_dir": str(workspace),
            "script_path": str(script_path),
            "preregistration_path": str(preregistration_path),
            "data_paths": {
                "input_documents": str(input_path),
                "evaluation_queries": str(queries_path),
                "dataset_metadata": str(metadata_path),
                "results_csv": str(results_path),
                "strategy_metrics_csv": str(strategy_metrics_path),
                "summary_json": str(summary_path),
                "chart_data_json": str(chart_path),
                **({"figure_png": str(figure_path)} if has_figure else {}),
            },
            "figure_path": str(figure_path) if has_figure else None,
            "metrics": metrics,
            "artifact_class": artifact_class,
            "publishable": metrics["publishable"],
            "experiment_domain": capability["domain"],
            "artifacts": artifact_paths,
            "artifact_hashes": artifact_hashes,
            "preregistration_trace": metrics["preregistration_trace"],
            "claims": [self._grounded_experiment_claim(metrics, protocol, artifact_hashes)],
            "execution": result,
            "reproduction": reproduction,
            "next_steps": ["如需扩大实验规模，可替换 data/input_documents.jsonl 并重新运行 run_experiment.py。"],
        }

    @staticmethod
    def _grounded_experiment_claim(metrics: dict, protocol: dict, artifact_hashes: dict) -> dict:
        rows = metrics.get("rows") or []
        baseline = next((row for row in rows if row.get("strategy") == "no_split"), {})
        best = metrics.get("best_strategy") or {}
        statistics_result = metrics.get("statistical_analysis") or {}
        baseline_mrr = baseline.get("mrr_at_10", baseline.get("mrr"))
        best_mrr = best.get("mrr_at_10", best.get("mrr"))
        sample_size = metrics.get("evaluated_query_count") or metrics.get("query_sample_size")
        uniform_effect_limit = (
            "该 pilot 的 query 和文档构造可能导致效应均匀，不得外推至非构造配置。"
            if statistics_result.get("uniform_effect_diagnostic")
            else ""
        )
        return {
            "statement": (
                f"在当前冻结的 {sample_size} 条 query 受控边界检索 pilot 中，"
                f"{best.get('strategy')} 的 MRR@10 为 {best_mrr}，no_split 为 {baseline_mrr}，"
                f"查询级配对均值差为 {statistics_result.get('mean_delta')}，"
                f"95% bootstrap 区间为 {statistics_result.get('confidence_interval_95')}。"
                "该结论仅限当前冻结 pilot，禁止外推至开放域、其他语料或其他检索器。"
                f"{uniform_effect_limit}"
            ),
            "evidence_source_ids": [],
            "evidence_passage_ids": [],
            "relation": "supports",
            "confidence": 0.9,
            "provenance": {
                "protocol_id": protocol["id"],
                "preregistration": "preregistration.md",
                "preregistration_sha256": artifact_hashes.get("preregistration.md"),
                "raw_results": "data/results.csv",
                "raw_results_sha256": artifact_hashes.get("data/results.csv"),
            },
        }

    async def _resolve_script(self, task: dict, run: dict | None, protocol: dict) -> tuple[str, bool]:
        if not settings.experiment_generated_code_enabled or settings.experiment_require_review:
            return self._script(), False
        hypothesis = ResearchHypothesisRepository.get_by_id(protocol["hypothesis_id"]) or {}
        goal = primary_goal((run or {}).get("research_goal", "") or task.get("description", ""))
        generated = await experiment_code_generator.generate(goal=goal, protocol=protocol, hypothesis=hypothesis)
        if generated:
            return generated, True
        return self._script(), False

    def _workspace(self, run: dict | None, task: dict, agent_id: str) -> Path:
        safe_title = re.sub(r'[\\/:*?"<>|#`]+', "", str(task.get("title") or task.get("id") or "experiment_task")).strip()
        return run_artifact_service.run_dir(run, task.get("run_id")) / "workspaces" / agent_id / f"{task.get('id')}_{safe_title[:24]}"

    def _create_plan(
        self, task: dict, agent_id: str, workspace: Path, input_path: Path,
        queries_path: Path, metadata_path: Path, script_path: Path, preregistration_path: Path,
        requirements_path: Path, environment_path: Path, protocol: dict,
    ) -> dict:
        now = datetime.now().isoformat()
        plan = {
            "id": f"exp_{uuid.uuid4().hex[:8]}",
            "run_id": task.get("run_id"),
            "task_id": task.get("id"),
            "agent_id": agent_id,
            "title": protocol["title"],
            "objective": protocol["research_question"],
            "workspace_dir": str(workspace),
            "files": [
                {"path": str(input_path.relative_to(workspace)), "content": input_path.read_text(encoding="utf-8")},
                {"path": str(queries_path.relative_to(workspace)), "content": queries_path.read_text(encoding="utf-8")},
                {"path": str(metadata_path.relative_to(workspace)), "content": metadata_path.read_text(encoding="utf-8")},
                {"path": str(script_path.relative_to(workspace)), "content": script_path.read_text(encoding="utf-8")},
                {"path": str(preregistration_path.relative_to(workspace)), "content": preregistration_path.read_text(encoding="utf-8")},
                {"path": requirements_path.name, "content": requirements_path.read_text(encoding="utf-8")},
                {"path": environment_path.name, "content": environment_path.read_text(encoding="utf-8")},
            ],
            "commands": [
                {
                    "command": f"{sys.executable} {script_path.name} --seed {index + 1}",
                    "description": f"固定种子确定性复现 {index + 1}",
                }
                for index in range(max(int(settings.experiment_repeat_runs), 1))
            ],
            "env_vars": {},
            "risk_level": "safe",
            "risk_reasons": [],
            "status": "approved",
            "result": None,
            "artifacts": [],
            "created_at": now,
            "updated_at": now,
            "approved_at": now,
            "approved_by": "run-level-human-approval" if settings.experiment_require_review else "system-safe-executor",
        }
        ExperimentPlanRepository.insert(plan)
        return plan

    @staticmethod
    def _preregistration(protocol: dict, input_path: Path, queries_path: Path) -> str:
        details = protocol.get("method_details") or {}
        return "\n".join([
            "# 实验预注册",
            "",
            f"- 协议 ID：`{protocol['id']}`",
            f"- 研究问题：{protocol['research_question']}",
            f"- 数据快照 SHA-256：`{hashlib.sha256(input_path.read_bytes()).hexdigest()}`",
            f"- Query/Qrel 快照 SHA-256：`{hashlib.sha256(queries_path.read_bytes()).hexdigest()}`",
            f"- 自变量：{', '.join(protocol.get('independent_variables') or [])}",
            f"- 因变量：{', '.join(protocol.get('dependent_variables') or [])}",
            f"- 基线：{json.dumps(protocol.get('baselines') or [], ensure_ascii=False)}",
            f"- 方法冻结项：{json.dumps(details, ensure_ascii=False, sort_keys=True)}",
            f"- 停止条件：{'；'.join(protocol.get('stopping_conditions') or [])}",
            f"- 预期风险与适用边界：{'；'.join(protocol.get('expected_risks') or [])}",
            "- 预期产物：run_experiment.py、input_documents.jsonl、evaluation_queries.json、"
            "requirements.txt、environment.json、repeat_metrics.jsonl、results.csv、summary.json、"
            "可选 figure.png、clean-room reproduction artifacts",
            "",
            "本文件在实验命令执行前生成；后续结果不得反向改写上述假设、数据、指标或停止条件。",
        ]) + "\n"

    def _create_run(self, task: dict, protocol: dict, plan: dict, input_path: Path) -> dict:
        now = datetime.now().isoformat()
        item = {
            "id": f"exp_run_{uuid.uuid4().hex[:10]}",
            "protocol_id": protocol["id"],
            "plan_id": plan["id"],
            "run_id": protocol["run_id"],
            "task_id": task.get("id"),
            "status": "pending",
            "command": plan["commands"][0]["command"] if plan.get("commands") else "",
            "dataset_snapshot": {
                "input_documents": str(input_path),
                "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                "size_bytes": input_path.stat().st_size,
                "datasets": protocol.get("datasets", []),
            },
            "started_at": None,
            "completed_at": None,
            "created_at": now,
        }
        ExperimentRunRepository.insert(item)
        return item

    def _reproduce(
        self,
        task: dict,
        agent_id: str,
        workspace: Path,
        input_path: Path,
        queries_path: Path,
        metadata_path: Path,
        script_path: Path,
        original_metrics: dict,
    ) -> dict:
        now = datetime.now().isoformat()
        reproduction_dir = workspace / "reproduction"
        plan = {
            "id": f"exp_reproduction_{uuid.uuid4().hex[:8]}", "run_id": task.get("run_id"),
            "task_id": task.get("id"), "agent_id": agent_id, "title": "干净目录独立复现",
            "objective": "在新工作目录复跑同一脚本与输入并比较主指标", "workspace_dir": str(reproduction_dir),
            "files": [
                {"path": "data/input_documents.jsonl", "content": input_path.read_text(encoding="utf-8")},
                {"path": "data/evaluation_queries.json", "content": queries_path.read_text(encoding="utf-8")},
                {"path": "data/dataset_metadata.json", "content": metadata_path.read_text(encoding="utf-8")},
                {"path": "run_experiment.py", "content": script_path.read_text(encoding="utf-8")},
            ],
            "commands": [{
                "command": f"{sys.executable} run_experiment.py --seed {max(int(settings.experiment_repeat_runs), 1)}",
                "description": "使用主实验末次固定种子独立复现",
            }],
            "env_vars": {}, "risk_level": "safe", "risk_reasons": [], "status": "approved",
            "result": None, "artifacts": [], "created_at": now, "updated_at": now,
            "approved_at": now, "approved_by": "run-level-human-approval",
        }
        ExperimentPlanRepository.insert(plan)
        executed = experiment_executor_service.execute_plan(plan["id"])
        reproduced = self._read_metrics(reproduction_dir / "summary.json")
        original_value = self._primary_value(original_metrics)
        reproduced_value = self._primary_value(reproduced)
        delta = abs(original_value - reproduced_value) if original_value is not None and reproduced_value is not None else None
        return {
            "plan_id": plan["id"], "status": executed["status"], "metric_delta": delta,
            "tolerance": settings.experiment_reproduction_tolerance,
            "passed": executed["status"] == "completed" and delta is not None and delta <= settings.experiment_reproduction_tolerance,
            "sandboxed": bool((executed.get("result") or {}).get("sandboxed")),
            "artifacts": [
                *(executed.get("artifacts") or []),
                *([str(reproduction_dir / "summary.json")] if (reproduction_dir / "summary.json").exists() else []),
            ],
        }

    @staticmethod
    def _primary_value(metrics: dict) -> float | None:
        best = metrics.get("best_strategy") or {}
        value = best.get("mrr_at_10") if best else metrics.get("treatment_value")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _write_input_documents(
        self, path: Path, queries_path: Path, metadata_path: Path, task: dict, run: dict | None
    ) -> str:
        goal = primary_goal((run or {}).get("research_goal", "") or task.get("description", ""))
        seed = goal or task.get("title", "research task")
        documents, queries, metadata = self._evaluation_dataset_from_uploads(run, task)
        if documents:
            with path.open("w", encoding="utf-8") as fh:
                for item in documents:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            queries_path.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return "external"

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
        queries_path.write_text(
            json.dumps(
                [
                    {"query": "固定长度切分 overlap 召回", "target_doc": "doc_chunk_overlap"},
                    {"query": "不切分 长文档 粒度 粗", "target_doc": "doc_no_split"},
                    {"query": "Top-3 Accuracy MRR 检索评估", "target_doc": "doc_metrics"},
                    {"query": "实验 workspace 脚本 输入数据 结果表", "target_doc": "doc_agent"},
                    {"query": "基线策略 对照 数据来源", "target_doc": "doc_baseline"},
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        metadata_path.write_text(
            json.dumps({"kind": "system_seed_demo", "uniform_query_template": False}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return "synthetic"

    def _evaluation_dataset_from_uploads(
        self, run: dict | None, task: dict
    ) -> tuple[list[dict], list[dict], dict]:
        if not run:
            return [], [], {}
        run_dir = run_artifact_service.run_dir(run, task.get("run_id"))
        attachments_path = run_dir / "inputs" / "attachments.json"
        if not attachments_path.exists():
            return [], [], {}
        try:
            items = json.loads(attachments_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [], [], {}
        attachments = items if isinstance(items, list) else []
        documents, queries = experiment_domain_service.labeled_dataset(attachments)
        metadata = {"kind": "uploaded_labeled_retrieval_dataset", "uniform_query_template": False}
        for item in attachments:
            raw = item.get("extracted_markdown") if isinstance(item, dict) else None
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                continue
            if isinstance(parsed.get("benchmark_design"), dict):
                metadata = parsed["benchmark_design"]
                break
        return documents, queries, metadata

    @staticmethod
    def _read_metrics(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except json.JSONDecodeError:
                continue
        return rows

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
import sys
from pathlib import Path


DATA_DIR = Path("data")
INPUT_PATH = DATA_DIR / "input_documents.jsonl"
QUERIES_PATH = DATA_DIR / "evaluation_queries.json"
METADATA_PATH = DATA_DIR / "dataset_metadata.json"
RESULTS_PATH = DATA_DIR / "results.csv"
STRATEGY_METRICS_PATH = DATA_DIR / "strategy_metrics.csv"
SUMMARY_PATH = Path("summary.json")
FIGURE_PATH = Path("figure.png")
REPEAT_PATH = DATA_DIR / "repeat_metrics.jsonl"


def plot_results(rows):
    """Render a grouped bar chart comparing strategies. No-op if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plotting skipped: {exc}")
        return False
    metrics = ["top1_accuracy", "top3_accuracy", "top5_accuracy", "mrr_at_10"]
    strategies = [row["strategy"] for row in rows]
    bar_width = 0.2
    positions = list(range(len(strategies)))
    fig, ax = plt.subplots(figsize=(8, 5))
    for offset, metric in enumerate(metrics):
        xs = [pos + offset * bar_width for pos in positions]
        ys = [row.get(metric, 0) for row in rows]
        ax.bar(xs, ys, width=bar_width, label=metric)
    ax.set_xticks([pos + 1.5 * bar_width for pos in positions])
    ax.set_xticklabels(strategies, rotation=15, ha="right")
    ax.set_ylabel("score")
    ax.set_title("Chunking strategy retrieval comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURE_PATH, dpi=120)
    plt.close(fig)
    print(f"figure saved: {FIGURE_PATH}")
    return True


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
    query_rows = []
    top1_hits = 0
    top3_hits = 0
    top5_hits = 0
    for query_index, query in enumerate(queries):
        document_scores = {}
        for chunk in chunks:
            value = score(query["query"], chunk)
            document_scores[chunk["doc_id"]] = max(value, document_scores.get(chunk["doc_id"], 0.0))
        ranked_docs = sorted(document_scores, key=lambda doc_id: (-document_scores[doc_id], doc_id))
        rank = next((idx + 1 for idx, doc_id in enumerate(ranked_docs) if doc_id == query["target_doc"]), None)
        if rank == 1:
            top1_hits += 1
        if rank and rank <= 3:
            top3_hits += 1
        if rank and rank <= 5:
            top5_hits += 1
        query_rows.append({
            "query_id": query.get("id", query_index),
            "target_doc": query["target_doc"],
            "rank": rank,
            "top1_hit": int(rank == 1),
            "top3_hit": int(bool(rank and rank <= 3)),
            "top5_hit": int(bool(rank and rank <= 5)),
            "reciprocal_rank_at_10": 1.0 / rank if rank and rank <= 10 else 0.0,
        })
    return ({
        "top1_accuracy": round(top1_hits / len(queries), 4),
        "top3_accuracy": round(top3_hits / len(queries), 4),
        "top5_accuracy": round(top5_hits / len(queries), 4),
        "mrr_at_10": round(sum(row["reciprocal_rank_at_10"] for row in query_rows) / len(query_rows), 4),
    }, query_rows)


def main():
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1
    docs = load_documents()
    query_pool = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    dataset_metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    if not query_pool:
        raise ValueError("evaluation_queries.json must contain at least one labeled query")
    queries = query_pool
    strategies = ["no_split", "fixed_100_no_overlap", "fixed_100_overlap_30"]
    rows = []
    per_query = {}
    for strategy in strategies:
        chunks = build_chunks(docs, strategy)
        metrics, query_rows = evaluate(chunks, queries)
        per_query[strategy] = query_rows
        rows.append({
            "strategy": strategy,
            "chunk_count": len(chunks),
            "avg_chunk_chars": round(sum(len(chunk["text"]) for chunk in chunks) / max(len(chunks), 1), 2),
            **metrics,
        })
    with RESULTS_PATH.open("w", encoding="utf-8", newline="") as fh:
        raw_rows = [
            {"strategy": strategy, **query_row}
            for strategy, query_rows in per_query.items()
            for query_row in query_rows
        ]
        writer = csv.DictWriter(fh, fieldnames=list(raw_rows[0].keys()))
        writer.writeheader()
        writer.writerows(raw_rows)
    with STRATEGY_METRICS_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    best = max(
        rows,
        key=lambda row: (
            row["mrr_at_10"], row["top1_accuracy"], row["top3_accuracy"],
            row["top5_accuracy"], -row["chunk_count"],
        ),
    )
    metric_fields = {
        "top1_accuracy": "top1_hit", "top3_accuracy": "top3_hit",
        "top5_accuracy": "top5_hit", "mrr_at_10": "reciprocal_rank_at_10",
    }
    paired_query_metric_deltas = {
        metric: [treatment[field] - baseline[field] for treatment, baseline in zip(
            per_query["fixed_100_overlap_30"], per_query["no_split"], strict=True
        )]
        for metric, field in metric_fields.items()
    }
    SUMMARY_PATH.write_text(
        json.dumps({
            "seed": seed,
            "evaluation": "paired_query_bootstrap",
            "retrieval_configuration": {
                "type": "deterministic_lexical_overlap",
                "document_aggregation": "maximum_chunk_score",
                "top_k": [1, 3, 5, 10],
                "shared_across_strategies": True,
                "rationale": "deterministic and parameter-free to isolate chunk-boundary effects",
            },
            "query_sample_size": len(query_pool),
            "evaluated_query_count": len(queries),
            "benchmark_design": dataset_metadata,
            "execution_seed_role": "deterministic reproduction label; no query resampling",
            "paired_query_deltas": paired_query_metric_deltas["mrr_at_10"],
            "paired_query_metric_deltas": paired_query_metric_deltas,
            "per_query_results": per_query,
            "rows": rows,
            "best_strategy": best,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    baseline = next(row for row in rows if row["strategy"] == "no_split")
    with REPEAT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "metric_name": "mrr_at_10",
            "seed": seed,
            "baseline_value": baseline["mrr_at_10"],
            "treatment_value": best["mrr_at_10"],
        }, ensure_ascii=False) + "\n")
    plot_results(rows)
    print(f"experiment completed: {len(rows)} strategies, best={best['strategy']}")


if __name__ == "__main__":
    main()
'''


reproducible_experiment_service = ReproducibleExperimentService()
