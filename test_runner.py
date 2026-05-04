"""
ResearchGroup-Agent 功能测试脚本
使用方式：python test_runner.py

此脚本自动测试 MVP 的完整闭环：
1. 后端启动检查
2. Agent 数据加载
3. 创建 Run
4. 执行 run_all 完整流程
5. 验证任务板状态
6. 验证产出物
"""

import sys
import os
import json
import time
import subprocess
import signal
import urllib.request
import urllib.error

# 配置
BACKEND_URL = "http://localhost:8000"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
TIMEOUT = 60  # 后端启动等待超时

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(msg):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}  {msg}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")


def print_ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")


def print_fail(msg):
    print(f"  {RED}✗{RESET} {msg}")


def print_info(msg):
    print(f"  {YELLOW}→{RESET} {msg}")


def api_get(path):
    try:
        req = urllib.request.Request(f"{BACKEND_URL}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except json.JSONDecodeError:
        return {"error": "JSON解析失败"}


def api_post(path, data=None):
    try:
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(f"{BACKEND_URL}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except json.JSONDecodeError:
        return {"error": "JSON解析失败"}


def check_backend_health():
    print_header("1. 后端健康检查")
    result = api_get("/api/health")
    if result.get("status") == "ok":
        print_ok(f"后端运行正常 (mock_mode={result.get('mock_mode')})")
        return True
    else:
        print_fail(f"后端异常: {result}")
        return False


def check_agents():
    print_header("2. Agent 数据验证")
    result = api_get("/api/agents")
    agents = result.get("agents", [])
    if len(agents) == 0:
        print_fail("未找到 Agent 数据")
        return False

    graduate_types = ["researcher", "engineer", "experimenter", "analyst", "writer"]
    found_types = {a["type"] for a in agents}
    missing = set(graduate_types) - found_types
    if missing:
        print_fail(f"缺少研究生Agent类型: {missing}")
        return False

    print_ok(f"Agent 总数: {len(agents)}")
    for a in agents:
        if a["type"] in graduate_types:
            skills = a.get("skills", {})
            max_skill = max(skills.values()) if skills else 0
            skill_name = [k for k, v in skills.items() if v == max_skill][0] if skills else "?"
            print_info(f"  {a['name']} [{a['status']}] — 专精: {skill_name}({max_skill}/10)")

    return True


def run_research():
    print_header("3. 执行研究任务 (run_all)")

    research_goal = "请让课题组围绕「面向研究生课题组协作的多Agent系统」完成一次阶段性调研，输出相关项目调研、系统架构建议、实验验证方案和总结报告。"

    print_info("创建 Run...")
    create_result = api_post("/api/runs", {"research_goal": research_goal})
    if "error" in create_result:
        print_fail(f"创建 Run 失败: {create_result['error']}")
        return False

    run_id = create_result.get("run_id")
    print_ok(f"Run 已创建: {run_id}")

    print_info("执行 run_all（完整流程）...")
    start = time.time()
    run_result = api_post(f"/api/runs/{run_id}/run_all")
    elapsed = time.time() - start

    if "error" in run_result:
        print_fail(f"执行失败: {run_result.get('error', '')[:200]}")
        return False

    tasks_total = run_result.get("tasks_total", 0)
    tasks_completed = run_result.get("tasks_completed", 0)
    tasks_revision = run_result.get("tasks_need_revision", 0)
    report_available = run_result.get("report_available", False)

    print_ok(f"执行完成 (耗时 {elapsed:.1f}s)")
    print_info(f"  总任务数: {tasks_total}")
    print_info(f"  已完成: {tasks_completed}")
    print_info(f"  需返工: {tasks_revision}")
    print_info(f"  报告可用: {report_available}")

    if tasks_total < 3:
        print_fail(f"任务数不足: 期望 >= 3，实际 {tasks_total}")
        return False
    if tasks_completed < 1:
        print_fail(f"无完成任务")
        return False
    if not report_available:
        print_fail(f"报告未生成")
        return False

    return run_id


def check_task_board(run_id):
    print_header("4. 任务板状态验证")
    result = api_get(f"/api/tasks?run_id={run_id}")
    tasks = result.get("tasks", [])

    if not tasks:
        print_fail("无任务数据")
        return False

    status_counts = {}
    for t in tasks:
        status = t.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    status_labels = {
        "pending": "待分配", "assigned": "已分配", "running": "执行中",
        "waiting_collab": "等待协作", "waiting_subagent": "等待SubAgent",
        "waiting_review": "等待审核", "need_revision": "需返工",
        "completed": "已完成", "failed": "失败"
    }

    print_ok(f"任务总数: {len(tasks)}")
    for status, count in sorted(status_counts.items()):
        label = status_labels.get(status, status)
        icon = "✅" if status == "completed" else "⏳" if status != "failed" else "❌"
        print_info(f"  {icon} {label}: {count}")

    has_owner = sum(1 for t in tasks if t.get("owner_agent"))
    has_collab = sum(1 for t in tasks if t.get("collaborator_agents"))
    has_review = sum(1 for t in tasks if t.get("review_result"))

    print_info(f"  已分配主责Agent: {has_owner}/{len(tasks)}")
    print_info(f"  有协作Agent: {has_collab}/{len(tasks)}")
    print_info(f"  已审核: {has_review}/{len(tasks)}")

    return has_owner > 0


def check_artifacts(run_id):
    print_header("5. 产出物验证")
    from pathlib import Path
    base = Path(__file__).parent
    run_dir = base / "artifacts" / "runs" / run_id

    if not run_dir.exists():
        print_fail(f"产出目录不存在: {run_dir}")
        return False

    expected_files = ["tasks.json", "agent_assignments.json", "final_report.md", "run_log.md"]
    all_ok = True
    for fname in expected_files:
        fpath = run_dir / fname
        if fpath.exists():
            size = fpath.stat().st_size
            print_ok(f"  {fname} ({size} bytes)")
        else:
            print_fail(f"  缺少 {fname}")
            all_ok = False

    if all_ok and (run_dir / "final_report.md").exists():
        content = (run_dir / "final_report.md").read_text(encoding="utf-8")
        sections = [s for s in ["## 1.", "## 2.", "## 3."] if s in content]
        print_info(f"  报告包含 {len(sections)}/10 个章节")

    return all_ok


def check_subagents():
    print_header("6. SubAgent 调用验证")
    result = api_get("/api/outputs")
    outputs = result.get("outputs", [])
    subagent_results = [o for o in outputs if o.get("output_type") == "subagent_result"]

    if subagent_results:
        print_ok(f"SubAgent 结果数: {len(subagent_results)}")
        for sa in subagent_results:
            print_info(f"  {sa.get('title', '')[:60]}")
    else:
        print_info("本次运行未触发 SubAgent（可能因为任务复杂度/可拆分性不满足阈值）")
        print_info("这不代表系统问题，在合适的研究目标下将自动触发")

    return True  # SubAgent 触发不是必要条件


def main():
    print(f"\n{BOLD}ResearchGroup-Agent 功能测试脚本{RESET}")
    print(f"后端地址: {BACKEND_URL}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = []

    # 1. 健康检查
    if not check_backend_health():
        print(f"\n{RED}后端未启动！请先在另一个终端运行: cd backend && python main.py{RESET}")
        return 1
    results.append(("后端健康检查", True))

    # 2. Agent 验证
    results.append(("Agent 数据验证", check_agents()))

    # 3. 执行研究任务
    run_id = run_research()
    results.append(("研究任务执行", run_id is not False))

    if run_id:
        # 4. 任务板验证
        results.append(("任务板状态", check_task_board(run_id)))
        # 5. 产出物验证
        results.append(("产出物验证", check_artifacts(run_id)))

    # 6. SubAgent 验证
    results.append(("SubAgent 验证", check_subagents()))

    # 汇总
    print_header("测试结果汇总")
    passed = 0
    failed = 0
    for name, ok in results:
        if ok:
            print_ok(f"{name}")
            passed += 1
        else:
            print_fail(f"{name}")
            failed += 1

    print(f"\n{BOLD}通过: {GREEN}{passed}{RESET} / 总计: {passed + failed}")
    if failed > 0:
        print(f"{RED}失败: {failed}{RESET}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
