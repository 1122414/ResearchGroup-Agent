# ResearchGroup-Agent

多 Agent 研究生课题组协作系统。导师 Agent 负责拆解研究目标、调度研究生 Agent、审核任务产出，并生成阶段性报告。当前版本重点修复了 P0 可读性、运行事件、成本记录和停止接口。

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

1. 打开首页，输入研究目标。
2. 点击“创建并运行”。
3. 页面跳转到 `/runs/{run_id}`。
4. 在运行详情页查看：
   - 当前阶段
   - 事件时间线
   - 任务执行表
   - Agent 活动
   - LLM usage 和成本
   - 停止运行按钮
5. 查看任务板：`/tasks?run_id={run_id}`。
6. 查看输出中心：`/outputs?run_id={run_id}`。

## P0 功能烟测

先启动后端，再运行：

```bash
python scripts/functional_p0_smoke.py
```

脚本会检查：

- 后端健康状态
- 创建 Run
- 启动执行
- 任务拆解
- 事件日志
- LLM usage
- 最终报告输出
- 未开始 Run 的停止接口

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
```

## 开发边界

当前 P0 阶段不做：

- 多用户权限
- 外部工具接入
- 长期记忆或向量库
- WebSocket 强依赖
- LangGraph / AutoGen / CrewAI 替换
- 像素办公室动画

像素办公室监控已在 `plan_/5.10` 中规划，建议等 P0 稳定后再做。
