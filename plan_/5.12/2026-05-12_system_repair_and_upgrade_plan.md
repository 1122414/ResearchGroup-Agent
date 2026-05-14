# ResearchGroup-Agent 系统修复与升级执行计划

**日期：** 2026-05-12  
**面向执行者：** opencode / 后续工程 Agent  
**目标仓库：** `E:\GitHub\Repositories\ResearchGroup-Agent`  
**计划类型：** 系统漏洞修复、死代码清理、架构整理、前后端体验与能力升级  
**执行原则：** 小步提交、可验证、保留 MVP 边界、为后续接入真实工具/记忆/多模态模型预留接口

---

## 0. 背景与当前系统判断

当前 ResearchGroup-Agent 是一个本地运行的多 Agent 研究协作系统：

- 前端：Next.js 16 + React 19 + Tailwind v4 + shadcn/ui。
- 后端：FastAPI + SQLite + Pydantic Settings。
- Agent 编排：自研状态机与服务层，不依赖 LangChain、AutoGen、CrewAI、LangGraph。
- LLM 调用：OpenAI-compatible `/chat/completions` 或 Mock Provider。
- 数据存储：SQLite + `artifacts/runs/{run_id}` 文件产物。
- 当前核心流程：创建 Run -> 导师拆解 -> 调度任务 -> 研究生执行 -> SubAgent 辅助 -> 导师审核 -> 写作研究生初稿 -> 导师终审最终报告。

系统已经具备 MVP 骨架，但存在明显工程风险：

1. 多处中文字符串出现编码损坏，影响 UI、Prompt、日志、报告可读性。
2. 服务层有不少 stub 和预留文件，但缺少清晰接口边界与调用说明。
3. Agent 通信仍是数据库状态流，缺少明确的上下文构造器和产出规范校验层。
4. 前端页面功能已经堆叠，部分页面缺少统一交互、加载态、错误态与性能优化。
5. 后端运行流程单体较重，`RunExecutionService` 承担过多职责。
6. SQLite schema 依赖手写 SQL 和 `_ensure_columns`，后续升级容易失控。
7. 设置面板可写 `.env`，但安全边界、字段白名单和敏感字段展示需要进一步收紧。
8. 日志、运行产物、附件处理、最终报告之间缺少统一生命周期管理。

---

## 1. 总体执行策略

### 1.1 阶段划分

本计划分为两条主线：

1. **系统修复计划**：先修漏洞、清死代码、稳定架构、保证现有功能可靠。
2. **系统升级方向**：再做前端体验、速度、后端能力、功能新增和外部接口预留。

### 1.2 优先级定义

| 优先级 | 含义 | 处理方式 |
|---|---|---|
| P0 | 阻塞系统正确性、数据安全、运行稳定 | 必须最先做 |
| P1 | 影响核心用户体验或后续扩展 | P0 后连续做 |
| P2 | 体验优化、架构增强、可维护性提升 | 分批做 |
| P3 | 实验性能力、可选功能 | 仅在主线稳定后做 |

### 1.3 每个任务的标准交付物

每个任务完成时必须具备：

1. 源码改动。
2. 必要的最小测试或 smoke 验证。
3. 不引入无关重构。
4. 一次独立中文 commit。
5. 在计划文档或变更说明里记录风险和后续事项。

### 1.4 严禁事项

执行本计划时严禁：

1. 不经确认删除用户数据、运行数据库、历史 artifacts。
2. 用 `git reset --hard`、`git checkout -- .` 等命令回滚用户改动。
3. 把 `backend/logs/`、`frontend/logs/`、`backend/out.log`、`backend/err.log` 提交进 git。
4. 把 `.env`、API Key、模型密钥、真实用户上传材料提交进 git。
5. 一次性做大范围重写，导致无法定位回归。
6. 引入大型 AI 框架替换现有流程，除非单独立项并保留兼容层。
7. 让 SubAgent 绕过父 Agent 或导师审核直接进入最终报告。
8. 让前端直接访问本地文件系统或直接修改 `.env`，必须走后端受控接口。
9. 在没有 schema 校验的情况下让 LLM 任意返回非结构化关键数据。
10. 在任务执行中无限递归创建 Agent 或 SubAgent。

---

## 2. 系统修复计划

## P0-01 修复全项目中文编码损坏

### 问题

