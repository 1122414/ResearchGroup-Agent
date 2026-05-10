# 后端可观测性、成本监测与停止控制计划

**日期**: 2026-05-10  
**范围**: `backend/app/models`, `backend/app/storage`, `backend/app/api`, `backend/app/services`, `backend/app/core/llm_provider.py`  
**优先级**: P0

## 1. 目标

把后端从“一个长请求跑完整个 Run”改成“每一步都可查询、可解释、可停止、可统计成本”的执行系统。

用户需要知道：

1. Run 当前阶段是什么。
2. 阶段什么时候开始、什么时候结束、耗时多少。
3. 哪个 Agent 正在处理哪个任务。
4. 每次 LLM 调用的模型、token、成本、耗时。
5. 点击停止后系统是否真的停止，以及停在了哪里。

## 2. 必须新增的数据结构

### 2.1 runs 表扩展

在 `runs` 表增加字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `started_at` | TEXT nullable | 用户点击开始执行的时间 |
| `cancel_requested_at` | TEXT nullable | 用户点击停止的时间 |
| `cancel_reason` | TEXT nullable | 停止原因 |
| `total_cost_usd` | REAL default 0 | 累计美元成本 |
| `total_tokens` | INTEGER default 0 | 累计 token |
| `total_llm_calls` | INTEGER default 0 | LLM 调用次数 |
| `last_event_id` | TEXT nullable | 最后事件 id |

RunStatus 增加：

```python
queued
cancelling
cancelled
```

### 2.2 新增 run_events 表

每个用户可见动作都写一条事件。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `evt_xxxxxxxx` |
| `run_id` | TEXT | 所属 Run |
| `task_id` | TEXT nullable | 关联任务 |
| `agent_id` | TEXT nullable | 关联 Agent |
| `subagent_id` | TEXT nullable | 关联 SubAgent |
| `event_type` | TEXT | 见下方枚举 |
| `phase` | TEXT | `decompose/schedule/execute/subagent/review/report/cancel/error` |
| `title` | TEXT | 用户可读标题 |
| `message` | TEXT | 用户可读说明 |
| `payload` | TEXT JSON | 结构化详情 |
| `created_at` | TEXT | 事件时间 |

事件类型建议：

```text
run.created
run.started
run.cancel_requested
run.cancelled
run.completed
run.failed
phase.started
phase.completed
task.created
task.assigned
task.started
task.output_created
task.waiting_subagent
task.waiting_review
task.completed
task.need_revision
agent.status_changed
subagent.created
subagent.completed
review.started
review.completed
report.created
llm.call_started
llm.call_completed
llm.call_failed
```

### 2.3 新增 llm_usage 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `usage_xxxxxxxx` |
| `run_id` | TEXT nullable | 所属 Run |
| `task_id` | TEXT nullable | 所属 Task |
| `agent_id` | TEXT nullable | 所属 Agent |
| `role` | TEXT | `advisor_decompose/graduate/subagent/advisor_review/advisor_report` |
| `provider` | TEXT | `mock/openai_compatible` |
| `model` | TEXT | 实际模型名 |
| `prompt_tokens` | INTEGER | 没有真实值时估算 |
| `completion_tokens` | INTEGER | 没有真实值时估算 |
| `total_tokens` | INTEGER | 总 token |
| `cost_usd` | REAL | 单次成本 |
| `latency_ms` | INTEGER | LLM 请求耗时 |
| `success` | INTEGER | 1/0 |
| `error` | TEXT nullable | 错误 |
| `created_at` | TEXT | 创建时间 |

Mock 模式也必须写入 `llm_usage`，成本为 0，token 可用简单估算：`len(text) / 4`。

## 3. 服务层实现

### 3.1 新增 RunEventService

文件建议：`backend/app/services/run_event_service.py`

职责：

1. `emit(run_id, event_type, phase, title, message, task_id=None, agent_id=None, subagent_id=None, payload=None)`
2. 写入 `run_events`。
3. 更新 `runs.last_event_id`。
4. 不调用 LLM，不做业务决策。

### 3.2 新增 CostTrackerService

文件建议：`backend/app/services/cost_tracker.py`

职责：

