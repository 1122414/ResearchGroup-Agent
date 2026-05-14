# ResearchGroup-Agent — Project Knowledge Base

**Generated:** 2026-05-12
**Commit:** 545d650
**Branch:** main

## OVERVIEW
多Agent模拟研究生课题组协作系统。Python FastAPI 后端 + Next.js 16/React 19 前端 + SQLite。导师Agent拆解任务→调度器按能力矩阵分配→五类研究生Agent执行→SubAgent临时委派→导师审核→生成阶段性报告。

## STRUCTURE
```
./
├── backend/              # Python FastAPI (33 .py files)
│   └── app/
│       ├── api/          # REST路由 (agents, tasks, runs, outputs)
│       ├── core/         # 配置、LLM Provider、Prompt加载
│       ├── models/       # Pydantic数据模型 (Agent, Task, Run, Output, SubAgent)
│       ├── services/     # 业务逻辑 (10服务 + 4预留接口)
│       ├── storage/      # SQLite初始化 + Repository模式
│       ├── prompts/      # 7个Agent Prompt .md文件
│       └── data/         # 种子数据 JSON
├── frontend/             # Next.js 16 + React 19 + shadcn/ui v4 + Tailwind v4
│   └── src/
│       ├── app/          # App Router页面 (首页, /tasks, /agents, /outputs)
│       ├── components/ui/# shadcn/ui primitives (card, badge, separator, tabs, button)
│       └── lib/          # API client + TypeScript类型定义
├── artifacts/            # 运行时产出物 (reports, logs, runs)
├── plan_/                # 规划文档 (MVP实现计划 + 全局大纲 + 可行性分析)
├── .env                  # 环境变量 (需自行创建)
├── test_runner.py        # E2E功能测试 (6阶段)
└── README.md             # 完整使用文档
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| 后端启动入口 | `backend/main.py:25` | FastAPI app + lifespan + uvicorn.run |
| LLM调用 | `backend/app/core/llm_provider.py` | MockLLMProvider + OpenAICompatibleProvider |
| 任务拆解 | `backend/app/services/task_decomposer.py` | 导师Agent拆研究目标为任务列表 |
| 调度算法 | `backend/app/services/task_scheduler.py:14-30` | 能力匹配分 * 0.7 + 空闲度 * 100 * 0.3 |
| SubAgent管理 | `backend/app/services/subagent_service.py:22-32` | 6条件门控触发 |
| 报告生成 | `backend/app/services/report_service.py` | Markdown + artifacts文件输出 |
| 前端API调用 | `frontend/src/lib/api.ts` | fetch封装, API_BASE=localhost:8000 |
| 类型定义 | `frontend/src/lib/types.ts` | SkillSet, Agent, Task, Run, Output + 中文标签映射 |
| 预留接口 | `backend/app/services/tool_provider.py` 等4个 | stub, MVP阶段不实现 |
| 环境配置 | `.env` / `backend/app/core/config.py` | 所有可配常量集中管理 |

## CONVENTIONS
- **Python**: Pydantic v2模型, SQLAlchemy v2, FastAPI >=0.110, 相对导入
- **TypeScript**: Next.js 16 App Router, `"use client"` 标记交互页面, `@/` 路径别名
- **Tailwind v4**: CSS-native配置 (@theme), 非 tailwind.config.js
- **shadcn/ui v4**: 使用 @base-ui/react primitives (非Radix), base-nova风格
- **Mock优先**: MOCK_MODE=true为默认, 无API Key也能完整运行
- **服务单例**: 所有service实例化为模块级变量 (如 `task_scheduler = TaskScheduler()`)
- **Prompt外置**: 所有Agent Prompt写在 `backend/app/prompts/*.md`, 不硬编码
- **SQLite直接SQL**: 不使用ORM migration, `init_db()` 建表

## ANTI-PATTERNS
### Never (MVP严禁)
- 实现复杂科研自动化 (论文发表、模型训练、集群调度)
- 构建权限/账号系统 (多用户、OAuth、SSO)
- 做大屏可视化 (3D、WebSocket、拖拽编排)
- 接入外部工具 (Zotero、Overleaf、Notion等)
- Agent无约束自由聊天 (必须围绕任务板状态机)
- SubAgent: 改变目标、创建子Agent、访问全量上下文、保留记忆
- 实现4个预留接口 (ToolProvider/AgentOrchestrator/SkillUpdateService/ExternalMemory)
- SubAgent结果绕过研究生Agent审查直接进入报告

### Always
- Agent输出必须是合法JSON
- SubAgent结果必须经研究生Agent检查和整合
- Agent行为绑定到任务板状态机
- 每次Run必须生成artifacts文件
- MVP必须支持MOCK_MODE=true
- Prompt不许硬编码在Python代码中

## COMMANDS
```bash
# 后端
cd backend && pip install -r requirements.txt
cd backend && python main.py                    # → http://localhost:8000

# 前端
cd frontend && npm install
cd frontend && npm run dev                      # → http://localhost:3000
cd frontend && npm run build                    # 生产构建
cd frontend && npm run lint                     # ESLint

# 测试
python test_runner.py                           # 需后端已启动, 6阶段E2E

# 环境
cp .env.example .env                            # 创建配置 (编辑LLM_API_KEY)
```

## NOTES
- Next.js 16 + React 19 + Tailwind v4 均为大版本跳跃, 查阅 `node_modules/next/dist/docs/`
- 前端 `API_BASE` 硬编码 `http://localhost:8000`, 生产部署需代理或环境变量
- 无CI/CD配置, 无Docker, 无数据库迁移工具 — MVP范围外
- pytest声明为依赖但无测试文件, test_runner.py是唯一测试
- `.env` 中 `LLM_API_KEY=` 留空, 用户自行填写