当前大量后端字符串、前端 UI 文案、Prompt 拼接内容出现 mojibake，例如 `éæ¬Ž`、`æµ è¯²` 等。这会导致：

- 用户看不懂页面。
- Prompt 指令质量下降。
- LLM 输出不可控。
- 日志和报告不可审计。

### 边界

只修复源码中的中文文案、Prompt 文案、UI label、错误信息、日志 title/message。  
不改业务逻辑。

### 要做什么

1. 扫描 mojibake：
   - `rg "é|æ|ç|å|è|î|Ñ|Ð|€|™" backend frontend`
2. 优先修复：
   - `backend/app/services/*.py`
   - `backend/app/api/*.py`
   - `backend/app/core/llm_provider.py`
   - `frontend/src/app/**/*.tsx`
   - `frontend/src/components/**/*.tsx`
   - `frontend/src/lib/types.ts`
   - `backend/app/data/seed_agents.json`
   - `backend/app/prompts/*.md`
3. 统一术语：
   - Run -> 运行
   - Task -> 任务
   - Output -> 产出
   - Advisor -> 导师 Agent
   - Graduate -> 研究生 Agent
   - Writer -> 写作研究生
   - SubAgent -> 临时 SubAgent
4. 所有用户可见文案必须为自然中文。
5. 后端事件 `run_events.title/message` 也必须是自然中文。

### 严禁做什么

- 不要用机器翻译盲改业务字段名。
- 不要修改数据库列名。
- 不要改 `task_type`、`status` 等枚举值。

### 验收标准

1. `rg "é|æ|ç|å|è|î|Ñ|Ð|€|™" backend frontend` 不再命中源码中的乱码。
2. `npm run lint` 通过。
3. `npm run build` 通过。
4. `python -m py_compile` 覆盖后端核心文件通过。
5. 首页、任务板、输出中心、像素办公室无乱码。

### 建议 commit

`修复系统中文编码文案`

---

## P0-02 清理敏感配置展示与 `.env` 写入边界

### 问题

设置接口当前会返回 `llm_api_key`，前端也支持编辑。虽然本地系统可接受，但存在风险：

- API Key 可能被日志或截图泄露。
- 前端可能误展示完整 key。
- `.env` 写入字段若控制不严格，可能被滥用。

### 边界

只收紧配置读写边界，不改变现有设置功能的基本可用性。

### 要做什么

1. `GET /api/settings` 默认返回脱敏 key，例如：
   ```json
   {
     "llm_api_key_masked": "sk-****abcd",
     "has_llm_api_key": true
   }
   ```
2. 前端输入框只在用户输入新值时更新 key。
3. `PATCH /api/settings` 继续允许写 `llm_api_key`，但：
   - 空字符串不覆盖原 key，除非显式传 `clear_llm_api_key: true`。
   - 严格使用白名单字段。
4. 禁止把 key 写入日志。
5. 设置保存成功后前端提示：
   - “已同步当前进程”
   - “部分配置需重启生效”

### 严禁做什么

- 不要把 `.env` 内容整体返回给前端。
- 不要把完整 API Key 打印在 console、backend log、frontend log。
- 不要允许任意 key 写入 `.env`。

### 验收标准

1. 浏览器网络面板中 `GET /api/settings` 不出现完整 API Key。
2. 更新非敏感字段仍可生效。
3. 更新 API Key 可写入 `.env`。
4. 日志中不出现 key 明文。

### 建议 commit

`收紧系统设置敏感配置边界`

---

## P0-03 稳定运行状态机和任务状态流

### 问题

当前运行流程可用，但状态流仍然散落在服务里。风险：

- 任务状态转换不集中。
- 运行取消和失败时容易遗漏 Agent reset。
- 写作任务依赖前置研究任务的规则需要更明确。

### 边界

不引入外部工作流框架。保持当前 FastAPI + 服务层结构。

### 要做什么

1. 新增状态定义文件：
   ```text
   backend/app/core/state_machine.py
   ```
2. 明确 Run 状态：
   ```text
   created -> queued -> decomposing -> scheduling -> executing -> reviewing -> reporting -> completed
   created/queued/executing/... -> cancelling -> cancelled
   any -> failed
   ```
3. 明确 Task 状态：
   ```text
   pending -> assigned -> running -> waiting_subagent -> running -> waiting_review -> completed
   waiting_review -> need_revision
   any -> failed
   ```
4. 在状态机中提供：
   - `can_transition_run(from, to)`
   - `can_transition_task(from, to)`
   - `assert_transition(...)`
