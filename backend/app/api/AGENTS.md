# backend/app/api/ — REST API路由层

## OVERVIEW
4个FastAPI Router, 前缀 `/api/{resource}`, 在 `backend/main.py:40-43` 注册。GET读/查询, POST写/触发。所有路由直接调用Repository静态方法。

## STRUCTURE
```
api/
├── routes_agents.py     # GET /api/agents, GET /api/agents/{id}
├── routes_tasks.py      # GET /api/tasks?run_id=X, GET /api/tasks/{id}
├── routes_runs.py       # POST /api/runs, GET /api/runs, GET /api/runs/{id}/run_all
└── routes_outputs.py    # GET /api/outputs?run_id=X, GET /api/outputs/{id}
```

## WHERE TO LOOK
| Endpoint | File | Method | Purpose |
|----------|------|--------|---------|
| 创建Run | `routes_runs.py:32` | POST `/api/runs` | body: `{research_goal}` → UUID run_id |
| 执行完整流程 | `routes_runs.py:55-118` | POST `/api/runs/{id}/run_all` | 5步: 拆解→调度→执行→审核→报告 |
| 获取任务 | `routes_tasks.py:9` | GET `/api/tasks` | 可选 `?run_id=X` 过滤 |
| 获取产出 | `routes_outputs.py:8` | GET `/api/outputs` | 可选 `?run_id=X` 过滤 |

## CONVENTIONS
- Router变量名 `router`, 前缀 `/api/{resource}`, tags `["{resource}"]`
- 响应格式: `{"agents": [...]}`, `{"tasks": [...]}`, `{"run": {...}, "tasks": [...]}`
- 404用 `HTTPException(status_code=404)`, 500用 `HTTPException(status_code=500)`
- POST body用Pydantic模型验证 (如 `RunCreateRequest`)
- run_all是同步等待 (await每个阶段), 非后台任务

## NOTES
- `routes_runs.py` 直接导入所有service单例, 是最耦合的路由文件
- `routes_outputs.py` GET /{id} 依赖 `OutputRepository.get_by_id()`
- 所有路由无认证/鉴权 (MVP单用户)
