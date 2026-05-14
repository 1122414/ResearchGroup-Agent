# backend/ — Python FastAPI Backend

## OVERVIEW
FastAPI后端, 分层架构: api(路由) → services(业务) → storage(数据)。所有Agent编排、任务调度、LLM调用逻辑在此。

## STRUCTURE
```
backend/
├── main.py                  # 入口: lifespan(init_db+seed) → CORS → 4 routers → uvicorn
├── requirements.txt         # Python 3.11+ 依赖
└── app/
    ├── api/                 # REST路由 → backend/app/api/AGENTS.md
    ├── core/                # config(.env加载), LLMProvider(Mock+OpenAI), PromptLoader
    ├── models/              # Pydantic v2: Agent, Task, SubAgent, Output, Run + 枚举
    ├── services/            # 业务服务 → backend/app/services/AGENTS.md
    ├── storage/             # SQLite init(db.py) + Repository模式(repositories.py)
    ├── prompts/             # Agent Prompt → backend/app/prompts/AGENTS.md
    └── data/                # 种子数据: seed_agents.json, seed_task_templates.json
```

## WHERE TO LOOK
| Component | File | Key Lines |
|-----------|------|-----------|
| 启动入口 | `main.py` | L25 FastAPI(), L18 lifespan, L40 routers, L53 uvicorn.run |
| 配置 | `app/core/config.py` | L16 `class Settings` — 自动从.env加载, `@lru_cache`单例 |
| LLM工厂 | `app/core/llm_provider.py` | L193 `create_llm_provider()` — mock_mode分支 |
| DB初始化 | `app/storage/db.py` | L21 `init_db()` — CREATE TABLE IF NOT EXISTS ×5 |
| 数据访问 | `app/storage/repositories.py` | AgentRepository, TaskRepository, RunRepository等5个 |
| 种子数据 | `app/data/seed_agents.json` | 5个研究生Agent的能力矩阵 (6维, 1-10分) |

## CONVENTIONS
- **相对导入**: `from ..storage.repositories import ...`
- **服务单例**: 所有service模块底部实例化 (如 `task_decomposer = TaskDecomposer()`)
- **空`__init__.py`**: 大部分子包`__init__.py`为空, 仅`storage/__init__.py`有`__all__`导出
- **Pydantic v2**: `model_validate`/`model_dump`, 使用`Field(default=..., ge=, le=)`
- **SQLite直接SQL**: 无ORM, 无alembic, `init_db()`用raw SQL建表
- **sys.path处理**: `main.py` L4插入backend目录到path, 支持直接`python main.py`运行

## NOTES
- `sys.path.insert` 是为了支持 `python backend/main.py` 直接运行, uvicorn模式不需要
- 无reload模式 (uvicorn.run未传reload=True), 开发需手动重启
- CORS origins loaded from `.env` via `settings.parsed_cors_origins` (main.py:45)
- 4个预留service文件在services/中但标记为stub, 导入安全但不调用
