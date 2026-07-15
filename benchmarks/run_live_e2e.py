from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request


def _filler(label: str, length: int) -> str:
    tokens = " ".join(f"{label}{index:02d}" for index in range(80)) + " "
    return (tokens * ((length // len(tokens)) + 1))[:length]


def _build_dataset() -> dict:
    documents = []
    queries = []
    for index in range(20):
        keys = [f"a{index:02d}", f"b{index:02d}", f"c{index:02d}", f"d{index:02d}"]
        target_id = f"target_{index:02d}"
        documents.extend([
            {
                "id": target_id,
                # The four relevant terms straddle the 100-character boundary:
                # no-overlap splits them 2+2, while a 30-character overlap keeps
                # them together. Long unique context also makes no-split retrieval
                # measurably harder instead of producing a degenerate all-ones run.
                "text": _filler(f"t{index:02d}x", 91) + " " + " ".join(keys) + " " + _filler(f"t{index:02d}y", 208),
            },
            {
                "id": f"distractor_{index:02d}",
                "text": " ".join(keys[:3]) + " " + _filler(f"n{index:02d}", 68),
            },
        ])
        queries.append({"query": " ".join(keys), "target_doc": target_id})
    return {
    "license": "user_owned_for_research",
    "ethics_review": "not_required",
        "benchmark_design": {
            "kind": "controlled_boundary_retrieval_pilot",
            "documents": len(documents), "queries": len(queries),
            "target_min_chars": 300, "frozen_chunk_boundary": 100,
        },
        "documents": documents,
        "queries": queries,
    }


DATASET = _build_dataset()


def validate_dataset(dataset: dict) -> None:
    documents = {item["id"]: item for item in dataset.get("documents") or []}
    queries = dataset.get("queries") or []
    if len(documents) < 40 or len(queries) < 20:
        raise ValueError("live acceptance dataset must contain at least 40 documents and 20 qrels")
    if any(query.get("target_doc") not in documents for query in queries):
        raise ValueError("every live acceptance query must have a valid qrel target")
    if any(len(documents[query["target_doc"]]["text"]) < 300 for query in queries):
        raise ValueError("target documents must be long enough for chunking strategies to differ")
    for query in queries:
        terms = query["query"].split()
        text = documents[query["target_doc"]]["text"]
        if not all(term in text[70:170] for term in terms):
            raise ValueError("overlap window must preserve every qrel term")
        if all(term in text[:100] for term in terms) or all(term in text[100:200] for term in terms):
            raise ValueError("qrel terms must straddle the frozen no-overlap boundary")


def request(base_url: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base_url + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    attempts = 3 if method == "GET" else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(1)
    raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one live, bounded retrieval-research acceptance case.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--approve-experiment", action="store_true")
    parser.add_argument("--run-id", default="", help="Monitor and continue an existing live run.")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    validate_dataset(DATASET)
    if args.run_id:
        run_id = args.run_id
        existing = request(args.base_url, "GET", f"/runs/{run_id}")["run"]
        print(json.dumps({"event": "resumed", "run_id": run_id, "artifact_dir": existing["artifact_dir"]}, ensure_ascii=False), flush=True)
    else:
        encoded = base64.b64encode(json.dumps(DATASET, ensure_ascii=False).encode("utf-8")).decode("ascii")
        created = request(
            args.base_url, "POST", "/runs",
            {
            "research_goal": (
                "在用户提供的 40 文档、20 条 query/qrel 的受控中文 RAG 检索基准上，比较整文档、固定长度无重叠和"
                "固定长度重叠切分策略的 MRR 与 Top-k accuracy。冻结数据、基线、指标和停止条件，"
                "只使用可核验全文 passage 形成相关工作结论，执行至少三次固定种子 bootstrap，"
                "在干净目录独立复现，并生成带限制与逐项追溯附录的论文草稿。该数据是受控边界检索 pilot，"
                "不允许把结论外推到开放域真实语料。"
            ),
            "attachments": [{
                "name": "retrieval_benchmark.json", "mime_type": "application/json",
                "size": len(encoded), "data_url": "data:application/json;base64," + encoded,
            }],
            },
        )
        run_id = created["run_id"]
        print(json.dumps({"event": "created", "run_id": run_id, "artifact_dir": created["artifact_dir"]}, ensure_ascii=False), flush=True)
        request(args.base_url, "POST", f"/runs/{run_id}/start", {})
    deadline = time.time() + args.timeout
    resolved: set[str] = set()
    last_status = ""
    while time.time() < deadline:
        snapshot = request(args.base_url, "GET", f"/runs/{run_id}")
        run = snapshot["run"]
        if run["status"] != last_status:
            print(json.dumps({"event": "status", "status": run["status"], "step": run.get("current_step")}, ensure_ascii=False), flush=True)
            last_status = run["status"]
        if run["status"] in {"completed", "failed", "cancelled"}:
            print(json.dumps({"event": "finished", "run": run, "tasks": snapshot["tasks"]}, ensure_ascii=False), flush=True)
            return 0 if run["status"] == "completed" else 2
        if run["status"] == "waiting_confirmation":
            approvals = request(args.base_url, "GET", f"/runs/{run_id}/approvals")["items"]
            pending = [item for item in approvals if item["status"] == "pending"]
            for item in pending:
                if item["id"] in resolved:
                    continue
                print(json.dumps({"event": "approval", "id": item["id"], "type": item["request_type"], "message": item["message"]}, ensure_ascii=False), flush=True)
                if item["request_type"] == "experiment_execute" and args.approve_experiment:
                    request(
                        args.base_url, "POST", f"/runs/approvals/{item['id']}/resolve",
                        {"approved": True, "resolved_by": "live-e2e-human-approved"},
                    )
                    resolved.add(item["id"])
                else:
                    return 3
        time.sleep(2)
    print(json.dumps({"event": "timeout", "run_id": run_id}, ensure_ascii=False), flush=True)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