1. 记录每次 LLM 调用。
2. 根据模型名和 token 估算费用。
3. 更新 `runs.total_cost_usd`, `runs.total_tokens`, `runs.total_llm_calls`。
4. 暴露 `get_run_usage(run_id)` 给 API。

初始价格表可以硬编码在配置中，后续再改为 `.env`：

```python
MODEL_PRICING = {
    "mock": {"input": 0.0, "output": 0.0},
    "gpt-4o-mini": {"input": 0.00000015, "output": 0.00000060},
}
```

严禁为了价格表引入外部联网查询。

### 3.3 LLMProvider 增加上下文参数

当前签名：

```python
generate(prompt: str, schema: Optional[dict] = None, role: str = "graduate") -> str
```

建议改为：

```python
generate(
    prompt: str,
    schema: Optional[dict] = None,
    role: str = "graduate",
    run_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
) -> str
```

要求：

1. 所有调用点传入 `run_id/task_id/agent_id`。
2. Mock 和真实 Provider 都记录 usage。
3. 真实 Provider 优先读取 API 返回的 `usage` 字段；没有时估算。

### 3.4 取消控制

新增 API：

```http
POST /api/runs/{run_id}/start
POST /api/runs/{run_id}/cancel
GET  /api/runs/{run_id}/events
GET  /api/runs/{run_id}/usage
GET  /api/runs/{run_id}/summary
```

兼容保留：

```http
POST /api/runs/{run_id}/run_all
```

但前端新页面使用 `/start`，`run_all` 可暂时调用同一执行函数。

取消逻辑：

1. `cancel` 只设置 `status=cancelling`, `cancel_requested_at=now`, `cancel_reason`。
2. 执行流程在每个阶段开始前、每个任务开始前、每次 LLM 调用前调用 `assert_not_cancelled(run_id)`。
3. 如果发现取消请求，写 `run.cancelled` 事件，状态改为 `cancelled`，停止后续任务。
4. 已经进行中的单次 LLM 调用不强行杀死，只在返回后停止下一步。

## 4. 执行流程改造

把 `routes_runs.py` 中 `run_all` 的串行逻辑抽到服务：

文件建议：`backend/app/services/run_execution_service.py`

主函数：

```python
async def execute_run(run_id: str) -> dict:
```

每个阶段必须 emit：

1. `phase.started`
2. 具体子事件
3. `phase.completed`

阶段顺序：

1. decompose
2. schedule
3. execute each task
4. subagent gate and execution
5. review
6. report
7. completed

注意：现阶段不要引入 Celery、RQ、APScheduler。若 FastAPI 请求仍然阻塞，也必须先保证事件已写库，前端能轮询看到进展。后续再考虑后台任务。

## 5. Agent 状态同步

现有 `AgentRepository.update_status` 没有更新 `current_tasks`，计划中不强制大改，但至少要做到：

1. 调度时写入 Agent 当前任务列表。
2. 任务开始时 Agent 状态 `working`。
3. 等待 SubAgent 时 Agent 状态 `waiting`。
4. 审核时导师状态可通过事件表达，不强行建导师表。
5. Run 完成/取消/失败时，把相关研究生 Agent 状态恢复为 `idle` 或 `blocked`。

## 6. 禁止事项

1. 禁止引入复杂任务队列、Docker、Redis、迁移框架。
2. 禁止把取消实现成前端 `AbortController` 伪取消；必须服务端状态可见。
3. 禁止只在日志文件写事件；必须进 SQLite，前端可查询。
4. 禁止让成本表只支持真实 API；Mock 模式也要有记录。
5. 禁止修改 4 个预留接口的核心职责，只可保留扩展点说明。

## 7. 验收标准

1. 创建 Run 后能查询到 `run.created`。
2. 开始执行后，`GET /api/runs/{id}/events` 至少能看到阶段开始/完成事件。
3. 任一 Run 完成后，`GET /api/runs/{id}/usage` 返回调用次数、token、成本。
4. 执行中调用 cancel 后，Run 最终进入 `cancelled` 或已经完成的 `completed`，不能继续创建新任务/新报告。
5. Mock 模式不需要 API Key，完整流程仍可运行。
6. 旧的 `python test_runner.py` 不应被破坏；必要时更新测试以适配新增状态。

