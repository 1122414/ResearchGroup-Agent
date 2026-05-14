"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { AGENT_STATUS_LABELS, SKILL_NAMES, type GraduateAgent, type Task } from "@/lib/types"

const STATUS_COLORS: Record<string, string> = {
  idle: "bg-[#f0fbf2] text-[#2f7341]",
  working: "bg-[#eef0ff] text-[#3b4395]",
  waiting: "bg-[#fff6e8] text-[#8b5a14]",
  reviewing: "bg-[#fff3ef] text-[#964b36]",
  blocked: "bg-[#fff1f1] text-[#9d2d2d]",
  finished: "bg-[var(--rg-surface-soft)] text-[var(--rg-muted)]",
}

const SKILL_BARS = ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]

const AGENT_TYPE_DESCRIPTION: Record<string, string> = {
  researcher: "文献研究 Agent，擅长文献梳理、相关工作比较和研究脉络提炼。",
  engineer: "工程实现 Agent，擅长系统设计、代码实现和技术方案评估。",
  experimenter: "实验设计 Agent，擅长实验设计、评测流程和指标定义。",
  analyst: "数据分析 Agent，擅长结果分析、数据解释和异常检测。",
  writer: "学术写作 Agent，擅长报告写作、结构整理和语言润色。",
}

export default function AgentsPage() {
  const router = useRouter()
  const [agents, setAgents] = useState<GraduateAgent[]>([])
  const [tasks, setTasks] = useState<Task[]>([])

  useEffect(() => {
    api.getAgents().then(({ agents }) => setAgents(agents))
    api.getTasks().then(({ tasks }) => setTasks(tasks))
  }, [])

  const taskMap = Object.fromEntries(tasks.map((task) => [task.id, task]))
  const graduateAgents = agents.filter((agent) =>
    ["researcher", "engineer", "experimenter", "analyst", "writer"].includes(agent.type),
  )

  return (
    <div className="page-stack">
      <div className="page-hero">
        <div className="eyebrow">Graduate agent roster</div>
        <h2 className="page-title">Agent 状态</h2>
        <p className="page-copy">查看每个研究生 Agent 的职责、技能矩阵、当前负载和任务占用情况。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {graduateAgents.map((agent) => (
          <Card key={agent.id} className="surface-card transition-shadow hover:shadow-md">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-3 text-base">
                <span>{agent.name}</span>
                <Badge className={STATUS_COLORS[agent.status] || ""}>
                  {AGENT_STATUS_LABELS[agent.status] || agent.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-xs leading-5 text-[var(--rg-body)]">
                {agent.description || AGENT_TYPE_DESCRIPTION[agent.type] || ""}
              </p>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium text-[var(--rg-muted)]">当前负载</span>
                  <span className="text-xs">{Math.round(agent.current_load * 100)}%</span>
                </div>
                <div className="h-2 w-full rounded-full bg-[var(--rg-surface-card)]">
                  <div
                    className="h-2 rounded-full bg-[var(--rg-linear)] transition-all"
                    style={{ width: `${agent.current_load * 100}%` }}
                  />
                </div>
              </div>

              <Separator />

              <div>
                <div className="mb-2 text-xs font-medium text-[var(--rg-muted)]">技能矩阵</div>
                {SKILL_BARS.map((skill) => (
                  <div key={skill} className="mb-1 flex items-center gap-2">
                    <span className="w-16 text-xs text-[var(--rg-muted)]">{SKILL_NAMES[skill]}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-[var(--rg-surface-soft)]">
                      <div
                        className="h-1.5 rounded-full bg-[var(--rg-dark-3)]"
                        style={{ width: `${agent.skills[skill as keyof typeof agent.skills] * 10}%` }}
                      />
                    </div>
                    <span className="w-5 text-right text-xs font-medium">{agent.skills[skill as keyof typeof agent.skills]}</span>
                  </div>
                ))}
              </div>

              <Separator />

              <div className="space-y-1">
                <div className="text-xs font-medium text-[var(--rg-muted)]">当前任务</div>
                {agent.current_tasks?.length > 0 ? (
                  <div className="space-y-1">
                    {agent.current_tasks.map((taskId) => {
                      const task = taskMap[taskId]
                      return (
                        <button
                          key={taskId}
                          onClick={() => router.push(`/tasks?run_id=${task?.run_id || ""}`)}
                          className="block w-full rounded-md bg-[var(--rg-surface-soft)] px-2 py-1 text-left text-xs hover:bg-[var(--rg-surface-card)]"
                        >
                          {task ? task.title : taskId}
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-[var(--rg-muted)]">暂无任务</div>
                )}
              </div>

              <div className="grid gap-1 text-xs text-[var(--rg-muted)] sm:grid-cols-[auto_minmax(0,1fr)] sm:items-start">
                <span className="shrink-0">可创建 SubAgent：{agent.max_subagents} 个</span>
                <span className="min-w-0 [overflow-wrap:anywhere] sm:text-right">
                  {agent.preferred_task_types?.length ? `偏好：${agent.preferred_task_types.join(", ")}` : ""}
                </span>
              </div>
              <Link href={`/skills?agent_id=${agent.id}`} className="block rounded-lg border border-[var(--rg-hairline)] px-3 py-2 text-center text-xs font-medium text-[var(--rg-body)] hover:bg-[var(--rg-surface-soft)]">
                管理专属 Skills
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
