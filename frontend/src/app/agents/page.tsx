"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { AGENT_STATUS_LABELS, SKILL_NAMES, type GraduateAgent, type Task } from "@/lib/types"

const STATUS_COLORS: Record<string, string> = {
  idle: "bg-green-100 text-green-700",
  working: "bg-blue-100 text-blue-700",
  waiting: "bg-yellow-100 text-yellow-700",
  reviewing: "bg-purple-100 text-purple-700",
  blocked: "bg-red-100 text-red-700",
  finished: "bg-gray-100 text-gray-700",
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
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold">Agent 状态</h2>
        <p className="text-sm text-gray-500">查看每个研究生 Agent 的职责、技能和当前负载。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {graduateAgents.map((agent) => (
          <Card key={agent.id} className="transition-shadow hover:shadow-md">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-3 text-base">
                <span>{agent.name}</span>
                <Badge className={STATUS_COLORS[agent.status] || ""}>
                  {AGENT_STATUS_LABELS[agent.status] || agent.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-xs leading-5 text-gray-600">
                {agent.description || AGENT_TYPE_DESCRIPTION[agent.type] || ""}
              </p>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium">当前负载</span>
                  <span className="text-xs">{Math.round(agent.current_load * 100)}%</span>
                </div>
                <div className="h-2 w-full rounded-full bg-gray-200">
                  <div
                    className="h-2 rounded-full bg-gray-900 transition-all"
                    style={{ width: `${agent.current_load * 100}%` }}
                  />
                </div>
              </div>

              <Separator />

              <div>
                <div className="mb-2 text-xs font-medium">技能矩阵</div>
                {SKILL_BARS.map((skill) => (
                  <div key={skill} className="mb-1 flex items-center gap-2">
                    <span className="w-16 text-xs text-gray-500">{SKILL_NAMES[skill]}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-gray-100">
                      <div
                        className="h-1.5 rounded-full bg-gray-700"
                        style={{ width: `${agent.skills[skill as keyof typeof agent.skills] * 10}%` }}
                      />
                    </div>
                    <span className="w-5 text-right text-xs font-medium">{agent.skills[skill as keyof typeof agent.skills]}</span>
                  </div>
                ))}
              </div>

              <Separator />

              <div className="space-y-1">
                <div className="text-xs font-medium text-gray-500">当前任务</div>
                {agent.current_tasks?.length > 0 ? (
                  <div className="space-y-1">
                    {agent.current_tasks.map((taskId) => {
                      const task = taskMap[taskId]
                      return (
                        <button
                          key={taskId}
                          onClick={() => router.push(`/tasks?run_id=${task?.run_id || ""}`)}
                          className="block w-full rounded-md bg-gray-50 px-2 py-1 text-left text-xs hover:bg-gray-100"
                        >
                          {task ? task.title : taskId}
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-gray-400">暂无任务</div>
                )}
              </div>

              <div className="flex items-center justify-between text-xs text-gray-400">
                <span>可创建 SubAgent：{agent.max_subagents} 个</span>
                <span>{agent.preferred_task_types?.length ? `偏好：${agent.preferred_task_types.join(", ")}` : ""}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