5. 在 `RunExecutionService`、`TaskRepository.update_status` 或更上层服务中使用。
6. 写作任务必须在非 `report_writing` 任务执行并审核后再执行。
7. 运行取消、失败、完成都必须调用统一 reset：
   - 相关 Agent 回到 `idle` 或 `blocked`
   - 当前任务列表清空

### 严禁做什么

- 不要让前端直接改任务状态。
- 不要允许 `completed` 任务回到 `running`，除非后续新增“重新执行任务”功能并单独建状态。
- 不要跳过导师审核直接进入最终报告。

### 验收标准

1. 单次运行完整执行成功。
2. 取消运行后 Agent 回到待命。
3. 写作任务开始时间晚于研究任务审核完成。
4. 无非法状态跃迁。

### 建议 commit

`规范运行与任务状态机`

---

## P0-04 修复最终报告上下文与附件目标截断逻辑

### 问题

当前 `research_goal` 会合并附件上下文；报告中提取 primary goal 依赖字符串 split。若中文分隔符乱码或变更，会导致最终报告标题包含附件全文。

### 边界

不改数据库 schema 的前提下先修复。后续 P1 再考虑新增附件表。

### 要做什么

1. 在 `routes_runs.py` 统一附件上下文分隔符常量：
   ```python
   ATTACHMENT_CONTEXT_HEADING = "## 用户上传的多模态附件上下文"
   ```
2. 在 `report_service.py` 复用同一个常量或公共 util。
3. 新增 util：
   ```text
   backend/app/core/research_goal.py
   ```
   提供：
   - `primary_goal(research_goal: str) -> str`
   - `attachment_context(research_goal: str) -> str`
   - `merge_goal_and_attachments(goal, attachments) -> str`
4. 前端 `primaryGoal()` 也保持同样分隔符。
5. 未来预留：后续可把附件上下文从 `runs.research_goal` 迁移到独立表。

### 严禁做什么

- 不要在多个文件里硬编码不同分隔符。
- 不要让最终报告标题包含附件原文。

### 验收标准

1. 带 PDF 附件创建运行后，任务拆解能读取附件上下文。
2. 最终报告标题只包含原始研究目标。
3. 输出中心和任务板显示的目标不包含附件全文。

### 建议 commit

`统一研究目标与附件上下文处理`

---

## P0-05 增加最小自动化测试

### 问题

当前依赖人工 smoke，缺少稳定的回归保护。

### 边界

先做最小测试，不追求完整覆盖率。

### 要做什么

新增测试目录：

```text
backend/tests/
frontend 可暂不加 E2E，先依赖 npm run lint/build
```

后端测试：

1. `test_state_machine.py`
   - 合法状态转换。
   - 非法状态转换。
2. `test_goal_context.py`
   - primary goal 截断。
   - 附件上下文合并。
3. `test_scheduler.py`
   - 高技能 Agent 优先。
   - 空闲度影响分数。
4. `test_report_service.py`
   - final_report、review_summary、writer_draft 三类产物生成。
5. `test_routes_runs.py`
   - preflight 无附件。
   - preflight PDF。
   - 图片在 Mock 模式下阻止。

### 严禁做什么

- 不要依赖真实 LLM API。
- 不要把测试写成必须联网。
- 不要污染真实 `researchgroup.db`，测试必须用临时数据库或隔离路径。

### 验收标准

1. `pytest` 可本地运行。
2. 测试不依赖真实 API Key。
3. 测试结束不留下大量 artifacts。

### 建议 commit

`补充核心流程回归测试`

---

## P1-01 清理死代码与预留模块边界

### 问题

当前存在多个预留模块：

- `agent_orchestrator.py`
- `external_memory.py`
- `tool_provider.py`
- `skill_update_service.py`

它们不是坏事，但缺少清晰说明，容易被误认为已经接入。

### 边界

不要删除所有预留模块。要把“未实现”和“预留接口”整理清楚。

### 要做什么

1. 新建：
   ```text
   backend/app/services/interfaces/
   ```
   或保持现有位置，但统一文件头文档。
2. 每个预留模块必须标注：
   - 当前是否接入主流程。
   - 预期输入输出。
   - 后续接入点。
   - 禁止当前调用的原因。
3. 对 NotImplemented 的服务增加明确异常：
   ```python
   raise NotImplementedError("该接口为预留扩展点，当前 MVP 未接入主流程")
   ```
