# ResearchGroup-Agent MVP 可落地开发计划

> 文档日期：2026-05-04  
> 文档用途：交给 OpenCode / 编码 Agent 执行开发  
> 项目定位：面向研究生课题组场景的多 Agent 协作与产出管理系统 MVP

---

## 0. 项目一句话定义

ResearchGroup-Agent 是一个模拟真实研究生课题组运转的多 Agent 协作系统：用户输入一个研究目标后，导师 Agent 负责拆解任务、分配任务、审核结果；五类研究生 Agent 按能力画像承担主责或协作任务；系统通过任务板追踪进度、Agent 状态、协作关系和阶段性产出，最终生成阶段性报告。

---

## 1. MVP 核心目标

本 MVP 只追求跑通一个完整闭环：

```text
用户输入研究目标
→ 导师 Agent 拆解任务
→ 系统根据能力分数和当前负载分配任务
→ 五类研究生 Agent 执行任务
→ 空闲 Agent 支援主责 Agent
→ 研究生 Agent 可按规则创建临时本科生 SubAgent
→ SubAgent 返回结构化结果后销毁
→ 主责研究生整合结果
→ 导师 Agent 审核
→ 系统生成阶段性产出
→ 前端任务板展示全过程状态
```

MVP 的重点不是“真正自动科研突破”，而是验证：

1. 多 Agent 组织结构是否成立；
2. 导师 Agent 能否拆任务、派任务、审核任务；
3. 研究生 Agent 能否基于能力画像分工协作；
4. SubAgent 是否能完成临时子任务并避免主 Agent 上下文污染；
5. 任务板是否能清楚展示虚拟课题组在做什么；
6. 系统是否能生成一个阶段性产出物。

---

## 2. MVP 必须实现的范围

### 2.1 必须实现的角色

MVP 只实现以下角色：

```text
导师 Agent
调研型研究生 Agent
工程型研究生 Agent
实验型研究生 Agent
数据分析型研究生 Agent
写作型研究生 Agent
本科生 SubAgent，临时创建，用完销毁
```

### 2.2 必须实现的系统能力

1. 用户输入研究目标；
2. 导师 Agent 将研究目标拆解为结构化任务；
3. 每个研究生 Agent 有固定能力画像；
4. 每个任务有能力需求画像；
5. 系统根据能力画像、任务需求和当前负载选择主责 Agent；
6. 系统可选择协作 Agent；
7. 研究生 Agent 可创建 SubAgent 处理短期子任务；
8. SubAgent 只拿到最小必要上下文，返回结构化结果后销毁；
9. 主责研究生 Agent 整合自身结果、协作结果和 SubAgent 结果；
10. 导师 Agent 审核任务结果，决定完成或返工；
11. 系统维护任务状态；
12. 前端展示任务板、Agent 状态、任务详情和最终产出；
13. 最终生成一份阶段性报告。

---

## 3. 当前阶段严禁做的事情

以下内容不属于 MVP，现阶段严禁开发，避免项目失控。

### 3.1 严禁做复杂科研自动化

现阶段不要做：

```text
真实论文自动发表
真实端到端科研创新发现
自动生成可投稿论文
自动审稿系统
完整实验平台
自动训练深度学习模型
真实集群调度
复杂 AutoML
复杂 benchmark 管理
```

### 3.2 严禁做复杂权限系统

现阶段不要做：

```text
多用户登录
组织权限
导师/学生真实账号体系
OAuth 登录
学校统一认证
团队成员邀请系统
```

MVP 只做单用户本地系统。

### 3.3 严禁做复杂前端大屏

现阶段不要做：

```text
炫酷 3D 可视化
复杂动态图谱编辑器
实时 WebSocket 大屏
拖拽式流程编排器
复杂 BI 报表
```

MVP 前端只需要清晰、可用、可展示。

### 3.4 严禁一开始接入太多外部工具

现阶段不要强依赖：

```text
Zotero
Overleaf
GitHub 写权限
真实数据库仓库
真实论文数据库 API
真实实验服务器
飞书/钉钉/Notion
```

但必须预留接口。

### 3.5 严禁让所有 Agent 自由聊天

所有 Agent 协作必须围绕任务板和状态机进行。

禁止实现成：

```text
多个 Agent 无约束互相对话
没有任务状态
没有主责人
没有结构化输出
没有导师审核
```

每个 Agent 行为都必须落到任务、状态和产出上。

---

## 4. MVP 推荐技术架构

本地优先，简单可控。

### 4.1 推荐技术栈

