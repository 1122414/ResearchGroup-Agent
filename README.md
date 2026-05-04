# ResearchGroup-Agent

面向研究生课题组场景的多 Agent 协作与产出管理系统。模拟真实科研课题组运行方式：导师 Agent 负责规划和审核，五类研究生 Agent 按能力画像分工协作，本科生 SubAgent 执行临时子任务，系统负责调度、追踪、可视化和阶段性产出沉淀。

## 项目结构

```
├── backend/              # Python FastAPI 后端
│   ├── main.py           # 启动入口
│   ├── requirements.txt  # Python 依赖
│   ├── app/
│   │   ├── api/          # RESTful API 路由
│   │   ├── core/         # 配置、LLM Provider、Prompt 加载
│   │   ├── models/       # Pydantic 数据模型
│   │   ├── services/     # 业务逻辑服务（含预留接口）
│   │   ├── storage/      # SQLite 数据库 + Repository
│   │   ├── prompts/      # Agent Prompt 提示词文件
│   │   └── data/         # 种子数据
├── frontend/             # Next.js + shadcn/ui 前端
│   ├── src/app/          # 页面（首页/任务板/Agent/产出）
│   └── src/lib/          # API 客户端 + TypeScript 类型
├── artifacts/            # 运行产出物（报告、日志）
├── .env                  # 环境变量配置（需自行创建）
├── .env.example          # 环境变量模板
└── test_runner.py        # 自动化功能测试脚本
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- npm

### 1. 配置环境变量

```bash
# 复制模板
cp .env.example .env
```

编辑 `.env`，配置 LLM API（可选，默认使用 Mock 模式）：

```ini
# 使用 Mock 模式（无需 API Key）
MOCK_MODE=true

# 或接入真实 API
MOCK_MODE=false
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt   # 首次运行需安装依赖
python main.py                     # 启动后端服务
```

后端启动后访问：
- API 健康检查：http://localhost:8000/api/health
- API 文档（Swagger）：http://localhost:8000/docs

### 3. 启动前端

```bash
cd frontend
npm install        # 首次运行需安装依赖
npm run dev        # 启动前端开发服务器
```

前端启动后访问：http://localhost:3000

## 调试与测试

### 运行自动化测试

```bash
# 1. 确保后端已启动（另一个终端）
cd backend && python main.py

# 2. 运行测试脚本
python test_runner.py
```

测试脚本会自动检查：
1. 后端健康状态
2. Agent 数据加载（5 个研究生 Agent + 能力矩阵）
3. 创建 Run 并执行 run_all 完整流程
4. 任务板状态验证
5. 产出物验证（tasks.json / agent_assignments.json / final_report.md / run_log.md）
6. SubAgent 调用验证

预期输出：**6/6 通过**。

### 手动 API 测试

```bash
# 创建研究运行
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{"research_goal": "测试研究目标"}'

# 执行完整流程（返回 run_id 后替换）
curl -X POST http://localhost:8000/api/runs/{run_id}/run_all

# 查看任务状态
curl http://localhost:8000/api/tasks?run_id={run_id}

# 查看 Agent 状态
curl http://localhost:8000/api/agents

# 查看产出
curl http://localhost:8000/api/outputs?run_id={run_id}
```

### 前端验收流程

1. 打开 http://localhost:3000
2. 输入研究目标（或点击"填入示例"）
3. 点击"启动虚拟课题组"
4. 观察任务板状态变化：http://localhost:3000/tasks
5. 查看 Agent 状态面板：http://localhost:3000/agents
6. 查看阶段性报告：http://localhost:3000/outputs

### 切换 Mock / 真实 API 模式

编辑 `.env` 文件中的 `MOCK_MODE`：
- `MOCK_MODE=true` — 使用内置 Mock Provider，无需 API Key，适合演示
- `MOCK_MODE=false` — 使用真实 OpenAI-compatible API，需配置 `LLM_API_KEY`

## 开发要点

### 预留扩展接口

以下接口已预留空实现，后续可逐步启用：

| 接口 | 文件 | 用途 |
|------|------|------|
| `ToolProvider` | `backend/app/services/tool_provider.py` | 未来工具接入（文献搜索、代码执行等） |
| `AgentOrchestrator` | `backend/app/services/agent_orchestrator.py` | 替换为 LangGraph/AutoGen 等框架 |
| `SkillUpdateService` | `backend/app/services/skill_update_service.py` | Agent 能力分数动态调整 |
| `ExternalMemory` | `backend/app/services/external_memory.py` | 长期记忆和知识库 |

### 架构说明

- **能力矩阵**：5 类研究生 Agent，每类 6 个能力维度（1-10 分），MVP 阶段使用固定分数
- **调度算法**：`能力匹配分 * 0.7 + 空闲程度 * 100 * 0.3`，选最高分 Agent 为主责
- **SubAgent**：满足复杂度 ≥6、可拆分性 ≥7、指导能力 ≥6 时自动创建，用完销毁
- **Mock Provider**：返回预设结构化 JSON，确保无 API Key 时也能运行完整闭环
