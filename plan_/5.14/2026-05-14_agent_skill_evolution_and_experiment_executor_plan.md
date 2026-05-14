# ResearchGroup-Agent Agent Skill 自动进化与实验执行器实施计划

**日期:** 2026-05-14  
**目标读者:** opencode / 后续实现 Agent  
**当前状态:** 设置弹框居中问题已修复。本计划只覆盖后续两项能力设计与实施：Agent Skill 自动沉淀、实验 Agent 受控代码执行。  
**执行原则:** 先做可审查、可回滚、可扩展的 MVP，不做无边界自主执行。

---

## 0. 总体目标

当前系统已经具备导师拆解任务、研究生执行、导师审核、最终报告生成等基本链路。下一阶段要补两个高价值能力：

1. **Agent 自动进化 / Skill 沉淀**
   - 每个 Agent 在完成具体任务后，能够将确实可复用的经验总结为 skill。
   - 每个 Agent 拥有自己的 skill 文件夹和可管理 skill 列表。
   - 用户可以在前端对 skill 进行增删改查、启用/禁用、归档/恢复，变更必须同步到后端持久层。

2. **实验 Agent 受控执行代码**
   - 实验研究生 Agent 不再只写实验方案，而是可以在用户指定 workspace 中生成、审查、执行实验代码。
   - 所有危险行为必须经过用户确认。
   - 用户可配置本地/服务器等执行环境、环境变量、工作区路径和安全策略。
   - 实验产物要作为 artifacts 进入任务输出和最终报告。

---

## 1. 任务边界

### 本阶段必须做

- 增加 Agent Skill 的后端数据模型、存储、服务层、API。
- 增加前端 Agent Skill 管理界面，支持增删改查。
- 增加任务完成后的 skill 候选生成与评估流程。
- 增加 skill 文件持久化目录结构。
- 增加实验执行器的配置模型、审查队列、危险行为扫描、执行记录和 artifacts 收集。
- 增加实验 Agent 的“生成代码 -> 用户审查 -> 执行 -> 收集结果 -> 总结输出”最小闭环。
- 增加必要测试脚本和功能冒烟脚本。
- 所有新增能力必须支持 `MOCK_MODE=true`。

### 本阶段严禁做

- 严禁让 Agent 未经用户审查直接执行危险命令。
- 严禁让实验 Agent 默认访问整个磁盘，只能访问用户配置的 workspace。
- 严禁把用户完整 `.env`、API Key、上传原文、隐私数据自动沉淀进 skill。
- 严禁 SubAgent 写入长期 skill。SubAgent 只能向所属研究生 Agent 返回候选观察。
- 严禁 Agent 自动修改核心 prompt、系统设置、全局策略。
- 严禁实现账号权限、多用户隔离、OAuth、云端同步。
- 严禁一上来接 Docker/K8s/远程队列完整能力，本阶段只预留接口。
- 严禁大规模重写现有任务调度和报告生成链路。

---

## 2. 开发优先级总览

### P0: 数据边界与安全基线

- 定义 skill 文件目录、数据库表、API 契约。
- 定义实验 workspace、安全策略、命令风险扫描、用户确认流程。
- 前端先能展示和管理 skill。
- 后端先能保存、读取、更新、删除 skill。

### P1: Skill 候选生成与审慎沉淀

- 在任务完成后生成 `experience_reflection`。
- 用评估器判断是否值得沉淀。
- 只把高置信、可复用、无敏感信息的内容写为 skill。
- skill 写入后可被 Agent 后续任务检索和注入 prompt。

### P2: 实验 Agent 受控执行闭环

- 实验 Agent 生成实验计划和代码。
- 前端显示待审查代码、命令、环境变量需求、风险提示。
- 用户确认后执行。
- 执行结果写入 artifacts 并回流任务输出。

### P3: 质量提升与可观测性

- Skill 命中统计、失效标记、合并建议。
- 实验执行日志、资源限制、超时控制、失败重试。
- 后续 Docker/远程服务器执行接口接入。

---

## 3. Agent Skill 自动进化详细计划

### 3.1 数据目录设计

建议新增目录：

```text
artifacts/
  agent_skills/
    advisor/
      skills/
        skill_xxx.md
      archived/
        skill_xxx.md
    literature_researcher/
      skills/
      archived/
    engineering_researcher/
      skills/
      archived/
    experiment_researcher/
      skills/
      archived/
    data_analysis_researcher/
      skills/
      archived/
    writing_researcher/
      skills/
      archived/
```

说明：

