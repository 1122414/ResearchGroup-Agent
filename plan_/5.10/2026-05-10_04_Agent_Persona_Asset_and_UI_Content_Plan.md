# Agent 角色设定、像素资产与中文文案计划

**日期**: 2026-05-10  
**范围**: `backend/app/data/seed_agents.json`, `frontend/src/lib/types.ts`, `frontend/public`, `frontend/src/components/office`  
**优先级**: P1-P2

## 1. 目标

让导师、五类研究生 Agent、SubAgent 在前端有稳定、可理解、可扩展的身份表达：

1. 每个 Agent 有中文名称、角色定位、技能特色。
2. 每个 Agent 有独立像素小人风格。
3. 每个 Agent 有对应办公室区域。
4. 每种状态有短气泡文案。
5. 所有中文标签集中管理，避免再次出现乱码。

## 2. 角色设定

### 2.1 导师 Agent

定位：

1. 拆解研究目标。
2. 决定任务结构。
3. 审核研究生产出。
4. 生成最终阶段报告。

视觉特色：

1. 站在白板或导师办公室。
2. 手持笔、文件夹或红笔。
3. 审核时显示批注/印章动效。

状态气泡示例：

1. “我正在把研究目标拆成可执行任务。”
2. “我在检查每个任务的产出是否合格。”
3. “正在整理阶段性报告。”

### 2.2 文献研究生 Agent

职责：

1. 文献梳理。
2. 相关工作比较。
3. 提炼研究脉络。

视觉特色：

1. 书架、资料堆、检索终端。
2. 小人拿书或翻页。

气泡示例：

1. “我在整理相关工作和研究脉络。”
2. “正在提取关键论文观点。”

### 2.3 工程研究生 Agent

职责：

1. 系统设计。
2. 代码实现。
3. 技术方案评估。

视觉特色：

1. 电脑、终端、架构图。
2. 小人敲键盘。

气泡示例：

1. “我在检查实现路径和模块边界。”
2. “正在把方案落到代码结构里。”

### 2.4 实验研究生 Agent

职责：

1. 实验设计。
2. 评测流程。
3. 指标定义。

视觉特色：

1. 实验台、仪器、计时器。
2. 小人观察实验数据。

气泡示例：

1. “我在设计可复现的实验流程。”
2. “正在确认评测指标。”

### 2.5 数据分析研究生 Agent

职责：

1. 结果分析。
2. 数据表和图表解释。
3. 异常分析。

视觉特色：

1. 图表屏幕、数据板。
2. 小人看折线图或柱状图。

气泡示例：

1. “我在分析运行结果和指标变化。”
2. “正在寻找异常和趋势。”

### 2.6 写作研究生 Agent

职责：

1. 报告写作。
2. 结构整理。
3. 语言润色。

视觉特色：

1. 稿纸、咖啡杯、文档窗口。
2. 小人写字或整理纸张。

气泡示例：

1. “我在把产出整理成报告。”
2. “正在统一术语和段落结构。”

### 2.7 SubAgent

职责：

1. 临时处理可拆分的小任务。
2. 只返回结果给父 Agent。
3. 不直接进入最终报告。

视觉特色：

1. 临时工位。
2. 小人半透明或带临时标识。
3. 完成后淡出。

气泡示例：

1. “我在处理一个临时子任务。”
2. “结果会交回给父 Agent 检查。”

## 3. 像素资产规格

第一版建议使用原创简化 CSS sprite 或自绘 PNG，不依赖外部版权资产。

每个角色至少准备：

1. `idle`: 2 帧。
2. `working`: 4 帧。
3. `waiting`: 2 帧。
4. `blocked`: 2 帧。
5. `done`: 2 帧。

尺寸建议：

1. 单帧 32x32 或 48x48。
2. 统一 2x 或 3x 像素放大，不使用模糊缩放。
3. 文件路径：

```text
frontend/public/pixel/agents/advisor.png
frontend/public/pixel/agents/researcher.png
frontend/public/pixel/agents/engineer.png
frontend/public/pixel/agents/experimenter.png
frontend/public/pixel/agents/analyst.png
frontend/public/pixel/agents/writer.png
frontend/public/pixel/agents/subagent.png
frontend/public/pixel/office/tiles.png
```

如果暂时没有图片，第一版可以用 CSS 像素块占位，但必须保留上述路径和配置接口。

## 4. 前端配置文件

建议新增：

```text
frontend/src/lib/agent-personas.ts
```

包含：

```ts
export const AGENT_PERSONAS = {
  advisor: {
    label: "导师",
    zone: "advisor_office",
    sprite: "/pixel/agents/advisor.png",
    accent: "#6b4f9f",
  },
}
```

建议新增：

```text
frontend/src/lib/status-labels.ts
```

集中放置：

1. Run 状态中文。
2. Task 状态中文。
3. Agent 状态中文。
4. Activity 状态中文。
5. Skill 中文。
6. Output 类型中文。

## 5. 后端 seed 数据调整

检查 `backend/app/data/seed_agents.json`：

1. 名称要稳定。
2. 类型和前端 persona 对齐。
3. description 改成正常中文。
4. preferred_task_types 保持英文枚举，前端负责翻译。

禁止在 prompt 或代码中硬编码新的角色长文案；角色简介可放 seed 数据，UI 标签放前端配置。

## 6. 文案原则

1. 用户可读，不写内部乱码或过度技术术语。
2. 每个状态一句话解释“为什么现在是这个状态”。
3. 气泡文案短，12-24 个中文字符优先。
4. 详情页文案可以稍长，但要解释因果。
5. 中文标签和英文枚举同时保留，调试时可显示枚举。

## 7. 禁止事项

1. 禁止使用 Star-Office-UI 的非商用美术资产作为本项目默认资产。
2. 禁止把所有角色做成同一个造型只换颜色；每个 Agent 要有职责特色。
3. 禁止在多个组件里散落状态翻译。
4. 禁止让 SubAgent 看起来和正式研究生同级；它必须是临时角色。
5. 禁止为了气泡文案频繁调用 LLM；气泡应来自状态模板和最新事件。

## 8. 验收标准

1. 所有 Agent 页面、任务页、运行页中文标签可读。
2. 每个正式 Agent 有独立 persona 配置。
3. 像素办公室即使没有最终美术，也能用占位 sprite 跑通。
4. 所有状态标签由一个集中配置导出。
5. 新增角色/状态时，不需要改多个页面。

