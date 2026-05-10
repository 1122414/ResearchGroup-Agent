# P0 立即修复计划：先让系统可读、可跑、可观测

**日期**: 2026-05-10  
**优先级**: P0  
**目标读者**: OpenCode / 后续实现 Agent  
**适用范围**: 当前 ResearchGroup-Agent MVP  
**核心目标**: 在继续做像素办公室和复杂增强之前，先修复当前项目中导致“看不懂、跑不稳、停不了、算不清”的问题。

## 1. 当前判断

项目当前不是方向错误，而是 MVP 层已经进入“功能骨架存在，但工程和产品表达混乱”的状态。

最需要先修的是：

1. 中文乱码和疑似编码损坏。
2. 前端页面可能存在 JSX/字符串损坏风险。
3. 后端流程是黑盒长请求，用户看不到中间过程。
4. 任务执行不可停止。
5. LLM 调用没有成本记录。
6. Mock 输出和 prompt 文案也有乱码，导致前端展示结果不可读。
7. README 和实际使用体验不一致，用户照 README 跑完仍不知道系统在干什么。

本 P0 计划只处理“修复和拉直基础体验”，不做像素办公室、不做大重构、不做外部工具接入。

## 2. P0 修复目标

完成后必须达到：

1. 项目能正常启动。
2. 前端所有主要页面中文可读。
3. 用户发布任务后能看到当前运行阶段。
4. 用户能看到阶段事件日志。
5. 用户能看到任务开始时间、更新时间、负责人、状态。
6. 用户能看到 LLM 调用次数、token 估算、成本汇总。
7. 用户能从前端请求停止 Run。
8. Mock 模式下无 API Key 也能完整跑通并展示可读结果。

## 3. 修复范围

### 3.1 前端修复范围

文件：

```text
frontend/src/app/page.tsx
frontend/src/app/tasks/page.tsx
frontend/src/app/agents/page.tsx
frontend/src/app/outputs/page.tsx
frontend/src/app/layout.tsx
frontend/src/lib/api.ts
frontend/src/lib/types.ts
```

必须修复：

1. 所有乱码中文。
2. 所有可能导致编译失败的未闭合字符串、标签、模板表达式。
3. 所有直接展示 JSON 但无解释的区域。
4. 首页阻塞等待 `runAll` 的交互。
5. 错误提示不可读的问题。

### 3.2 后端修复范围

文件：

```text
backend/app/api/routes_runs.py
backend/app/api/routes_tasks.py
backend/app/api/routes_agents.py
backend/app/api/routes_outputs.py
backend/app/core/llm_provider.py
backend/app/services/task_decomposer.py
backend/app/services/task_executor.py
backend/app/services/subagent_service.py
backend/app/services/review_service.py
backend/app/services/report_service.py
backend/app/storage/db.py
backend/app/storage/repositories.py
backend/app/models/run.py
backend/app/models/task.py
backend/app/models/agent.py
```

必须修复：

1. 后端中文错误提示和 Mock 输出乱码。
2. Run 状态缺少取消状态。
3. 缺少事件日志表。
4. 缺少 LLM usage 表。
5. 缺少取消接口。
6. 缺少运行摘要接口。

### 3.3 文档修复范围

文件：

```text
README.md
.env.example
test_runner.py
```

必须修复：

1. README 中文乱码。
2. README 中流程说明与前端新流程一致。
3. 明确 Mock 模式和真实 LLM 模式的区别。
4. 明确如何查看运行详情、成本、停止任务。

## 4. 具体修复任务

## Task P0-1：项目可启动性检查

### 要做

1. 运行后端语法检查：

```bash
cd backend
python -m py_compile main.py app/core/llm_provider.py app/services/task_decomposer.py app/services/task_executor.py app/services/subagent_service.py app/services/review_service.py app/services/report_service.py
```

2. 运行前端构建检查：

```bash
cd frontend
npm run lint
npm run build
```

3. 记录所有失败点，先修编译错误，再修体验问题。

### 验收

1. 后端 Python 文件无语法错误。
2. 前端至少能通过 `npm run build`。
3. 若 lint 有历史问题，必须记录并区分是否由本次修复引入。