- `skills/` 存放启用或可启用 skill。
- `archived/` 存放归档 skill，不参与 Agent 上下文注入。
- 文件名建议：`YYYYMMDD_<slug>_<short_id>.md`。
- 不允许 SubAgent 拥有长期 skill 目录。

### 3.2 Skill Markdown 格式

每个 skill 文件必须是可读 Markdown，带 YAML frontmatter。

```markdown
---
id: skill_20260514_xxxxxxxx
agent_id: experiment_researcher
title: 可复现实验结果记录模板
status: active
confidence: 0.82
source_run_id: run_xxxxxxxx
source_task_id: task_xxxxxxxx
created_at: 2026-05-14T20:00:00+08:00
updated_at: 2026-05-14T20:00:00+08:00
last_used_at:
usage_count: 0
failure_count: 0
tags:
  - experiment
  - reproducibility
---

# 可复现实验结果记录模板

## 适用场景

说明什么时候应该使用该 skill。

## 触发条件

- 当任务需要比较多个实验方案。
- 当用户需要最终报告引用可复现实验结果。

## 操作步骤

1. 固定实验输入、随机种子和运行环境。
2. 保存命令、stdout、stderr、退出码。
3. 汇总指标并写入 artifacts。

## 反例

- 一次性事实查询不应使用该 skill。
- 无法复现实验环境时不要伪造结果。

## 来源摘要

本 skill 来自哪次任务，遇到什么问题，如何解决。
```

### 3.3 后端模型

新增文件建议：

- `backend/app/models/agent_skill.py`
- `backend/app/services/agent_skill_service.py`
- `backend/app/services/skill_reflection_service.py`
- `backend/app/services/skill_evaluator.py`
- `backend/app/api/routes_agent_skills.py`

建议模型字段：

```python
class AgentSkill(BaseModel):
    id: str
    agent_id: str
    title: str
    description: str
    content: str
    status: Literal["draft", "active", "disabled", "archived"]
    confidence: float
    source_run_id: str | None
    source_task_id: str | None
    tags: list[str]
    usage_count: int
    failure_count: int
    created_at: str
    updated_at: str
    last_used_at: str | None
```

SQLite 表建议：

```sql
CREATE TABLE IF NOT EXISTS agent_skills (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    source_run_id TEXT,
    source_task_id TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    file_path TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT
);
```

### 3.4 后端 API

新增路由前缀：`/api/agent-skills`

必须实现：

- `GET /api/agent-skills?agent_id=&status=&q=`
  - 获取 skill 列表。
- `GET /api/agent-skills/{skill_id}`
  - 获取单个 skill 详情。
- `POST /api/agent-skills`
  - 用户手动新增 skill。
- `PATCH /api/agent-skills/{skill_id}`
  - 用户编辑 title、description、content、tags、status。
- `DELETE /api/agent-skills/{skill_id}`
  - 默认软删除或归档，不直接物理删除。
- `POST /api/agent-skills/{skill_id}/restore`
  - 从 archived 恢复。
- `POST /api/agent-skills/{skill_id}/disable`
  - 禁用，不参与 prompt 注入。
- `POST /api/agent-skills/{skill_id}/enable`
  - 启用。

后续预留：

- `POST /api/agent-skills/{skill_id}/merge`
- `POST /api/agent-skills/evaluate-candidate`
- `GET /api/agent-skills/{skill_id}/history`
- `POST /api/agent-skills/{skill_id}/rollback`

### 3.5 前端 CRUD 设计

必须在前端落实用户对 skill 的增删改查。

建议页面：

- `/agents` 页面：每个 Agent 卡片增加 “Skills” 入口。
- 新增 `/agents/[agent_id]/skills` 或在 Agent 详情里增加 Tab。
- 也可新增全局 `/skills` 页面，支持按 Agent 过滤。

必须功能：

- Skill 列表：
  - Agent 筛选
  - 状态筛选：active / disabled / archived / draft
  - 搜索 title / tags / description
  - 显示 confidence、usage_count、failure_count、更新时间
- Skill 详情：
  - Markdown 渲染
  - YAML metadata 以只读摘要展示
- 新增：
  - 表单填写 title、agent_id、tags、content
  - 默认 status 为 `draft` 或 `active`，建议用户手动新增默认 `active`
- 编辑：
  - 可编辑 title、description、tags、content、status
  - 保存后调用后端 PATCH，并同步更新 skill 文件
- 删除：
  - 前端显示“归档”而不是永久删除
  - 二次确认
  - 调用 DELETE，后端移动到 archived