前端：

```text
React / Next.js
TypeScript
Tailwind CSS
shadcn/ui，可选
```

后端：

```text
Python FastAPI
Pydantic 数据模型
SQLite 本地数据库
```

Agent 编排：

```text
第一版优先自研轻量调度器
后续预留 LangGraph / AutoGen / CrewAI 接入接口
```

LLM 接入：

```text
统一 LLMProvider 抽象层
支持 OpenAI-compatible API
支持本地 mock 模式
```

存储：

```text
SQLite：任务、Agent 状态、产出记录
本地文件夹：报告、日志、Artifact
```

### 4.2 推荐目录结构

```text
researchgroup-agent/
  README.md
  .env.example
  backend/
    main.py
    requirements.txt
    app/
      api/
        routes_agents.py
        routes_tasks.py
        routes_runs.py
        routes_outputs.py
      core/
        config.py
        llm_provider.py
        prompt_loader.py
      models/
        agent.py
        task.py
        subagent.py
        output.py
        run.py
      services/
        agent_registry.py
        task_scheduler.py
        task_decomposer.py
        task_executor.py
        review_service.py
        report_service.py
        subagent_service.py
      storage/
        db.py
        repositories.py
      prompts/
        advisor_agent.md
        grad_researcher.md
        grad_engineer.md
        grad_experimenter.md
        grad_analyst.md
        grad_writer.md
        subagent.md
      data/
        seed_agents.json
        seed_task_templates.json
  frontend/
    package.json
    src/
      app/
        page.tsx
        tasks/page.tsx
        agents/page.tsx
        outputs/page.tsx
      components/
        ResearchGoalInput.tsx
        TaskBoard.tsx
        TaskCard.tsx
        AgentStatusPanel.tsx
        TaskDetailDrawer.tsx
        OutputViewer.tsx
        CollaborationTimeline.tsx
      lib/
        api.ts
        types.ts
  artifacts/
    reports/
    logs/
    runs/
```

---

## 5. 核心数据模型

### 5.1 GraduateAgent

```json
{
  "id": "grad_researcher",
  "name": "调研型研究生 Agent",
  "type": "researcher",
  "description": "擅长文献检索、论文阅读、相关工作总结和研究现状分析。",
  "skills": {
    "literature_review": 10,
    "coding": 4,
    "experiment": 5,
    "data_analysis": 6,
    "academic_writing": 8,
    "mentoring": 8
  },
  "status": "idle",
  "current_load": 0.0,
  "max_load": 1.0,
  "current_tasks": [],
  "preferred_task_types": [
    "literature_survey",
    "paper_summary",
    "related_work"
  ],
  "tools": [
    "mock_web_search",
    "summary_tool"
  ],
  "can_create_subagents": true,
  "max_subagents": 2
}
```

### 5.2 Task

```json
{
  "id": "task_001",
  "title": "调研多 Agent 科研协作系统相关项目",
  "description": "查找并总结已有多 Agent 科研协作系统，形成对比分析。",
  "task_type": "literature_survey",
  "required_skills": {
    "literature_review": 9,
    "coding": 3,
    "experiment": 1,
    "data_analysis": 5,
    "academic_writing": 7,
    "mentoring": 6
  },
  "priority": 8,
  "complexity": 8,
  "decomposability": 9,
  "status": "pending",
  "owner_agent": null,
  "collaborator_agents": [],
  "subtasks": [],
  "outputs": [],
  "review_result": null,
  "created_at": "",
  "updated_at": ""
}
```

### 5.3 SubAgent

```json
{
  "id": "subagent_001",
  "parent_agent": "grad_researcher",
  "task_id": "task_001",
  "task": "搜索 10 个相关 GitHub 项目，并整理名称、链接、功能、技术栈。",
  "context": "只提供完成该子任务所需的最小上下文。",
  "expected_output_schema": {
    "project_name": "",
    "link": "",
    "main_features": "",
    "tech_stack": "",
    "relevance": ""
  },
  "status": "running",
  "lifecycle": "destroy_after_return",
  "result": null
}
```

### 5.4 TaskStatus 枚举

```text
pending             待分配
assigned            已分配
running             执行中
waiting_collab      等待协作 Agent
waiting_subagent    等待 SubAgent 返回
waiting_review      等待导师审核
need_revision       需要返工
completed           已完成
archived            已归档
failed              失败
```

### 5.5 AgentStatus 枚举

```text
idle        空闲
working     工作中
waiting     等待其他 Agent 或 SubAgent
reviewing   审核中
blocked     阻塞
finished    完成当前任务
```