### 禁止

1. 禁止跳过构建检查直接改 UI。
2. 禁止用删除功能的方式绕过错误。

## Task P0-2：全量中文乱码修复

### 要做

1. 将前端所有页面文案恢复为正常中文。
2. 将 `frontend/src/lib/types.ts` 中所有状态标签恢复为正常中文。
3. 将后端 Mock 输出、错误提示、current_step 文案恢复为正常中文。
4. 将 README 恢复为正常中文。

### 建议状态标签

Run：

```text
created: 已创建
queued: 等待执行
decomposing: 正在拆解任务
scheduling: 正在调度分配
executing: 正在执行任务
reviewing: 导师审核中
reporting: 正在生成报告
cancelling: 正在停止
cancelled: 已停止
completed: 已完成
failed: 失败
```

Task：

```text
pending: 待分配
assigned: 已分配
running: 执行中
waiting_collab: 等待协作
waiting_subagent: 等待 SubAgent
waiting_review: 等待导师审核
need_revision: 需要修改
completed: 已完成
archived: 已归档
failed: 失败
```

Agent：

```text
idle: 空闲
working: 工作中
waiting: 等待中
reviewing: 审核中
blocked: 阻塞
finished: 已完成
```

### 验收

1. 前端页面不再出现乱码。
2. 后端返回给前端的阶段文案可读。
3. Mock 模式生成的任务标题、描述、输出可读。

### 禁止

1. 禁止只修前端标签，不修 Mock 数据。
2. 禁止继续保留乱码作为占位。

## Task P0-3：Run 事件日志

### 要做

新增 `run_events` 表，记录每个用户可见动作。

字段：

```text
id
run_id
task_id
agent_id
subagent_id
event_type
phase
title
message
payload
created_at
```

新增服务：

```text
backend/app/services/run_event_service.py
```

新增 API：

```http
GET /api/runs/{run_id}/events
```

执行流程至少写入：

1. Run 创建。
2. Run 开始。
3. 开始拆解任务。
4. 任务创建完成。
5. 开始调度。
6. 任务分配给 Agent。
7. 开始执行任务。
8. SubAgent 创建和完成。
9. 导师审核开始和完成。
10. 报告生成。
11. Run 完成、失败或取消。

### 验收

1. 创建 Run 后能查到事件。
2. 执行过程中事件持续增加。
3. 前端能按时间线展示事件。

### 禁止

1. 禁止只写控制台日志。
2. 禁止只写 artifacts 文件。

## Task P0-4：运行详情摘要接口

### 要做

新增 API：

```http
GET /api/runs/{run_id}/summary
```

返回：

```json
{
  "run": {},
  "counts": {
    "tasks_total": 0,
    "tasks_pending": 0,
    "tasks_running": 0,
    "tasks_completed": 0,
    "tasks_need_revision": 0,
    "tasks_failed": 0,
    "subagents_total": 0
  },
  "usage": {
    "total_cost_usd": 0,
    "total_tokens": 0,
    "total_llm_calls": 0
  },
  "latest_event": {},
  "tasks": [],
  "agents": []
}
```

### 验收

1. 前端只调用该接口即可拿到运行详情页的主要数据。
2. Run 完成、失败、取消时 summary 都能正常返回。

### 禁止

1. 禁止让前端自己拼 5 个接口才能显示核心状态。

## Task P0-5：LLM 成本和耗时记录

### 要做

新增 `llm_usage` 表。

字段：

```text
id
run_id
task_id
agent_id
role
provider
model
prompt_tokens
completion_tokens
total_tokens
cost_usd
latency_ms
success
error
created_at
```

新增 API：

```http
GET /api/runs/{run_id}/usage
```

Mock 模式：

1. 成本为 0。
2. token 用字符数估算。
3. 仍然记录耗时和调用角色。

真实 LLM 模式：

1. 优先使用 API response 中的 usage。
2. 没有 usage 时用估算。
3. 模型单价先用本地配置表，不联网查询。

### 验收

1. 每次 LLM 调用产生 usage 记录。
2. Run summary 中能看到累计成本。
3. 前端成本表能展示明细。

