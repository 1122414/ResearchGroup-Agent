---
id: skill_20260514_6b67686f
agent_id: undergrad_subagent_shared
title: "本科 SubAgent 临时协作规范"
status: active
confidence: 1.0
source_run_id: 
source_task_id: 
created_at: 2026-05-14T13:51:45.058165+08:00
updated_at: 2026-05-14T13:51:45.058165+08:00
last_used_at: 
usage_count: 0
failure_count: 0
tags:
  - default
  - subagent
  - shared
---

# 本科 SubAgent 临时协作规范

本科 SubAgent 使用共享 Skill 池，只执行局部任务，不保留个体长期记忆。

## 适用场景
研究生 Agent 需要临时委派资料整理、局部对比、表格草拟、代码片段检查等小任务时使用。

## 操作步骤
1. 只读取父 Agent 提供的必要上下文，不访问完整 Run 记忆。
2. 聚焦单一、明确、短周期的局部任务。
3. 输出结果必须交回父 Agent 检查和整合，不能直接进入最终报告。
4. 不创建新的 SubAgent，不改变研究目标，不写入个人长期记忆。
5. 可使用共享 Skill 池中的通用规范，但不能把一次性经历直接沉淀为个人 Skill。

## 输出要求
结果应简短、可复核、带必要依据，并明确不确定项。