4. 通过 `rg "agent_orchestrator|external_memory|tool_provider"` 确认主流程没有误调用。
5. 如果有完全无引用、无计划的文件，移入 `plan_/archive_notes` 说明后再删。

### 严禁做什么

- 不要删除未来明确要接入的接口。
- 不要把 stub 当成可用功能展示到前端。

### 验收标准

1. 所有预留接口都有中文 docstring。
2. README 或新建 `backend/app/services/README.md` 说明扩展点。
3. 主流程无误调用。

### 建议 commit

`整理预留服务接口边界`

---

## P1-02 拆分 RunExecutionService

### 问题

`RunExecutionService` 当前承担：

- 状态流控制。
- 任务执行批处理。
- 审核批处理。
- 报告触发。
- 取消处理。
- Agent reset。

类职责偏重，后续扩展容易变成巨型服务。

### 边界

不改变外部 API。`run_execution_service.execute(run_id)` 仍然保留。

### 要做什么

建议拆出：

```text
backend/app/services/run_lifecycle.py
backend/app/services/task_batch_runner.py
backend/app/services/agent_state_service.py
```

职责：

| 文件 | 职责 |
|---|---|
| `run_lifecycle.py` | Run 状态流、取消、失败、完成 |
| `task_batch_runner.py` | 执行任务批次、审核任务批次 |
| `agent_state_service.py` | Agent 工作/待命/blocked 状态更新 |

`RunExecutionService` 变成编排入口，只按阶段调用这些服务。

### 严禁做什么

- 不要改 API 路由行为。
- 不要把业务逻辑移动到路由层。
- 不要改变数据库结构。

### 验收标准

1. `run_execution_service.execute()` 外部签名不变。
2. 运行完整任务成功。
3. 取消和失败仍能 reset Agent。
4. 单个文件行数明显下降。

### 建议 commit

`拆分运行执行服务职责`

---

## P1-03 建立统一 Output 类型和报告产物规范

### 问题

当前 outputs 类型包括：

- `task_result`
- `subagent_result`
- `review`
- `review_summary`
- `final_report_draft`
- `final_report`

但类型定义分散，前后端可能不一致。

### 边界

不大改数据库，先统一枚举和类型 label。

### 要做什么

1. 后端新增：
   ```text
   backend/app/models/output_types.py
   ```
2. 定义：
   ```python
   TASK_RESULT = "task_result"
   SUBAGENT_RESULT = "subagent_result"
   REVIEW = "review"
   REVIEW_SUMMARY = "review_summary"
   FINAL_REPORT_DRAFT = "final_report_draft"
   FINAL_REPORT = "final_report"
   ```
3. 所有服务使用常量。
4. 前端 `OUTPUT_TYPE_LABELS` 与后端枚举同步。
5. 输出中心按类型排序：
   - final_report
   - final_report_draft
   - review_summary
   - review
   - subagent_result
   - task_result

### 严禁做什么

- 不要新增随意字符串类型。
- 不要把最终报告和审核汇总混为一个产物。

### 验收标准

1. 输出类型无魔法字符串散落。
2. 输出中心 label 正常显示。
3. 下载 `.md` 只针对 Markdown 类产物。

### 建议 commit

`统一产出类型与报告规范`

---

## P1-04 数据库 schema 版本化

### 问题

当前 schema 通过 `CREATE TABLE IF NOT EXISTS` 和 `_ensure_columns` 演进。短期可用，长期容易失控。

### 边界

不要引入复杂 ORM migration。保持轻量。

### 要做什么

1. 新建表：
   ```sql
   schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)
   ```
2. 新建目录：
   ```text
   backend/app/storage/migrations/
   ```
3. 每次 schema 变更写一个 Python migration：
   ```text
   0001_init.py
   0002_add_run_usage.py
   0003_add_attachments.py
   ```
4. `init_db()` 执行未应用 migration。
5. 当前已有表保持兼容，不强制重建。

### 严禁做什么

- 不要删除现有用户数据。
- 不要要求用户手动删库。

### 验收标准

1. 老数据库启动不报错。
2. 新数据库可完整初始化。
3. migration 可重复执行且幂等。

### 建议 commit

`增加轻量数据库迁移机制`

---

## P1-05 附件独立建模

### 问题

当前附件上下文合并进 `runs.research_goal`，简单但不够干净。

