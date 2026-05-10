# backend/app/services/ — 业务逻辑层 (12文件)

## OVERVIEW
项目最密集的子目录。7个活跃服务 + 4个预留stub + 1个agent注册中心。所有服务为模块级单例, 按需导入。

## STRUCTURE
```
services/
├── agent_registry.py           # Agent注册: 从seed_agents.json加载 → SQLite
├── task_decomposer.py          # 导师拆任务: LLM调用 → JSON解析 → 写入DB
├── task_scheduler.py           # 调度: 能力匹配分*0.7 + 空闲度*100*0.3
├── task_executor.py            # 任务执行: 按Agent类型选prompt → LLM生成结果
├── subagent_service.py         # SubAgent: 6条件门控 → 创建 → 执行 → 销毁
├── review_service.py           # 导师审核: LLM判断approved/need_revision
├── report_service.py           # 报告: 汇总完成tasks → final_report.md + artifacts
├── tool_provider.py            # [预留] 未来工具接入统一入口
├── agent_orchestrator.py       # [预留] LangGraph/AutoGen替换接口
├── skill_update_service.py     # [预留] 能力分数动态调整
└── external_memory.py          # [预留] 长期记忆/向量数据库
```

## WHERE TO LOOK
| Task | File | Key Logic |
|------|------|-----------|
| 任务拆解流程 | `task_decomposer.py:24-80` | `decompose()`: system_prompt + user_prompt → LLM → parse → DB insert |
| 调度匹配公式 | `task_scheduler.py:14-30` | `assign_owner()`: Σ(skill_i * required_i) ×0.7 + idle×100×0.3 |
| 协作触发条件 | `task_scheduler.py:33-50` | complexity≥7 OR load≥0.7 OR 跨领域 → 选≤2个collaborator |
| SubAgent门控 | `subagent_service.py:22-32` | complexity≥6, decomposability≥7, mentoring≥6, 最多floor(mentoring/3)个 |
| Mock路由 | `llm_provider.py:16-24` | advisor_decompose→5tasks, advisor_review→85%通过, graduate→按task_type返回 |
| 报告fallback | `report_service.py:90-150` | LLM失败时用 `_build_fallback_report()` 生成结构化报告 |

## CONVENTIONS
- 所有服务实例化为模块级单例: `xxx_service = XxxService()`
- LLM调用通过 `create_llm_provider()` 工厂 (mock_mode分支)
- Prompt加载通过 `prompt_loader.load("name")` → 从backend/app/prompts/读取
- DB操作通过Repository静态方法 (无ORM session管理)
- 任务状态流转: pending → assigned → running → waiting_review → completed/need_revision

## ANTI-PATTERNS
- 不要在服务中硬编码prompt文本 (使用prompt_loader)
- 不要直接操作SQLite (通过Repository)
- 不要绕过导师审核直接标记任务完成
- 不要实现4个预留stub (标记为 `NotImplementedError`)