- 启用/禁用：
  - 快捷按钮
  - disabled 不进入 Agent 上下文

严禁：

- 前端直接写文件。
- 前端绕过后端 API 修改 skill。
- 删除按钮直接物理删除文件。

### 3.6 Skill 候选生成流程

任务执行完成后，研究生 Agent 或导师 Agent 生成 `experience_reflection`。

建议在 `RunExecutionService` 中的任务审核通过后插入：

```text
task completed
  -> generate_experience_reflection(agent_id, task, output, review)
  -> evaluate_skill_candidate(reflection)
  -> if accepted: create_skill(status="draft" or "active")
  -> emit run event skill.created / skill.rejected
```

### 3.7 Skill 是否值得沉淀的评估标准

必须满足：

- 可复用：未来同类任务能直接使用。
- 具体：不是“要认真分析”这种空话。
- 有边界：说明什么时候不能用。
- 有收益：能降低执行成本、减少错误或提升输出质量。
- 无敏感信息：不包含用户密钥、完整上传原文、隐私数据。
- 非一次性事实：例如某篇论文的具体内容不应沉淀为通用 skill。

建议评分：

```text
reusability >= 0.7
specificity >= 0.7
safety >= 0.9
novelty >= 0.5
```

低于阈值：

- 不写 skill。
- 可保留为 run event 或短期 reflection，但不进入长期记忆。

### 3.8 Skill 注入 Agent 上下文

在 Agent 执行任务前：

- 按 agent_id 查询 active skills。
- 根据 task_type、required_skills、tags、关键词做轻量匹配。
- 最多注入 3-5 条 skill 摘要，不要把整个技能库塞进 prompt。
- 使用后增加 `usage_count` 和 `last_used_at`。
- 如果使用后任务失败或导师指出 skill 误导，增加 `failure_count`。

严禁：

- 不允许 active skill 无限增长导致 prompt 膨胀。
- 不允许 archived / disabled skill 注入。
- 不允许跨 Agent 默认共享 skill。跨 Agent 共享必须后续单独设计。

### 3.9 Skill 删改策略

用户手动：

- 编辑：更新 DB 与 Markdown 文件。
- 禁用：status 改为 disabled，文件仍留在 skills。
- 归档：status 改为 archived，文件移动到 archived。
- 恢复：从 archived 移回 skills。

系统建议：

- `failure_count >= 3`：标记为 `needs_review` 或建议禁用。
- `usage_count=0` 且超过 N 天：建议归档。
- 与新 skill 高相似：建议合并。

本阶段不要自动物理删除。

---

## 4. 实验 Agent 受控执行代码详细计划

### 4.1 目标

实验研究生 Agent 可以真实运行代码，得到实验结果，但必须受控：

- 用户配置 workspace。
- 用户审查代码、命令和环境变量。
- 危险行为必须确认。
- 输出完整 artifacts。

### 4.2 配置项

新增 `.env` / 设置页面字段：

```env
EXPERIMENT_EXECUTION_ENABLED=false
EXPERIMENT_WORKSPACE_DIR=artifacts/experiment_workspace
EXPERIMENT_EXECUTION_BACKEND=local
EXPERIMENT_COMMAND_TIMEOUT_SECONDS=300
EXPERIMENT_MAX_OUTPUT_CHARS=20000
EXPERIMENT_ALLOW_NETWORK=false
EXPERIMENT_ALLOW_PACKAGE_INSTALL=false
EXPERIMENT_REQUIRE_REVIEW=true
EXPERIMENT_ENV_FILE=
```

后续预留：

```env
EXPERIMENT_REMOTE_HOST=
EXPERIMENT_REMOTE_PORT=
EXPERIMENT_DOCKER_IMAGE=
EXPERIMENT_QUEUE_BACKEND=
```

### 4.3 后端模块

新增建议：

- `backend/app/models/experiment.py`
- `backend/app/services/experiment_executor.py`
- `backend/app/services/experiment_workspace_service.py`
- `backend/app/services/command_risk_scanner.py`
- `backend/app/services/execution_review_service.py`
- `backend/app/api/routes_experiments.py`

核心接口：

```python
class ExperimentPlan(BaseModel):
    id: str
    run_id: str
    task_id: str
    agent_id: str
    workspace_dir: str
    files: list[ExperimentFile]
    commands: list[ExperimentCommand]
    env_vars: dict[str, str]
    risk_level: Literal["safe", "needs_review", "dangerous"]
    status: Literal["draft", "pending_review", "approved", "running", "completed", "failed", "rejected"]
```