### 边界

保持兼容旧 run，不破坏已有 `research_goal`。

### 要做什么

1. 新增表：
   ```sql
   run_attachments (
     id TEXT PRIMARY KEY,
     run_id TEXT NOT NULL,
     name TEXT NOT NULL,
     mime_type TEXT,
     size INTEGER,
     path TEXT NOT NULL,
     extracted_markdown_path TEXT,
     extraction_status TEXT,
     extraction_error TEXT,
     created_at TEXT NOT NULL
   )
   ```
2. 后端新增 Repository：
   ```text
   AttachmentRepository
   ```
3. `routes_runs.py` 创建 run 时：
   - 保存附件文件。
   - 写入 `run_attachments`。
   - PDF 提取结果写 `extracted_markdown_path`。
4. 拆解任务时由上下文构造器读取附件 Markdown，而不是塞进 `research_goal`。
5. 前端运行详情显示附件列表。

### 严禁做什么

- 不要把大文件内容直接存 SQLite。
- 不要把图片 base64 长期存数据库。

### 验收标准

1. 附件列表可查询。
2. PDF 提取结果可追踪。
3. 最终报告标题不会包含附件上下文。

### 建议 commit

`独立建模运行附件`

---

## 3. 系统升级方向

## P1-06 前端页面统一视觉系统

### 目标

让系统从“功能堆叠”升级为“稳定、专业、可长时间使用的研究协作工作台”。

### 要做什么

1. 建立统一布局：
   - 页面标题区。
   - 操作区。
   - 状态指标区。
   - 主内容区。
2. 建立统一组件：
   ```text
   frontend/src/components/app-page.tsx
   frontend/src/components/run-selector.tsx
   frontend/src/components/status-pill.tsx
   frontend/src/components/empty-state.tsx
   frontend/src/components/error-state.tsx
   ```
3. 页面风格：
   - 首页偏任务创建。
   - 任务板偏密集工作台。
   - 输出中心偏文档阅读。
   - 像素办公室保留游戏化视觉，但控件仍要清晰。
4. 修复所有移动端溢出。
5. 所有按钮使用 lucide icon。
6. 所有 select/input 高度统一。

### 严禁做什么

- 不要做营销 landing page。
- 不要用大面积紫蓝渐变、装饰球、无意义 hero。
- 不要把卡片套卡片。
- 不要牺牲任务密度。

### 验收标准

1. 1440、1024、768、390 宽度下无明显重叠。
2. 核心页面视觉风格统一。
3. 表单和按钮文字不溢出。

### 建议 commit

`统一前端页面视觉系统`

---

## P1-07 前端响应速度优化

### 问题

当前前端多页面会重复请求：

- runs
- tasks
- outputs
- office state

轮询也可能造成无效请求。

### 要做什么

1. 引入轻量请求缓存策略。可选方案：
   - 不引入库：自研 `useAsyncResource`。
   - 或引入 TanStack Query，但需要单独评估依赖。
2. 优先不引入新库，实现：
   ```text
   frontend/src/lib/request-cache.ts
   frontend/src/hooks/use-runs.ts
   frontend/src/hooks/use-run-tasks.ts
   frontend/src/hooks/use-run-outputs.ts
   ```
3. 轮询优化：
   - 只有 running/queued/decomposing/scheduling/reviewing/reporting 时轮询。
   - completed/failed/cancelled 停止轮询。
4. 切换 run 时保留上一次数据作为 skeleton 或 stale view。
5. 大 Markdown 渲染用 memo。
6. 输出列表分页或虚拟化预留。

### 严禁做什么

- 不要全局每秒请求所有接口。
- 不要在 effect 中无条件 setState 造成循环渲染。

### 验收标准

1. 已完成运行页面不再持续轮询。
2. 切换运行时页面无明显闪烁。
3. 浏览器 Network 中重复请求明显减少。

### 建议 commit

`优化前端请求缓存与轮询策略`

---

## P1-08 后端运行事件升级为 SSE

### 问题

当前前端主要轮询状态。运行中实时性一般，且频繁请求浪费。

### 边界

先加 SSE，不强制替换所有轮询。

### 要做什么

1. 新增接口：
   ```text
   GET /api/runs/{run_id}/events/stream
   ```
2. 返回 Server-Sent Events。
3. 每次 `run_event_service.emit()` 后可被 stream 获取。
4. 前端运行详情和像素办公室优先使用 SSE。
5. SSE 失败时回退轮询。