### 禁止

1. 禁止真实模式下不记录成本。
2. 禁止 Mock 模式下没有 usage 数据。

## Task P0-6：停止 Run

### 要做

RunStatus 增加：

```text
cancelling
cancelled
```

新增 API：

```http
POST /api/runs/{run_id}/cancel
```

执行服务每个阶段前检查取消状态：

1. 拆解前。
2. 调度前。
3. 每个任务执行前。
4. SubAgent 调用前。
5. 审核前。
6. 报告生成前。

取消后：

1. 写入 `run.cancel_requested` 事件。
2. 状态进入 `cancelling`。
3. 当前不可中断的 LLM 调用完成后，不再执行下一步。
4. 状态进入 `cancelled`。
5. 保留已完成产出。

### 验收

1. 前端点击停止后状态变为“正在停止”。
2. 后端不再继续执行后续任务。
3. 已产生的任务、输出、事件不丢失。

### 禁止

1. 禁止只停止前端轮询。
2. 禁止把取消当成失败。

## Task P0-7：前端运行详情页

### 要做

新增：

```text
frontend/src/app/runs/[run_id]/page.tsx
```

页面包含：

1. Run 摘要。
2. 当前阶段。
3. 停止按钮。
4. 阶段时间线。
5. 事件日志。
6. 任务列表。
7. Agent 活动列表。
8. 成本汇总和明细入口。

首页改造：

1. 创建 Run。
2. 调用 start。
3. 跳转 `/runs/{run_id}`。
4. 不再等待 `runAll` 完整返回。

### 验收

1. 用户发布任务后能看到实时运行详情。
2. 页面轮询 summary/events/usage。
3. Run 完成、失败、取消后停止轮询。

### 禁止

1. 禁止继续把核心信息只放在 `/tasks`。
2. 禁止让用户只能看最终报告。

## Task P0-8：任务板可解释化

### 要做

增强 `/tasks`：

1. 每张任务卡显示负责人。
2. 显示最新事件。
3. 显示任务开始/更新时间。
4. 显示优先级、复杂度、可拆解度。
5. 显示 SubAgent 是否触发。
6. 显示审核结果。

### 验收

1. 用户不点开 JSON 也能知道任务现在卡在哪。
2. 点击任务能看到任务详情和事件。

### 禁止

1. 禁止只展示英文枚举。
2. 禁止只展示原始 JSON。

## 5. P0 不做内容

以下内容留到 P1/P2：

1. 像素办公室。
2. Agent 小人动画。
3. 独立办公室地图。
4. WebSocket / SSE。
5. 外部工具接入。
6. 多用户权限。
7. 长期记忆。
8. 向量库。
9. LangGraph/AutoGen/CrewAI 替换。
10. 桌面宠物。

## 6. 推荐执行顺序

1. P0-1 可启动性检查。
2. P0-2 中文乱码修复。
3. P0-3 Run 事件日志。
4. P0-5 LLM 成本记录。
5. P0-6 停止 Run。
6. P0-4 Summary 聚合接口。
7. P0-7 前端运行详情页。
8. P0-8 任务板可解释化。
9. 更新 README。
10. 运行验收测试。

## 7. 最终验收清单

必须全部通过：

1. `MOCK_MODE=true` 时，后端可启动。
2. 前端可启动并可构建。
3. 首页中文可读。
4. 发布任务后跳转运行详情页。
5. 运行详情页能看到当前阶段。
6. 运行详情页能看到事件流。
7. 任务板能看懂每个任务在做什么。
8. Agent 页面能看懂每个 Agent 的状态。
9. 成本表能看到 Mock usage。
10. 点击停止后后端 Run 进入取消流程。
11. README 能指导用户完成上述流程。

## 8. 给 OpenCode 的执行要求

1. 先修编译和乱码，再做新功能。
2. 每完成一个 P0 task 都要运行对应检查。
3. 不要在 P0 中实现像素办公室。
4. 不要重构整个项目结构。
5. 不要删除现有 Mock 模式。
6. 不要让 SubAgent 绕过研究生 Agent 和导师审核。
7. 所有新增 API 都要在 README 中说明。

