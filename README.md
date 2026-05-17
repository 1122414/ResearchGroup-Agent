# ResearchGroup-Agent

多 Agent 研究生课题组协作系统。导师 Agent 负责拆解研究目标、调度研究生 Agent、审核任务产出，并生成阶段性报告。

## 当前能力

- FastAPI 后端 + SQLite
- Next.js 16 / React 19 前端
- Mock LLM 模式，默认无需 API Key
- OpenAI-compatible LLM 接口
- Run / Task / Agent / SubAgent / Output 数据模型
- Run 事件日志：拆解、调度、执行、SubAgent、审核、报告
- LLM usage 记录：调用次数、token 估算、耗时、成本
- 前端运行详情页：`/runs/{run_id}`
- 前端停止运行按钮
- 前端设置面板：查看和切换 Mock 模式、模型配置、调度器参数
- 任务板可解释性：调度分、主要技能、SubAgent 标志、产出数量
- 像素办公室监控：`/office`

## 环境配置

复制环境变量文件：

```bash
cp .env.example .env
```

推荐本地先使用：

```ini
MOCK_MODE=true
```

如需真实模型：

```ini
MOCK_MODE=false
LLM_API_KEY=your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
```

模型、调度阈值、成本估算、CORS、轮询间隔等都集中在 `.env` / `.env.example` 中。

## 启动后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

后端地址：

- Health: http://localhost:8000/api/health
- Swagger: http://localhost:8000/docs

## 启动前端

```bash
cd frontend
npm install
npm.cmd run dev
```

前端地址：

- http://localhost:3000

PowerShell 如果拦截 `npm.ps1`，请使用 `npm.cmd`。

## 推荐调试流程

1. 打开首页 http://localhost:3000，输入研究目标。
2. 点击"创建并运行"。
3. 页面跳转到 `/runs/{run_id}`。
4. 在运行详情页查看：
   - 当前阶段
   - 事件时间线（实时轮询）
   - 任务执行表
   - Agent 活动
   - LLM usage 和成本
   - 停止运行按钮
5. 查看任务板：`/tasks?run_id={run_id}`
   - 点击任务卡查看调度信息、技能矩阵、产出列表
6. 查看输出中心：`/outputs?run_id={run_id}`
   - 按任务和类型过滤
7. 查看像素办公室：`/office?run_id={run_id}`
   - 实时查看 Agent 位置和状态
   - 悬停查看气泡文案
   - 点击角色或任务查看详情
8. 点击导航栏设置图标查看系统配置。

## P0 功能烟测

先启动后端，再运行：

```bash
python scripts/functional_p0_smoke.py
```

脚本会检查：

- 后端健康状态
- 设置 API
- 创建 Run
- 启动执行
- 任务拆解
- 事件日志
- LLM usage
- 最终报告输出
- 未开始 Run 的停止接口
- 像素办公室 API

## 升级版研究工作台验收

建议先使用 mock 模式完成闭环验收：

```ini
MOCK_MODE=true
```

启动后端后执行：

```bash
python scripts/functional_research_workbench_upgrade.py
```

该脚本会依次验证：

- 研究对象初始化；
- hypothesis 驱动的实验协议、实验结果与 finding；
- 迭代式研究编排快照；
- artifact manifest；
- 最终报告产物；
- claim / evidence 查询链路。

如果需要手动调试，优先看这几个接口：

```http
GET /api/runs/{run_id}/research-state
GET /api/runs/{run_id}/research-loop
GET /api/experiments/protocols?run_id={run_id}
GET /api/experiments/results?run_id={run_id}
GET /api/experiments/findings?run_id={run_id}
GET /api/runs/{run_id}/artifact-manifest
```

### 可信文献与自动推进

系统现在支持两层防线来避免“先编后补证据”：

1. 文献任务执行前先检索证据，再把 `allowed_sources` 注入研究生 Agent。
2. 研究生 Agent 只能引用白名单中的 `source_id`；若没有足够可信来源，会显式返回“证据不足”，而不是生成不可核验的参考文献。

相关配置可在前端设置中调整，也可以直接写入 `.env`：

```env
WEB_SEARCH_ENABLED=false
WEB_SEARCH_PROVIDER_MODE=tavily
TAVILY_API_KEY=
LITERATURE_REQUIRE_GROUNDED_SOURCES=true
LITERATURE_MIN_GROUNDED_SOURCES=1
CITATION_VALIDATION_ENABLED=true
RUN_INTERACTION_MODE=hitl
```

- `WEB_SEARCH_ENABLED=true` 后，当前会启用 Tavily 网络搜索工具；后续可以在同一工具边界下扩展更多搜索提供方。
- `RUN_INTERACTION_MODE=hitl` 表示需要人工确认实验、返工和最终报告；改成 `auto` 后，这些节点会自动放行，但仍保留审批审计记录。

新增功能验收脚本：

```bash
python scripts/functional_research_integrity_and_modes.py
```

它会验证：

- Tavily 工具能力已暴露；
- `auto` 模式下运行不会被人工确认阻塞；
- 没有可信来源时，文献任务返回“证据不足”而不是伪造引用；
- `waiting_confirmation` 状态的最近运行可以被删除。

## 常用 API

```http
POST /api/runs
POST /api/runs/{run_id}/start
POST /api/runs/{run_id}/cancel
GET  /api/runs/{run_id}/summary
GET  /api/runs/{run_id}/events
GET  /api/runs/{run_id}/usage
GET  /api/tasks?run_id={run_id}
GET  /api/outputs?run_id={run_id}
GET  /api/agents
GET  /api/settings
PATCH /api/settings
GET  /api/monitor/office-state?run_id={run_id}
```

## 开发边界

当前阶段不做：

- 多用户权限
- 外部工具接入（Zotero、Overleaf、Notion 等）
- 长期记忆或向量库
- WebSocket 强依赖（当前使用轮询）
- LangGraph / AutoGen / CrewAI 替换
- 复杂像素美术资产
- 账号系统、权限系统、OAuth