### 严禁做什么

- 不要直接引入 WebSocket 复杂状态同步。
- 不要让 SSE 阻塞 Run 执行线程。

### 验收标准

1. 运行中事件可实时出现在运行详情页。
2. SSE 断开后自动 fallback 到轮询。
3. 多个浏览器打开同一 run 不影响执行。

### 建议 commit

`增加运行事件SSE推送`

---

## P1-09 后端上下文构造器

### 问题

当前 Prompt 上下文分散在 decomposer、executor、review、report 服务中。后续加入附件、记忆、工具结果会越来越乱。

### 要做什么

新增：

```text
backend/app/services/context_builder.py
```

职责：

1. 为导师拆解构造上下文。
2. 为研究生任务执行构造上下文。
3. 为 SubAgent 构造受限上下文。
4. 为导师审核构造上下文。
5. 为写作研究生构造全局报告上下文。
6. 为导师终审构造最终报告上下文。

接口示例：

```python
class ContextBuilder:
    def for_decomposition(run_id: str) -> dict: ...
    def for_task_execution(task_id: str) -> dict: ...
    def for_subagent(task_id: str, parent_agent_id: str) -> dict: ...
    def for_review(task_id: str) -> dict: ...
    def for_final_report(run_id: str) -> dict: ...
```

### 严禁做什么

- 不要让 SubAgent 拿到全量 run 上下文。
- 不要把完整附件原文无截断塞入所有 Prompt。

### 验收标准

1. Prompt 拼接逻辑明显集中。
2. 每个 Agent 能拿到的上下文边界可测试。
3. 最终报告输入上下文可追踪。

### 建议 commit

`增加Agent上下文构造器`

---

## P2-01 任务重新执行与修订流

### 目标

让 `need_revision` 任务可以被用户重新执行，而不是卡住。

### 要做什么

1. 后端新增：
   ```text
   POST /api/tasks/{task_id}/rerun
   ```
2. 支持：
   - 清理旧 `review_result`。
   - 保留旧产出为历史版本。
   - 任务状态回到 `assigned` 或 `running`。
3. 输出版本化：
   - `out_{task_id}_v1`
   - `out_{task_id}_v2`
4. 前端任务详情增加“重新执行”按钮。

### 严禁做什么

- 不要覆盖旧产出。
- 不要自动重跑所有任务。

### 验收标准

1. `need_revision` 任务可重新执行。
2. 旧产出可在输出中心查到。
3. 最终报告只采用最新通过审核的产出。

### 建议 commit

`支持任务修订与重新执行`

---

## P2-02 接入真实工具接口

### 目标

把 `ToolProvider` 从 stub 升级为受控工具层。

### 首批工具

1. `web_search`
2. `pdf_extract`
3. `markdown_reader`
4. `file_digest`
5. `chart_generator`

### 要做什么

1. 定义工具协议：
   ```python
   class ToolResult(BaseModel):
       ok: bool
       content: str | dict
       citations: list[dict] = []
       error: str | None = None
   ```
2. 工具调用必须受白名单控制。
3. 每次工具调用写入 `run_events`。
4. 工具结果进入任务上下文前必须摘要或截断。

### 严禁做什么

- 不要让 LLM 自由决定执行任意 shell。
- 不要默认联网搜索，必须由配置开关控制。
- 不要把本地任意路径暴露给 Agent。

### 验收标准

1. 工具列表可查询。
2. 工具调用有日志和事件。
3. Agent Prompt 中能引用工具结果。

### 建议 commit

`接入受控工具提供层`

---

## P2-03 长期记忆接口预留与最小实现

### 目标

让系统支持后续接入向量库，但先保持轻量本地实现。

### 要做什么

1. 扩展 `external_memory.py`：
   ```python
   save_summary(agent_id, run_id, content)
   retrieve(agent_id, query, limit=5)
   delete_run_memory(run_id)
   ```
2. 第一阶段使用 SQLite 表：
   ```sql
   agent_memory (
     id TEXT PRIMARY KEY,
     agent_id TEXT,
     run_id TEXT,
     memory_type TEXT,
     content TEXT,
     created_at TEXT
   )
   ```
3. 只保存导师审核摘要、最终报告摘要，不保存完整附件。
4. 预留向量库 adapter：
   ```text
   backend/app/services/memory_adapters/base.py
   backend/app/services/memory_adapters/sqlite.py
   backend/app/services/memory_adapters/vector_stub.py
   ```