### 4.4 API 设计

新增前缀：`/api/experiments`

必须实现：

- `GET /api/experiments/config`
- `PATCH /api/experiments/config`
- `POST /api/experiments/plans`
  - 创建实验计划，通常由实验 Agent 生成。
- `GET /api/experiments/plans?run_id=&task_id=`
- `GET /api/experiments/plans/{plan_id}`
- `PATCH /api/experiments/plans/{plan_id}`
  - 用户或前端编辑计划。
- `POST /api/experiments/plans/{plan_id}/scan`
  - 风险扫描。
- `POST /api/experiments/plans/{plan_id}/approve`
  - 用户批准。
- `POST /api/experiments/plans/{plan_id}/reject`
  - 用户拒绝。
- `POST /api/experiments/plans/{plan_id}/execute`
  - 执行已批准计划。
- `GET /api/experiments/plans/{plan_id}/artifacts`
  - 获取输出文件、日志、图表。

后续预留：

- `POST /api/experiments/plans/{plan_id}/execute-remote`
- `POST /api/experiments/plans/{plan_id}/execute-docker`
- `GET /api/experiments/executors`

### 4.5 前端页面

建议在设置页增加实验配置区：

- 是否启用实验执行。
- workspace 路径。
- 执行环境：本地 / 服务器预留 / Docker 预留。
- 命令超时。
- 是否允许联网。
- 是否允许安装依赖。
- 是否强制用户审查。
- 环境变量配置文件路径。

建议新增实验审查页面：

- `/experiments`
- 或任务详情中显示 “实验执行审查”

页面必须展示：

- Agent 生成的文件列表和代码 diff。
- 待执行命令。
- 需要的环境变量。
- workspace 路径。
- 风险扫描结果。
- 用户确认/拒绝按钮。
- 执行日志。
- 生成 artifacts。

### 4.6 危险行为扫描规则

本阶段先实现静态规则，不引入复杂沙箱。

危险命令示例：

- 删除：`rm -rf`, `del /s`, `Remove-Item -Recurse`
- 磁盘破坏：格式化、分区、注册表修改
- 系统目录写入：`C:\Windows`, `/etc`, `/usr/bin`
- 密钥读取：读取 `.env`、SSH key、浏览器 cookie
- 联网：`curl`, `wget`, 任意请求外部 API
- 安装依赖：`pip install`, `npm install`, `conda install`
- 后台常驻：`Start-Process`, `nohup`, `&`
- 提权：`sudo`, `runas`

风险分级：

- `safe`: 只在 workspace 内读写，命令白名单。
- `needs_review`: 安装依赖、联网、运行未知脚本。
- `dangerous`: 删除、提权、系统目录写入、读取敏感文件。

默认策略：

- `safe` 且 `EXPERIMENT_REQUIRE_REVIEW=false` 可直接执行。
- 其他都必须用户确认。
- `dangerous` 即使确认也要展示强警告。

### 4.7 执行产物

每次执行创建目录：

```text
artifacts/
  runs/
    run_xxxxxxxx/
      experiments/
        plan_xxxxxxxx/
          plan.json
          files/
          stdout.log
          stderr.log
          result.json
          metrics.json
          summary.md
```

`result.json` 至少包含：

```json
{
  "exit_code": 0,
  "started_at": "",
  "completed_at": "",
  "duration_ms": 0,
  "commands": [],
  "artifacts": [],
  "risk_level": "safe"
}
```

### 4.8 与报告链路集成

实验结果进入任务输出：

- `task.outputs` 增加 `experiment_result` 类型。
- 导师审核时看到实验计划、风险结果、执行日志摘要和 metrics。
- 最终报告引用实验结果时必须注明：
  - workspace
  - 执行命令
  - 执行时间
  - 退出码
  - 关键指标

严禁：

- 报告中伪造实验结果。
- 实验失败却写成成功。
- 丢弃 stderr 和失败原因。

---

## 5. 推荐实施步骤

### 阶段 A: Agent Skill CRUD 基础设施

要做：

- 新增 `agent_skills` 表。
- 新增 `AgentSkillRepository`。
- 新增 `AgentSkillService`。
- 新增 `/api/agent-skills` CRUD。
- 新增 skill Markdown 文件读写。
- 前端新增 Skill 管理页面或 Agent 详情 Tab。

验收：

- 用户能在前端创建 skill。
- 后端 DB 有记录。
- `artifacts/agent_skills/{agent_id}/skills/*.md` 有文件。
- 用户能编辑、禁用、归档、恢复 skill。

