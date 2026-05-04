"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { AGENT_STATUS_LABELS, SKILL_NAMES } from "@/lib/types"

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
  const [agents, setAgents] = useState<any[]>([])

  useEffect(() => {
    api.getAgents().then(({ agents }) => setAgents(agents))
  }, [])

  const graduateAgents = agents.filter((a) =>
    ["researcher", "engineer", "experimenter", "analyst", "writer"].includes(a.type)
  )

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">Agent 状态面板</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {graduateAgents.map((agent) => (
          <Card key={agent.id}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center justify-between">
                <span>{agent.name}</span>
                <Badge className={STATUS_COLORS[agent.status] || ""}>
                  {AGENT_STATUS_LABELS[agent.status] || agent.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-gray-600 text-xs">{agent.description}</p>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium">当前负载</span>
                  <span className="text-xs">{Math.round(agent.current_load * 100)}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all"
                    style={{ width: `${agent.current_load * 100}%` }}
                  />
                </div>
              </div>

              <Separator />

              <div>
                <div className="text-xs font-medium mb-1">能力矩阵</div>
                {SKILL_BARS.map((skill) => (
                  <div key={skill} className="flex items-center gap-2 mb-1">
                    <span className="text-xs w-16 text-gray-500">{SKILL_NAMES[skill]}</span>
                    <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                      <div
                        className="bg-indigo-500 h-1.5 rounded-full"
                        style={{ width: `${agent.skills[skill] * 10}%` }}
                      />
                    </div>
                    <span className="text-xs w-4 text-right font-medium">{agent.skills[skill]}</span>
                  </div>
                ))}
              </div>

              <div className="text-xs text-gray-400">
                偏好任务：{(agent.preferred_task_types || []).join("、") || "无"}
              </div>
              <div className="text-xs text-gray-400">
                SubAgent上限：{agent.max_subagents} | 工具：{(agent.tools || []).join("、") || "无"}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
