# API 数据契约、预留接口与验收计划

**日期**: 2026-05-10  
**范围**: 全项目  
**优先级**: P0-P2

## 1. 目标

为后续实现提供稳定边界，避免前端、后端、像素办公室、成本监测互相猜字段。

本文件定义：

1. API 契约。
2. 数据字段命名。
3. 预留接口边界。
4. 开发优先级。
5. 验收测试。
6. 明确禁止事项。

## 2. API 契约

### 2.1 Run API

```http
POST /api/runs
GET /api/runs
GET /api/runs/{run_id}
POST /api/runs/{run_id}/start
POST /api/runs/{run_id}/cancel
GET /api/runs/{run_id}/summary
GET /api/runs/{run_id}/events
GET /api/runs/{run_id}/usage
```

`GET /api/runs/{run_id}/summary` 返回：

```json
{
  "run": {},
  "counts": {
    "tasks_total": 5,
    "tasks_completed": 3,
    "tasks_running": 1,
    "tasks_failed": 0,
    "tasks_need_revision": 1,
    "subagents_total": 2
  },
  "usage": {
    "total_cost_usd": 0.0,
    "total_tokens": 0,
    "total_llm_calls": 0,
    "failed_llm_calls": 0
  },
  "latest_event": {},
  "agents": [],
  "tasks": []
}
```

### 2.2 Event API

`GET /api/runs/{run_id}/events` 支持查询参数：

```text
?limit=100
?after_id=evt_xxx
?phase=execute
?task_id=task_xxx
```

返回：

```json
{
  "events": [],
  "next_after_id": "evt_xxx"
}
```

### 2.3 Usage API

`GET /api/runs/{run_id}/usage` 返回：

```json
{
  "summary": {
    "total_cost_usd": 0.0,
    "total_tokens": 0,
    "total_llm_calls": 0,
    "failed_llm_calls": 0,
    "avg_latency_ms": 0
  },
  "items": []
}
```

### 2.4 Monitor API

```http
GET /api/monitor/office-state?run_id={run_id}
```

用于像素办公室，不要求 P0 实现完整动画字段，但 P1/P2 前必须稳定。

## 3. 前端数据类型

更新 `frontend/src/lib/types.ts`，避免 `any[]` 泛滥。

必须定义：

```ts
Run
RunSummary
RunEvent
LLMUsage
Task
Agent
SubAgent
OfficeState
OfficeAgentState
```

要求：

1. API client 返回强类型。
2. 页面内部尽量不用 `any`。
3. 后端新增字段前端可兼容缺省值。

## 4. 预留接口边界

现有 4 个预留服务：

1. `ToolProvider`
2. `AgentOrchestrator`
3. `SkillUpdateService`
4. `ExternalMemory`

本阶段只做边界预留，不实现真实功能。

### 4.1 ToolProvider

可预留字段：

1. `tool_calls_count`
2. `tool_usage_summary`
3. `external_tool_enabled=false`

禁止：

1. 接 Zotero/Overleaf/Notion/GitHub。
2. 自动执行外部命令。

### 4.2 AgentOrchestrator

可预留：

1. `orchestrator_type="mvp_sequential"`
2. `execution_plan` 字段。

禁止：

1. 引入 LangGraph/AutoGen/CrewAI。
2. 重写整个执行引擎。

### 4.3 SkillUpdateService

可预留：

1. Agent skill snapshot。
2. 后续技能变化日志表。

禁止：

1. 让 Agent 自动修改自身能力。
2. 根据单次任务动态改 seed skill。

### 4.4 ExternalMemory

可预留：

1. `memory_refs` 字段。
2. 输出记录中保留来源字段。

禁止：

1. 长期记忆。
2. 向量库。
3. 外部知识库接入。

## 5. 开发任务拆分

### Task A: 后端状态与事件

范围：

1. SQLite schema。
2. Repository。
3. RunEventService。
4. RunExecutionService。
5. 新 API。

不碰：

1. 像素办公室 UI。
2. 大规模 prompt 改写。

### Task B: 成本追踪

范围：

1. LLMProvider 签名。
2. CostTrackerService。
3. `llm_usage` 表。
4. usage API。

不碰：

1. 外部计费查询。
2. 多模型动态价格后台管理。

### Task C: 前端运行详情

范围：

1. `/runs/[id]`。
2. 轮询。
3. 时间线。
4. 成本表。
5. 停止按钮。

不碰：

1. 像素动画。
2. 资产管理。

### Task D: 前端任务/Agent 清晰化

范围：

1. 修文案。
2. 任务卡解释。
3. Agent 活动卡。
4. 输出页可读化。

### Task E: 像素办公室

范围：

1. `office-state`。
2. `/office` 页面。
3. CSS sprite 占位。
4. 角色点击详情。

## 6. 验收用例

### 6.1 Mock 完整流程

步骤：

1. 设置 `MOCK_MODE=true`。
2. 启动后端。
3. 启动前端。
4. 创建 Run。
5. 打开 `/runs/{id}`。

期望：

1. 事件持续出现。
2. 任务被拆解。
3. Agent 被分配。
4. 成本表显示 0 美元和估算 token。
5. 最终完成或需修改。

### 6.2 停止流程

步骤：

1. 创建 Run。
2. 执行中点击停止。
3. 等待状态变化。

期望：

1. 出现 `run.cancel_requested` 事件。
2. Run 进入 `cancelling`。
3. 后续进入 `cancelled` 或在已经完成时保持 `completed`。
4. 停止后不再新增任务执行事件。

### 6.3 前端可读性

检查页面：

1. `/`
2. `/runs/{id}`
3. `/tasks`
4. `/agents`
5. `/outputs`
6. `/office`

期望：

1. 无乱码。
2. 无长文本溢出。
3. 状态都显示中文。
4. 用户不打开控制台也能理解系统在做什么。

### 6.4 成本记录

检查：

1. 每次 LLM 调用有 usage 行。
2. Run 汇总成本等于明细求和。
3. 失败调用也记录。
4. Mock 模式成本为 0。

### 6.5 像素办公室

步骤：

1. 打开 `/office?run_id=...`。
2. 观察运行中状态。
3. 点击 Agent。
4. 点击任务板。

期望：

1. 角色出现。
2. 气泡能解释当前动作。
3. 点击后能看到结构化详情。
4. 停止 Run 后办公室状态同步变为已取消。

## 7. 严禁现阶段做的事

1. 账号/权限/多租户。
2. WebSocket 强依赖。
3. Docker/CI/CD/部署平台。
4. 外部工具接入。
5. 长期记忆/向量库。
6. 自动论文检索或真实科研自动化。
7. Agent 自由聊天入口。
8. SubAgent 越权直接进入报告。
9. 复制第三方非商用美术资产。
10. 大规模重构成全新框架。

## 8. 完成定义

本轮增强完成时，用户应能做到：

1. 发布任务后立即看到运行详情页。
2. 实时看懂每一步发生了什么。
3. 看见任务开始时间、更新时间、耗时。
4. 看见 LLM 调用成本。
5. 从前端停止任务。
6. 在任务板理解每个 Agent 的工作。
7. 在像素办公室直观看到导师和研究生的状态。