---

## 6. 固定能力矩阵

MVP 阶段使用人工预设能力，不做动态学习。

| 研究生 Agent | 文献调研 | 编码 | 实验 | 数据分析 | 学术写作 | 指导管理 |
|---|---:|---:|---:|---:|---:|---:|
| 调研型研究生 | 10 | 4 | 5 | 6 | 8 | 8 |
| 工程型研究生 | 4 | 10 | 7 | 6 | 5 | 7 |
| 实验型研究生 | 5 | 7 | 10 | 8 | 5 | 8 |
| 数据分析型研究生 | 6 | 7 | 8 | 10 | 6 | 8 |
| 写作型研究生 | 7 | 4 | 5 | 6 | 10 | 7 |

分数解释：

```text
1-2：几乎不会，只能极简单辅助
3-4：基础能力，可以打下手
5-6：中等能力，可以独立完成普通任务
7-8：熟练能力，可以作为协作核心
9-10：专家能力，适合作为主责 Agent
```

---

## 7. 调度规则

### 7.1 主责 Agent 选择规则

每个任务有 required_skills。每个 Agent 有 skills。

MVP 使用简单匹配分：

```text
能力匹配分 = Σ(agent_skill_i * task_required_skill_i)
空闲程度 = 1 - current_load
最终分 = 能力匹配分 * 0.7 + 空闲程度 * 100 * 0.3
```

选择最终分最高的 Agent 作为 owner_agent。

### 7.2 协作 Agent 选择规则

满足以下条件时分配协作 Agent：

```text
1. 任务 complexity >= 7；或
2. 主责 Agent current_load >= 0.7；或
3. 任务需要跨领域能力，例如调研任务里有 coding >= 3；或
4. 导师 Agent 在拆解结果中明确建议协作。
```

协作 Agent 选择条件：

```text
1. 非主责 Agent；
2. current_load <= 0.6；
3. 对任务某个关键能力分 >= 5；
4. 最多选择 2 个协作 Agent。
```

### 7.3 SubAgent 创建规则

研究生 Agent 只有在满足以下条件时才能创建 SubAgent：

```text
1. task.complexity >= 6；
2. task.decomposability >= 7；
3. agent.skills.mentoring >= 6；
4. 子任务输入输出明确；
5. 子任务不需要长期上下文；
6. 子任务不直接决定最终结论。
```

最大 SubAgent 数：

```text
max_subagents = floor(mentoring / 3)
```

约束：

```text
1-3：最多 0 个
4-6：最多 1 个
7-8：最多 2 个
9-10：最多 3 个
```

### 7.4 SubAgent 结果处理规则

SubAgent 的结果不能直接进入最终报告，必须经过 parent graduate agent 整合。

流程：

```text
SubAgent 返回结构化结果
→ parent Agent 检查
→ parent Agent 删除低质量内容
→ parent Agent 整合为任务中间结果
→ owner Agent 输出最终任务结果
```

---

## 8. Agent Prompt 边界

### 8.1 导师 Agent Prompt 目标

导师 Agent 只做：

```text
任务拆解
任务分类
任务优先级判断
任务审核
返工建议
阶段性总结
```

导师 Agent 不直接执行所有任务。

### 8.2 研究生 Agent Prompt 目标

研究生 Agent 只做：

```text
执行自己负责的任务
请求协作
创建必要 SubAgent
整合子结果
输出结构化任务结果
```

研究生 Agent 不允许越过导师 Agent 直接决定整个项目方向。

### 8.3 SubAgent Prompt 目标

SubAgent 只做：

```text
完成单个明确子任务
只接收最小上下文
只返回结构化结果
不保留长期记忆
完成后销毁
```

SubAgent 不允许：

```text
改变主任务目标
和其他 Agent 自由聊天
自己创建新的 SubAgent
决定最终报告结论
访问完整项目上下文
```

---

## 9. MVP 页面设计

### 9.1 首页 / 运行页

功能：

```text
输入研究目标
点击“启动虚拟课题组”
显示当前运行状态
显示最新系统日志
显示阶段性产出入口
```

输入示例：

```text
请让课题组围绕“面向研究生课题组协作的多 Agent 系统”完成一次阶段性调研，输出相关项目调研、系统架构建议、实验验证方案和周报。
```

### 9.2 任务板页面

使用看板列展示任务状态：

```text
待分配
执行中
等待协作
等待 SubAgent
等待导师审核
需要返工
已完成
```

每张任务卡展示：

