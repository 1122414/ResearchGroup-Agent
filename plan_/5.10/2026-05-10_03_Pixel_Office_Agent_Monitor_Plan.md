# 像素风课题组办公室监控计划

**日期**: 2026-05-10  
**范围**: `frontend/src/app/office`, `frontend/src/components/office`, `backend/app/api/routes_monitor.py`  
**优先级**: P2  
**参考**: Star-Office-UI 的核心启发是“用像素办公室把不可见的 Agent 工作状态变成可视化状态看板”，包括状态映射、角色动画、气泡、多 Agent 状态展示。参考链接: https://github.com/ringhyacinth/Star-Office-UI

## 1. 目标

为 ResearchGroup-Agent 做一个像素风“课题组办公室”，让用户能实时看到导师、研究生 Agent、SubAgent 在做什么。

它不是替代任务看板，而是任务看板的可视化入口：

1. 任务事实以 `/runs/[id]` 和 `/tasks` 为准。
2. 像素办公室负责直观展示“谁在哪里、在做什么、是否卡住、是否需要关注”。
3. 点击角色、办公室、任务板可以进入结构化详情。

## 2. 页面入口

新增页面：

```text
/office
/office?run_id=run_xxxxxxxx
```

导航中增加“像素办公室”入口。

页面结构：

1. 顶部工具条
   - Run 选择器。
   - 当前 Run 状态。
   - 累计成本。
   - 停止运行按钮。
   - 跳转运行详情。
2. 主办公室画布
   - 导师办公室。
   - 五个研究生独立办公室。
   - 公共任务看板。
   - SubAgent 临时工位。
   - 休息区/空闲区。
   - 问题区/阻塞区。
3. 右侧详情面板
   - 当前选中的 Agent 或任务。
   - 最新事件。
   - 当前产出摘要。

## 3. 后端聚合接口

新增：

```http
GET /api/monitor/office-state?run_id={run_id}
```

返回结构建议：

```json
{
  "run": {
    "id": "run_xxx",
    "status": "executing",
    "current_step": "正在执行任务",
    "total_cost_usd": 0.012,
    "total_tokens": 12000,
    "started_at": "...",
    "updated_at": "..."
  },
  "agents": [
    {
      "id": "agent_researcher",
      "name": "文献研究生",
      "role": "researcher",
      "status": "working",
      "activity_state": "researching",
      "current_task_id": "task_xxx",
      "current_task_title": "梳理相关工作",
      "office_zone": "research_office",
      "speech": "正在整理文献脉络",
      "last_event_at": "..."
    }
  ],
  "tasks": [
    {
      "id": "task_xxx",
      "title": "梳理相关工作",
      "status": "running",
      "owner_agent": "agent_researcher",
      "priority": 9,
      "latest_event": "已开始执行"
    }
  ],
  "subagents": [
    {
      "id": "subagent_xxx",
      "parent_agent": "agent_researcher",
      "task_id": "task_xxx",
      "status": "running",
      "speech": "正在查找辅助材料"
    }
  ],
  "events": []
}
```

不要让前端自己拼 5 个接口做办公室状态；后端提供聚合状态，前端轮询即可。

## 4. 状态到动画的映射

定义 `activity_state`，不要直接使用底层状态枚举。

| activity_state | 触发来源 | 办公室表现 |
|---|---|---|
| `idle` | Agent 空闲 | 在休息区或自己办公室待命 |
| `decomposing` | 导师拆解任务 | 导师办公室亮灯，导师看白板 |
| `scheduling` | 调度分配 | 公共任务板闪烁，任务卡移动 |
| `researching` | 文献/调研任务 | 文献研究生翻书/查资料 |
| `coding` | 工程任务 | 工程研究生敲代码 |
| `experimenting` | 实验设计/执行 | 实验研究生操作仪器 |
| `analyzing` | 数据分析 | 数据分析研究生看图表 |
| `writing` | 报告写作 | 写作研究生写文档 |
| `reviewing` | 导师审核 | 导师办公室审核章/红笔 |
| `waiting` | 等待协作或 SubAgent | 原地等待，气泡说明原因 |
| `blocked` | 失败或需人工关注 | 问题区高亮 |
| `done` | 任务完成 | 回到办公室或休息区 |

## 5. 办公室区域设计

第一版用纯前端 CSS/像素图块实现，不依赖 Canvas 游戏引擎。

建议区域：

1. 中央公共任务看板
   - 展示 3-5 张当前最重要任务卡。
   - 卡片颜色对应状态。
2. 左上导师办公室
   - 导师 Agent。
   - 当前 Run 阶段。
   - 审核/拆解/报告生成动作。
3. 研究生办公室
   - 文献研究生：书架、资料堆。
   - 工程研究生：电脑、终端。
   - 实验研究生：实验台、仪器。
   - 数据分析研究生：图表屏幕。
   - 写作研究生：稿纸、白板。
4. SubAgent 临时工位
   - 临时小人出现，任务完成后消失或灰掉。
5. 问题区
   - 失败、阻塞、需修改任务进入该区。

## 6. 技术实现建议

第一版：

1. React 组件 + CSS sprite。
2. 角色用 `div` + `background-position` 切帧。
3. 每 800-1200ms 切换帧。
4. 每 2 秒轮询 `office-state`。
5. 角色位置由 `office_zone` 映射到 CSS grid 坐标。

后续可选：

1. Phaser。
2. Canvas。
3. 可上传资产。
4. 桌面宠物版。

当前禁止引入 Phaser，除非 P0/P1 已完成且现有页面稳定。

## 7. 与现有前端的关系

像素办公室必须能跳回结构化页面：

1. 点击任务卡 -> `/tasks?run_id=...&task_id=...`
2. 点击 Agent -> `/agents?agent_id=...`
3. 点击 Run 状态 -> `/runs/{run_id}`
4. 点击成本 -> `/runs/{run_id}#usage`

## 8. 禁止事项

1. 禁止复制 Star-Office-UI 的非商用美术资产到本项目。
2. 禁止为了动画牺牲可读性；办公室只是监控入口，不是唯一信息源。
3. 禁止把任务状态只存在前端动画里；所有状态必须来自后端接口。
4. 禁止先做资产上传、AI 生图装修、桌面宠物。
5. 禁止让 SubAgent 拥有永久记忆或独立办公室；SubAgent 只能是临时工位。

## 9. 验收标准

1. `/office?run_id=...` 能展示导师、五名研究生、公共任务看板。
2. Agent 状态变化后，角色区域/气泡在 2 秒内更新。
3. 至少支持 `idle/working/waiting/reviewing/blocked/done` 六类视觉状态。
4. 点击角色能看到当前任务、最新事件、成本摘要。
5. 停止 Run 后办公室停止动画推进，并显示已取消。

