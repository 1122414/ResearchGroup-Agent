#!/usr/bin/env python3
"""ResearchGroup-Agent P0 功能烟测脚本。

用法:
    cd ResearchGroup-Agent
    python scripts/functional_p0_smoke.py

前提:
    后端必须已启动在 http://localhost:8000
"""

import sys
import time
import urllib.request
import urllib.error
import json

BASE_URL = "http://localhost:8000/api"


def req(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def health_check():
    print("[1/9] 健康检查...")
    resp = req("GET", "/health")
    assert resp.get("status") == "ok", f"健康检查失败: {resp}"
    print(f"    OK - mock_mode={resp.get('mock_mode')}, model={resp.get('model')}")


def settings_api():
    print("[2/9] 设置API...")
    resp = req("GET", "/settings")
    assert "mock_mode" in resp, "设置API缺少 mock_mode"
    assert "llm_model_name" in resp, "设置API缺少 llm_model_name"
    print(f"    OK - mock_mode={resp['mock_mode']}, model={resp['llm_model_name']}")


def create_and_run():
    print("[3/9] 创建并执行 Run...")
    goal = "研究一个可观测的多 Agent 课题组协作系统，要求能拆解任务、分配研究生 Agent、记录执行过程和生成阶段报告。"
    create_resp = req("POST", "/runs", {"research_goal": goal})
    run_id = create_resp["run_id"]
    assert run_id, "创建 Run 失败"
    print(f"    Created run_id={run_id}")

    start_resp = req("POST", f"/runs/{run_id}/start")
    print(f"    Started run, status={start_resp.get('status')}")
    return run_id


def poll_run(run_id: str, timeout: int = 60):
    print("[4/9] 轮询 Run 执行...")
    start_time = time.time()
    final_statuses = {"completed", "failed", "cancelled"}
    while time.time() - start_time < timeout:
        summary = req("GET", f"/runs/{run_id}/summary")
        status = summary.get("run", {}).get("status", "")
        counts = summary.get("counts", {})
        if counts.get("tasks_total", 0) > 0:
            print(
                f"    status={status}, tasks={counts.get('tasks_total')}, "
                f"completed={counts.get('tasks_completed')}, usage_calls={summary.get('usage', {}).get('total_llm_calls')}"
            )
        if status in final_statuses:
            print(f"    Run finished with status={status}")
            return summary
        time.sleep(2)
    raise TimeoutError("Run 执行超时")


def check_events(run_id: str):
    print("[5/9] 检查事件日志...")
    events_resp = req("GET", f"/runs/{run_id}/events?limit=200")
    events = events_resp.get("events", [])
    assert len(events) > 0, "没有事件日志"

    event_types = {e["event_type"] for e in events}
    required_types = {"run.created", "run.started", "phase.started", "phase.completed"}
    missing = required_types - event_types
    assert not missing, f"缺少事件类型: {missing}"

    print(f"    OK - 共 {len(events)} 条事件，包含 {len(event_types)} 种类型")


def check_usage(run_id: str):
    print("[6/9] 检查成本记录...")
    usage_resp = req("GET", f"/runs/{run_id}/usage")
    summary = usage_resp.get("summary", {})
    items = usage_resp.get("items", [])

    assert summary.get("total_llm_calls", 0) > 0, "没有 LLM 调用记录"
    assert "total_cost_usd" in summary, "缺少 total_cost_usd"
    assert "total_tokens" in summary, "缺少 total_tokens"

    print(f"    OK - {summary['total_llm_calls']} 次调用, ${summary['total_cost_usd']:.6f}, {summary['total_tokens']} tokens")


def check_tasks(run_id: str):
    print("[7/9] 检查任务数据...")
    tasks_resp = req("GET", f"/tasks?run_id={run_id}")
    tasks = tasks_resp.get("tasks", [])
    assert len(tasks) > 0, "没有任务"

    has_assignment_info = any(t.get("assignment_info") for t in tasks)
    has_subagent_flag = any(t.get("subagent_triggered") for t in tasks)

    print(f"    OK - {len(tasks)} 个任务, assignment_info={has_assignment_info}, subagent_triggered={has_subagent_flag}")


def check_outputs(run_id: str):
    print("[8/9] 检查输出...")
    outputs_resp = req("GET", f"/outputs?run_id={run_id}")
    outputs = outputs_resp.get("outputs", [])
    assert len(outputs) > 0, "没有输出"

    report = [o for o in outputs if o.get("output_type") == "final_report"]
    print(f"    OK - {len(outputs)} 个输出, 最终报告={len(report)} 个")


def check_cancel_unstarted():
    print("[9/10] 检查取消未开始 Run...")
    create_resp = req("POST", "/runs", {"research_goal": "测试取消接口-未开始"})
    run_id = create_resp["run_id"]

    cancel_resp = req("POST", f"/runs/{run_id}/cancel", {"reason": "功能测试"})
    status = cancel_resp.get("run", {}).get("status")
    assert status == "cancelled", f"取消后状态应为 cancelled, 实际是 {status}"
    print(f"    OK - 未开始 Run 可直接取消, status={status}")


def check_cancel_during_execution():
    print("[10/10] 检查执行中取消...")
    goal = "测试执行中取消功能"
    create_resp = req("POST", "/runs", {"research_goal": goal})
    run_id = create_resp["run_id"]

    req("POST", f"/runs/{run_id}/start")

    start_time = time.time()
    cancelled = False
    while time.time() - start_time < 30:
        summary = req("GET", f"/runs/{run_id}/summary")
        status = summary.get("run", {}).get("status", "")
        if status in ("decomposing", "scheduling", "executing"):
            cancel_resp = req("POST", f"/runs/{run_id}/cancel", {"reason": "测试中途中止"})
            cancel_status = cancel_resp.get("run", {}).get("status")
            assert cancel_status == "cancelling", f"执行中取消应返回 cancelling, 实际是 {cancel_status}"
            cancelled = True
            break
        time.sleep(1)

    if not cancelled:
        req("POST", f"/runs/{run_id}/cancel", {"reason": "测试取消"})
        cancelled = True

    start_time = time.time()
    while time.time() - start_time < 15:
        summary = req("GET", f"/runs/{run_id}/summary")
        status = summary.get("run", {}).get("status", "")
        if status in ("cancelled", "completed"):
            print(f"    OK - 执行中取消成功, 最终状态={status}")
            return
        time.sleep(1)

    raise TimeoutError("执行中取消后未能在预期时间内到达最终状态")


def check_office_state(run_id: str):
    print("[额外] 检查像素办公室 API...")
    resp = req("GET", f"/monitor/office-state?run_id={run_id}")
    assert "run" in resp, "缺少 run 字段"
    assert "agents" in resp, "缺少 agents 字段"
    assert "tasks" in resp, "缺少 tasks 字段"
    agents = resp.get("agents", [])
    assert len(agents) > 0, "agents 为空"
    assert all("activity_state" in a for a in agents), "Agent 缺少 activity_state"
    print(f"    OK - {len(agents)} 个 Agent, {len(resp.get('tasks', []))} 个任务")


def main():
    print("=" * 60)
    print("ResearchGroup-Agent P0 功能烟测")
    print("=" * 60)

    try:
        health_check()
        settings_api()
        run_id = create_and_run()
        summary = poll_run(run_id)
        check_events(run_id)
        check_usage(run_id)
        check_tasks(run_id)
        check_outputs(run_id)
        check_cancel_unstarted()
        check_cancel_during_execution()
        check_office_state(run_id)

        print("\n" + "=" * 60)
        print("全部通过")
        print("=" * 60)
        return 0
    except AssertionError as exc:
        print(f"\n失败: {exc}")
        return 1
    except urllib.error.URLError as exc:
        print(f"\n连接失败: {exc}")
        print("请确保后端已启动: cd backend && python main.py")
        return 1
    except Exception as exc:
        print(f"\n错误: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