```text
任务标题
任务类型
主责 Agent
协作 Agent
当前状态
优先级
复杂度
是否有 SubAgent
```

点击任务卡打开详情。

### 9.3 任务详情抽屉

展示：

```text
任务描述
能力需求
分配原因
主责 Agent
协作 Agent
SubAgent 调用记录
中间结果
导师审核意见
最终输出
状态流转日志
```

### 9.4 Agent 状态页面

展示五个研究生 Agent 和导师 Agent：

```text
名称
角色
能力矩阵
当前状态
当前负载
当前任务
最近产出
可管理 SubAgent 数
```

### 9.5 产出页面

展示：

```text
阶段性报告
任务拆解表
Agent 分工表
调研摘要
实验计划
系统架构建议
周报
```

MVP 可以直接用 Markdown 渲染。

---

## 10. 后端 API 设计

### 10.1 Agent API

```text
GET /api/agents
获取所有 Agent 状态

GET /api/agents/{agent_id}
获取单个 Agent 详情
```

### 10.2 Task API

```text
GET /api/tasks
获取全部任务

GET /api/tasks/{task_id}
获取任务详情

POST /api/tasks/{task_id}/assign
手动触发任务分配，可选

POST /api/tasks/{task_id}/review
导师审核任务，可选
```

### 10.3 Run API

```text
POST /api/runs
创建一次课题组运行
body: { research_goal: string }

GET /api/runs/{run_id}
获取运行状态

POST /api/runs/{run_id}/step
执行下一步，用于 MVP 调试

POST /api/runs/{run_id}/run_all
执行完整流程，用于演示
```

建议 MVP 同时支持 step 模式和 run_all 模式。

step 模式方便调试和展示状态变化。

### 10.4 Output API

```text
GET /api/outputs
获取产出列表

GET /api/outputs/{output_id}
获取具体产出

POST /api/outputs/final_report
生成最终阶段性报告
```

---

## 11. 运行流程设计

### 11.1 run_all 流程

```text
1. 用户提交 research_goal
2. 创建 Run 记录
3. 导师 Agent 生成任务列表
4. 任务写入数据库，状态为 pending
5. Scheduler 为每个任务选择 owner_agent 和 collaborator_agents
6. 更新任务状态为 assigned
7. TaskExecutor 逐个执行任务
8. 研究生 Agent 判断是否创建 SubAgent
9. SubAgentService 执行临时子任务并返回结果
10. 研究生 Agent 整合输出
11. 任务状态变为 waiting_review
12. 导师 Agent 审核
13. 审核通过则 completed，不通过则 need_revision
14. ReportService 汇总所有 completed 任务
15. 生成 Markdown 阶段性报告
```

### 11.2 step 流程

step 模式每次只推进一个阶段：

```text
STEP 1：导师拆任务
STEP 2：任务分配
STEP 3：研究生执行
STEP 4：SubAgent 执行
STEP 5：研究生整合
STEP 6：导师审核
STEP 7：生成报告
```

前端应提供“执行下一步”按钮，方便演示。

---

## 12. 任务模板

MVP 中导师 Agent 拆解任务可以先结合 LLM 和模板。

至少支持以下 5 类任务：

### 12.1 文献调研任务

```json
{
  "task_type": "literature_survey",
  "required_skills": {
    "literature_review": 9,
    "coding": 2,
    "experiment": 1,
    "data_analysis": 4,
    "academic_writing": 7,
    "mentoring": 6
  }
}
```

### 12.2 工程架构任务

```json
{
  "task_type": "system_design",
  "required_skills": {
    "literature_review": 3,
    "coding": 9,
    "experiment": 4,
    "data_analysis": 4,
    "academic_writing": 5,
    "mentoring": 5
  }
}
```

### 12.3 实验设计任务

```json
{
  "task_type": "experiment_design",
  "required_skills": {
    "literature_review": 4,
    "coding": 5,
    "experiment": 9,
    "data_analysis": 7,
    "academic_writing": 5,
    "mentoring": 6
  }
}
```

### 12.4 数据分析任务

```json
{
  "task_type": "result_analysis",
  "required_skills": {
    "literature_review": 3,
    "coding": 5,
    "experiment": 6,
    "data_analysis": 10,
    "academic_writing": 6,
    "mentoring": 5
  }
}
```

### 12.5 写作汇总任务

```json
{
  "task_type": "report_writing",
  "required_skills": {
    "literature_review": 6,
    "coding": 2,
    "experiment": 3,
    "data_analysis": 5,
    "academic_writing": 10,
    "mentoring": 5
  }
}
```