### 严禁做什么

- 不要默认把所有用户上传资料写入长期记忆。
- 不要跨 run 自动污染当前任务上下文。
- 不要引入 Chroma/Pinecone 等依赖，除非单独立项。

### 验收标准

1. 每次 run 完成后可保存摘要记忆。
2. 默认不启用跨运行检索，需设置开关。
3. 删除 run 时可删除相关 memory。

### 建议 commit

`预留并实现轻量Agent记忆接口`

---

## P2-04 多模态模型能力检测升级

### 问题

当前图片附件仅做 Mock 模式判断，无法真正确认模型是否支持视觉输入。

### 要做什么

1. 设置中增加：
   ```text
   MULTIMODAL_ENABLED
   VISION_MODEL_NAME
   ```
2. 后端新增能力检测：
   ```text
   GET /api/capabilities
   POST /api/capabilities/check
   ```
3. 图片附件预检逻辑：
   - Mock 模式禁止。
   - 未开启 `MULTIMODAL_ENABLED` 禁止。
   - 未配置 `VISION_MODEL_NAME` 警告或禁止。
4. 后续预留视觉解析接口：
   ```text
   backend/app/services/vision_extractor.py
   ```

### 严禁做什么

- 不要假装所有 OpenAI-compatible 模型都支持图片。
- 不要把图片 base64 直接塞进普通文本模型 Prompt。

### 验收标准

1. 图片附件有清晰预检结果。
2. 前端显示模型能力。
3. 无视觉能力时不会启动包含图片的运行。

### 建议 commit

`完善多模态能力检测`

---

## P2-05 输出中心升级为文档工作台

### 目标

让最终报告和过程产出更适合阅读、审核、下载。

### 要做什么

1. 最终报告：
   - Markdown 渲染。
   - 目录导航。
   - 下载 `.md`。
   - 复制全文。
2. 过程产出：
   - 按任务聚合。
   - 按 Agent 聚合。
   - 按产出类型聚合。
3. 审核汇总：
   - 显示通过/需修改统计。
   - 点击任务跳转任务详情。
4. 增加导出包：
   ```text
   GET /api/runs/{run_id}/export.zip
   ```
   包含 final_report、review_summary、tasks、attachments metadata。

### 严禁做什么

- 不要把所有输出堆在一个长列表。
- 不要下载时重新生成报告，必须下载已保存产物。

### 验收标准

1. 输出中心可快速定位最终报告。
2. 审核汇总和任务产出分区清晰。
3. zip 导出包含完整可审计产物。

### 建议 commit

`升级输出中心为文档工作台`

---

## P2-06 Agent 可观测性与成本面板

### 目标

让用户看到每个 Agent 做了什么、花了多少钱、用了多少 token。

### 要做什么

1. 后端聚合接口：
   ```text
   GET /api/runs/{run_id}/agent-usage
   ```
2. 统计：
   - 每个 Agent 的任务数。
   - LLM 调用次数。
   - prompt/completion tokens。
   - cost。
   - 平均延迟。
   - 错误次数。
3. 前端运行详情增加：
   - Agent 用量表。
   - 阶段耗时。
   - 成本曲线。

### 严禁做什么

- 不要在前端重新计算复杂聚合。
- 不要把 prompt 全文默认展示，避免泄露上传材料。

### 验收标准

1. run 详情可看到 Agent 级成本。
2. 失败调用可追踪。
3. Mock 模式成本显示为 0 或 mock 配置成本。

### 建议 commit

`增加Agent用量与成本面板`

---

## P3-01 可插拔 AI 编排框架适配层

### 目标

未来可以接入 LangGraph、AutoGen、CrewAI，但不破坏现有自研编排。

### 要做什么

1. 定义统一接口：
   ```python
   class OrchestratorAdapter:
       async def execute_run(run_id: str) -> dict: ...
       async def execute_task(task_id: str) -> dict: ...
   ```
2. 当前实现：
   ```text
   NativeStateMachineAdapter
   ```
3. 预留：
   ```text
   LangGraphAdapter
   AutoGenAdapter
   CrewAIAdapter
   ```
4. `.env` 配置：
   ```text
   ORCHESTRATOR=native
   ```

### 严禁做什么

- 不要直接替换当前运行流程。
- 不要引入框架依赖进默认安装。
- 不要让框架接管数据库写入规则。

