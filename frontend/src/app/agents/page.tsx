"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { AGENT_STATUS_LABELS, SKILL_NAMES, type GraduateAgent } from "@/lib/types"

const STATUS_COLORS: Record<string, string> = {
  idle: "bg-green-100 text-green-700",
  working: "bg-blue-100 text-blue-700",
  waiting: "bg-yellow-100 text-yellow-700",
  reviewing: "bg-purple-100 text-purple-700",
  blocked: "bg-red-100 text-red-700",
  finished: "bg-gray-100 text-gray-700",
}

const SKILL_BARS = ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]

export default function AgentsPage() {
  const [agents, setAgents] = useState<GraduateAgent[]>([])

  useEffect(() => {
    api.getAgents().then(({ agents }) => setAgents(agents))
  }, [])

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
          <Card key={agent.id}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-3 text-base">
                <span>{agent.name}</span>
                <Badge className={STATUS_COLORS[agent.status] || ""}>
                  {AGENT_STATUS_LABELS[agent.status] || agent.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-xs leading-5 text-gray-600">{agent.description}</p>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium">当前负载</span>
                  <span className="text-xs">{Math.round(agent.current_load * 100)}%</span>
                </div>
                <div className="h-2 w-full rounded-full bg-gray-200">
                  <div className="h-2 rounded-full bg-gray-900" style={{ width: `${agent.current_load * 100}%` }} />
                </div>
              </div>

              <Separator />

              <div>
                <div className="mb-2 text-xs font-medium">技能矩阵</div>
                {SKILL_BARS.map((skill) => (
                  <div key={skill} className="mb-1 flex items-center gap-2">
                    <span className="w-16 text-xs text-gray-500">{SKILL_NAMES[skill]}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-gray-100">
                      <div className="h-1.5 rounded-full bg-gray-700" style={{ width: `${agent.skills[skill as keyof typeof agent.skills] * 10}%` }} />
                    </div>
                    <span className="w-5 text-right text-xs font-medium">{agent.skills[skill as keyof typeof agent.skills]}</span>
                  </div>
                ))}
              </div>

              <div className="text-xs text-gray-400">
                当前任务：{agent.current_tasks?.length ? agent.current_tasks.join("、") : "暂无"}
              </div>
              <div className="text-xs text-gray-400">
                可创建 SubAgent：{agent.max_subagents} 个
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
