# backend/app/prompts/ — Agent Prompt 提示词文件

## OVERVIEW
7个Markdown格式的Agent System Prompt, 通过 `PromptLoader` 加载。所有prompt独立于代码, 修改后无需重启即可生效(cache在内存)。中英文混合。

## STRUCTURE
```
prompts/
├── advisor_agent.md        # 导师Agent: 拆解任务、审核、总结 (role=advisor_decompose/review/report)
├── grad_researcher.md      # 调研型: 文献检索、论文总结 (skills: 文献调研10, 写作8)
├── grad_engineer.md        # 工程型: 架构设计、代码实现 (skills: 编码10, 实验7)
├── grad_experimenter.md    # 实验型: 实验设计、参数调优 (skills: 实验10, 分析8)
├── grad_analyst.md         # 数据分析型: 指标分析、可视化 (skills: 分析10, 实验8)
├── grad_writer.md          # 写作型: 周报、报告、润色 (skills: 写作10, 调研7)
└── subagent.md             # 本科生SubAgent: 临时子任务 (role=subagent)
```

## WHERE TO LOOK
| Role | File | 关键约束 |
|------|------|----------|
| 导师 | `advisor_agent.md` | 不能亲自执行; 必须输出JSON; 15%返工率; task_type枚举5选1 |
| 研究生通用 | `grad_*.md` | 可创建SubAgent; 可请求协作; 输出JSON; 不能改目标 |
| SubAgent | `subagent.md` | 6条严格禁止: 不改目标、不聊天、不创建子Agent、不决定结论、不访问全量上下文、不保留记忆 |

## CONVENTIONS
- 文件命名: `{role}_agent.md` 或 `{role}.md`
- Prompt结构: 角色定义 → 职责 → 能力(1-10) → 工作方式 → 约束 → 输出格式
- 使用 `PromptLoader.load("name")` 加载 (不含.md后缀)
- 通过 `prompt_loader.load_with_context("name", **kwargs)` 支持模板变量替换

## NOTES
- Mock模式下的行为差异在 `llm_provider.py` 中处理, 不在prompt中
- 研究生prompt中声明了能力分数, 但实际调度使用seed_agents.json中的分数
- subagent.md L15-21的6条禁止是运行时强制约束, 不仅限prompt