---

## 13. Prompt 文件要求

所有 prompt 放到 `backend/app/prompts/`，不要写死在代码里。

### 13.1 advisor_agent.md

必须包含：

```text
你是导师 Agent。
你的职责是根据用户研究目标拆解任务、分配任务建议、审核研究生结果、生成阶段性总结。
你不能亲自完成所有任务。
你必须输出 JSON 格式任务列表。
每个任务必须包含 title、description、task_type、priority、complexity、decomposability、required_skills。
```

### 13.2 grad_researcher.md

调研型研究生：文献调研、资料归纳、相关工作、研究空白分析。

### 13.3 grad_engineer.md

工程型研究生：架构设计、代码实现、接口、工具接入、技术路线。

### 13.4 grad_experimenter.md

实验型研究生：实验目标、实验假设、评价指标、实验步骤、可复现性。

### 13.5 grad_analyst.md

数据分析型研究生：指标分析、结果解释、趋势、异常、可视化数据字段。

### 13.6 grad_writer.md

写作型研究生：周报、报告、论文草稿、结构组织和润色。

### 13.7 subagent.md

本科生 SubAgent：只完成单个明确子任务，返回结构化结果，不保留记忆，不扩展任务。

---

## 14. Mock 模式要求

MVP 必须支持 mock 模式，避免没有 LLM Key 时项目无法运行。

### 14.1 LLMProvider 抽象

实现：

```python
class LLMProvider:
    def generate(self, prompt: str, schema: dict | None = None) -> str:
        pass
```

至少两个实现：

```text
MockLLMProvider
OpenAICompatibleProvider
```

### 14.2 MockLLMProvider 行为

Mock 模式需要返回固定但合理的内容：

```text
导师拆出 5 个任务
研究生 Agent 输出模拟结果
SubAgent 返回模拟结构化结果
导师审核默认通过，少量任务可模拟返工
最终报告可生成固定模板
```

这样保证本地演示稳定。

---

## 15. Artifact / 产出要求

每次运行至少生成以下产出：

```text
artifacts/runs/{run_id}/tasks.json
artifacts/runs/{run_id}/agent_assignments.json
artifacts/runs/{run_id}/subagent_results.json
artifacts/runs/{run_id}/final_report.md
artifacts/runs/{run_id}/run_log.md
```

`final_report.md` 至少包含：

```text
# 阶段性研究报告

## 1. 研究目标
## 2. 任务拆解
## 3. Agent 分工
## 4. 调研结果
## 5. 系统架构建议
## 6. 实验验证方案
## 7. 数据分析与指标
## 8. 当前问题
## 9. 下一步计划
## 10. 导师总结
```

---

## 16. 开发优先级

### P0：必须完成，否则 MVP 不成立

1. 项目基础结构；
2. 后端 FastAPI 启动；
3. SQLite 初始化；
4. Agent 数据模型；
5. Task 数据模型；
6. 固定五类研究生 Agent seed 数据；
7. LLMProvider 抽象和 MockLLMProvider；
8. 导师 Agent 任务拆解，mock 可用；
9. TaskScheduler 能根据能力矩阵分配主责 Agent；
10. TaskExecutor 能执行任务并生成模拟结构化结果；
11. SubAgentService 能创建临时 SubAgent 并返回结果；
12. ReviewService 能做导师审核；
13. ReportService 能生成 final_report.md；
14. 前端首页可输入研究目标；
15. 前端任务板可展示任务状态；
16. 前端 Agent 状态面板可展示能力和负载；
17. 前端产出页面可查看 final_report.md。

### P1：强烈建议完成，提升演示效果

1. step 模式逐步执行；
2. 任务详情抽屉；
3. 状态流转日志；
4. 协作 Agent 展示；
5. SubAgent 调用记录展示；
6. 简单 Markdown 渲染；
7. 任务返工模拟；
8. 分配原因展示，例如为什么派给调研型 Agent；
9. run_log.md 自动记录所有阶段。

### P2：可以延后

1. 接入真实 OpenAI-compatible API；
2. 更精细 Prompt；
3. 更复杂的调度算法；
4. 能力分数动态调整；
5. 真实文献搜索工具；
6. GitHub 项目搜索；
7. 代码执行沙箱；
8. 实验结果图表；
9. 多次运行历史对比。

---

## 17. 验收标准

MVP 完成后，必须能够完成以下演示流程：