### 验收标准

1. native 适配器行为和当前一致。
2. 其他适配器只是 stub，不参与主流程。
3. README 明确说明默认仍是 native。

### 建议 commit

`预留可插拔Agent编排适配层`

---

## P3-02 研究模板和任务模板系统

### 目标

让用户创建任务时可选择研究模板，提高生成质量。

### 要做什么

1. 新增模板：
   - 产品对比研究。
   - 文献综述。
   - 技术方案调研。
   - 实验评测。
   - 游戏/应用竞品分析。
2. 后端：
   ```text
   GET /api/research-templates
   ```
3. 前端首页选择模板后自动填充：
   - 研究目标结构。
   - 输出要求。
   - 推荐附件类型。
4. 模板保存在：
   ```text
   backend/app/data/research_templates.json
   ```

### 严禁做什么

- 不要把模板写死在前端。
- 不要让模板绕过导师拆解。

### 验收标准

1. 首页可选模板。
2. 模板能提升任务拆解稳定性。
3. 用户仍可自由编辑目标。

### 建议 commit

`增加研究任务模板系统`

---

## 4. 推荐执行顺序

### 第一阶段：修系统正确性

1. P0-01 修复系统中文编码文案
2. P0-02 收紧系统设置敏感配置边界
3. P0-03 稳定运行状态机和任务状态流
4. P0-04 修复最终报告上下文与附件目标截断逻辑
5. P0-05 增加最小自动化测试

### 第二阶段：整理架构

1. P1-01 清理死代码与预留模块边界
2. P1-02 拆分 RunExecutionService
3. P1-03 建立统一 Output 类型和报告产物规范
4. P1-04 数据库 schema 版本化
5. P1-05 附件独立建模

### 第三阶段：升级用户体验

1. P1-06 前端页面统一视觉系统
2. P1-07 前端响应速度优化
3. P1-08 后端运行事件升级为 SSE
4. P2-05 输出中心升级为文档工作台
5. P2-06 Agent 可观测性与成本面板

### 第四阶段：扩展能力

1. P2-01 任务重新执行与修订流
2. P2-02 接入真实工具接口
3. P2-03 长期记忆接口预留与最小实现
4. P2-04 多模态模型能力检测升级
5. P3-01 可插拔 AI 编排框架适配层
6. P3-02 研究模板和任务模板系统

---

## 5. 每阶段验收命令

### 后端语法检查

```bash
python -m py_compile backend/main.py backend/app/api/*.py backend/app/core/*.py backend/app/services/*.py backend/app/storage/*.py
```

### 后端测试

```bash
pytest
```

### 前端检查

```bash
cd frontend
npm run lint
npm run build
```

### API smoke

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/runs
curl http://127.0.0.1:8000/api/settings
```

### 页面 smoke

浏览器打开：

```text
http://localhost:3000/
http://localhost:3000/tasks
http://localhost:3000/outputs
http://localhost:3000/office
```

---

## 6. 建议提交策略

每个任务一个中文 commit。示例：

```text
修复系统中文编码文案
收紧系统设置敏感配置边界
规范运行与任务状态机
统一研究目标与附件上下文处理
补充核心流程回归测试
整理预留服务接口边界
拆分运行执行服务职责
统一产出类型与报告规范
增加轻量数据库迁移机制
独立建模运行附件
统一前端页面视觉系统
优化前端请求缓存与轮询策略
增加运行事件SSE推送
增加Agent上下文构造器
支持任务修订与重新执行
接入受控工具提供层
预留并实现轻量Agent记忆接口
完善多模态能力检测
升级输出中心为文档工作台
增加Agent用量与成本面板
预留可插拔Agent编排适配层
增加研究任务模板系统
```

---

## 7. 最终目标形态

完成本计划后，系统应达到：

1. 所有页面中文正常、体验统一。
2. 运行流程可审计、可取消、可恢复、可测试。
3. Agent 上下文边界清晰，SubAgent 不能越权。
4. 最终报告、审核汇总、写作初稿三类产物清楚分离。
5. 设置、安全、附件、日志都有明确生命周期。
6. 前端响应更快，运行中状态更实时。
7. 后端架构从“功能可用”升级到“可持续扩展”。
8. 为真实工具、长期记忆、多模态模型、外部 AI 编排框架留下明确接口，但默认不越过 MVP 安全边界。