严禁：

- 不做自动沉淀。
- 不接 Agent prompt 注入。
- 不做跨 Agent 共享。

### 阶段 B: Skill 候选生成与评估

要做：

- 新增 `SkillReflectionService`。
- 新增 `SkillEvaluator`。
- 在任务完成后生成候选。
- 通过评估后写入 draft 或 active。
- 生成 `skill.created` / `skill.rejected` run event。

验收：

- 任务完成后能看到 skill 候选记录。
- 不合格经历不会写入 skill。
- 生成内容不含敏感信息。

严禁：

- 不允许 SubAgent 直接写 skill。
- 不允许所有经历都沉淀。

### 阶段 C: Skill 注入与使用统计

要做：

- Agent 执行前按任务匹配 active skill。
- 最多注入 3-5 条。
- 更新 usage_count / last_used_at。
- 失败或导师负反馈更新 failure_count。

验收：

- Agent prompt 中能看到相关 skill 摘要。
- disabled/archived skill 不注入。
- 使用统计正确。

严禁：

- 不允许注入全量 skill 库。

### 阶段 D: 实验执行配置与审查队列

要做：

- 新增实验配置模型和设置接口。
- 前端设置页加入实验执行配置。
- 新增实验计划模型。
- 实验 Agent 先生成 pending_review 计划。
- 前端可查看计划、代码、命令和风险。

验收：

- 用户能配置 workspace。
- 实验计划不会自动执行。
- 用户能批准或拒绝。

严禁：

- 不允许此阶段执行真实命令。

### 阶段 E: 本地实验执行器 MVP

要做：

- 实现 workspace 限制。
- 实现命令风险扫描。
- 实现受控执行。
- 记录 stdout/stderr/exit_code。
- artifacts 回流任务输出。

验收：

- safe 命令能在 workspace 内执行。
- dangerous 命令必须确认。
- 超时会终止。
- 结果能进入任务详情和最终报告。

严禁：

- 不做服务器执行。
- 不做 Docker 隔离。
- 不允许读写 workspace 外路径。

### 阶段 F: 测试与文档

要做：

- 增加后端 API 测试。
- 增加前端基础交互测试或手动测试清单。
- 增加 `scripts/functional_smoke_agent_skills.py`。
- 增加 `scripts/functional_smoke_experiments.py`。
- 更新 README。

验收：

- MOCK 模式下可跑完整功能冒烟。
- 文档说明如何配置 workspace 和确认危险命令。

---

## 6. 测试清单

### Skill CRUD

- 创建 skill。
- 编辑 title/content/tags。
- 禁用 skill。
- 启用 skill。
- 归档 skill。
- 恢复 skill。
- 删除不存在 skill 返回 404。
- archived skill 不参与注入。

### Skill 自动沉淀

- 低价值 reflection 被拒绝。
- 高价值 reflection 生成 skill。
- 含 `.env` 或 key-like 文本的候选被拒绝或脱敏。
- SubAgent 结果只作为输入，不直接写 skill。

### 实验执行

- 未配置 workspace 时不能执行。
- workspace 外路径被拒绝。
- safe 命令执行成功。
- 超时命令被终止。
- 删除命令被标记 dangerous。
- 安装依赖命令按配置进入 needs_review。
- 执行结果写入 artifacts。
- 失败结果也进入任务输出，不伪装为成功。

---

## 7. 后续预留接口

Skill 后续能力：

- Skill 版本历史。
- Skill 合并。
- Skill 相似度去重。
- 跨 Agent 共享技能库。
- 用户批准后把某个 Agent skill 晋升为团队公共 skill。
- 外部向量检索或 RAG 接入。

实验执行后续能力：

- Docker 沙箱。
- SSH 远程服务器执行。
- 队列式执行。
- GPU 资源配置。
- 实验数据集管理。
- 图表预览。
- Jupyter notebook 导出。

所有预留接口本阶段只定义边界，不实现复杂能力。

---

## 8. 给 opencode 的执行要求

- 每个阶段单独提交，中文 commit message。
- 不要 push 到远程。
- 不要重写无关页面和无关服务。
- 不要修改用户已有未提交文件，除非它们正是本任务目标。
- 所有文件写入必须在项目目录内。
- 后端新增 API 必须有基本错误处理。
- 前端所有危险操作必须二次确认。
- 所有新配置必须写入 `.env.example`，并通过设置页可编辑。
- 完成后输出调试步骤和功能测试脚本路径。