1. 启动前端和后端；
2. 打开首页；
3. 输入一个研究目标；
4. 点击启动；
5. 系统生成 5 个左右任务；
6. 任务板显示任务从 pending 到 assigned；
7. Agent 面板显示五类研究生的能力和负载；
8. 系统展示每个任务的主责 Agent 和协作 Agent；
9. 至少一个任务创建 SubAgent；
10. SubAgent 返回结构化结果；
11. 任务进入导师审核；
12. 任务完成或返工；
13. 系统生成 final_report.md；
14. 前端可以查看阶段性报告；
15. artifacts 目录中能看到本次运行文件。

---

## 18. MVP 示例演示输入

```text
请让课题组围绕“面向研究生课题组协作的多 Agent 系统”完成一次阶段性调研，输出相关项目调研、系统架构建议、实验验证方案、数据分析指标和周报总结。
```

期望任务拆解：

```text
1. 调研已有多 Agent 科研协作系统
2. 设计 ResearchGroup-Agent MVP 系统架构
3. 设计任务调度与 SubAgent 验证实验
4. 设计系统运行指标和数据分析方案
5. 汇总阶段性周报和项目总结
```

期望分配：

```text
任务 1：调研型研究生主责，工程型和写作型协作
任务 2：工程型研究生主责，数据分析型协作
任务 3：实验型研究生主责，工程型协作
任务 4：数据分析型研究生主责，实验型协作
任务 5：写作型研究生主责，调研型协作
```

至少出现一个 SubAgent：

```text
调研型研究生创建本科生 SubAgent：整理 5 个相关项目的名称、功能、技术栈和相关性。
```

---

## 19. 后续预留接口

虽然 MVP 不实现，但代码结构必须预留以下接口。

### 19.1 ToolProvider 接口

预留未来工具接入：

```python
class ToolProvider:
    def run(self, tool_name: str, input: dict) -> dict:
        pass
```

未来工具：

```text
paper_search
web_search
github_search
code_runner
file_reader
chart_generator
zotero_connector
overleaf_connector
```

### 19.2 AgentOrchestrator 接口

预留替换为 LangGraph / AutoGen：

```python
class AgentOrchestrator:
    def run_task(self, task_id: str) -> dict:
        pass

    def run_step(self, run_id: str) -> dict:
        pass
```

### 19.3 SkillUpdateService 接口

预留后续能力动态调整：

```python
class SkillUpdateService:
    def update_after_review(self, agent_id: str, task_id: str, review_score: float):
        pass
```

MVP 中只保留空实现，不启用。

### 19.4 ExternalMemory 接口

预留长期记忆：

```python
class ExternalMemory:
    def save_summary(self, agent_id: str, content: str):
        pass

    def retrieve(self, agent_id: str, query: str) -> list[str]:
        pass
```

MVP 中不做向量数据库。

---

## 20. 编码 Agent 执行要求

给 OpenCode / 编码 Agent 的硬性要求：

1. 不要扩大需求；
2. 不要主动加入复杂外部依赖；
3. 不要做登录系统；
4. 不要做真实科研搜索；
5. 不要把所有逻辑写死在前端；
6. 不要把 prompt 写死在 Python 代码里；
7. 不要让 Agent 无限制互相聊天；
8. 所有任务必须有结构化状态；
9. 所有 Agent 行为必须可追踪；
10. 所有运行必须生成 artifacts 文件；
11. 必须支持 mock 模式；
12. 优先完成 P0，再做 P1；
13. 遇到不明确需求时，按本文档边界执行，不要自行扩展。

---

## 21. 最小完成版本定义

如果时间紧，最小完成版本只需要做到：

```text
1. 一个首页输入研究目标
2. 后端 mock 导师拆出 5 个任务
3. 调度器按能力矩阵分配 5 个研究生 Agent
4. 每个任务生成一个模拟结果
5. 至少一个任务创建一个 SubAgent 并返回结果
6. 导师 Agent mock 审核通过
7. 前端展示任务板和 Agent 状态
8. 生成 final_report.md
```

这就是最小可演示闭环。

---

## 22. 项目成功标准

这个 MVP 成功的标准不是输出内容多么像真实论文，而是用户能明显看到：

```text
导师在布置任务
研究生有不同能力
任务被合理分配
空闲 Agent 可以协作
研究生可以创建 SubAgent
SubAgent 用完销毁
任务状态持续变化
最终产出被沉淀
整个虚拟课题组过程可见
```

只要这个闭环成立，后续就可以逐步接入真实工具、真实文献、真实代码执行和更复杂的科研产出。
