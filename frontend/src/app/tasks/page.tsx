"use client"

import { useState, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { TASK_STATUS_LABELS, AGENT_STATUS_LABELS } from "@/lib/types"

const STATUS_COLUMNS = [
  "pending", "assigned", "running", "waiting_collab",
  "waiting_subagent", "waiting_review", "need_revision", "completed",
]

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  assigned: "bg-blue-100 text-blue-700",
  running: "bg-indigo-100 text-indigo-700",
  waiting_collab: "bg-purple-100 text-purple-700",
  waiting_subagent: "bg-pink-100 text-pink-700",
  waiting_review: "bg-orange-100 text-orange-700",
  need_revision: "bg-red-100 text-red-700",
  completed: "bg-green-100 text-green-700",
  archived: "bg-gray-200 text-gray-500",
  failed: "bg-red-200 text-red-800",
}

export default function TasksPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-gray-500">加载中...</div>}>
      <TasksContent />
    </Suspense>
  )
}

function TasksContent() {
  const searchParams = useSearchParams()
  const runId = searchParams.get("run_id")
  const [tasks, setTasks] = useState<any[]>([])
  const [agents, setAgents] = useState<any[]>([])
  const [selectedTask, setSelectedTask] = useState<any>(null)

  useEffect(() => {
    api.getTasks(runId || undefined).then(({ tasks }) => setTasks(tasks))
    api.getAgents().then(({ agents }) => setAgents(agents))
  }, [runId])

  const agentMap: Record<string, string> = {}
  agents.forEach((a) => { agentMap[a.id] = a.name })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">任务板</h2>
        {runId && <span className="text-sm text-gray-500">运行: {runId}</span>}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        {STATUS_COLUMNS.map((status) => {
          const columnTasks = tasks.filter((t) => t.status === status)
          return (
            <div key={status} className="bg-gray-50 rounded-lg p-3 min-h-[200px]">
              <div className="text-xs font-semibold text-gray-500 mb-2 uppercase flex items-center justify-between">
                {TASK_STATUS_LABELS[status] || status}
                <Badge variant="secondary" className="text-xs">{columnTasks.length}</Badge>
              </div>
              <div className="space-y-2">
                {columnTasks.map((task) => (
                  <button
                    key={task.id}
                    onClick={() => setSelectedTask(task)}
                    className={`w-full text-left p-2 rounded-md border text-xs transition-colors hover:shadow ${STATUS_COLORS[task.status] || "bg-white"}`}
                  >
                    <div className="font-medium truncate">{task.title}</div>
                    <div className="text-gray-500 mt-1">
                      {task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"}
                    </div>
                    <div className="flex gap-1 mt-1">
                      <Badge variant="outline" className="text-[10px] px-1 py-0">
                        P{task.priority}
                      </Badge>
                      {task.collaborator_agents?.length > 0 && (
                        <Badge variant="outline" className="text-[10px] px-1 py-0">
                          +{task.collaborator_agents.length}协作
                        </Badge>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {selectedTask && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {selectedTask.title}
              <Badge className={STATUS_COLORS[selectedTask.status]}>
                {TASK_STATUS_LABELS[selectedTask.status]}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <span className="font-medium">描述：</span>
              {selectedTask.description}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div><span className="font-medium">类型：</span>{selectedTask.task_type}</div>
              <div><span className="font-medium">优先级：</span>{selectedTask.priority}/10</div>
              <div><span className="font-medium">复杂度：</span>{selectedTask.complexity}/10</div>
              <div><span className="font-medium">可拆分性：</span>{selectedTask.decomposability}/10</div>
            </div>
            <Separator />
            <div>
              <span className="font-medium">主责Agent：</span>
              {selectedTask.owner_agent ? agentMap[selectedTask.owner_agent] || selectedTask.owner_agent : "未分配"}
            </div>
            {selectedTask.collaborator_agents?.length > 0 && (
              <div>
                <span className="font-medium">协作Agent：</span>
                {selectedTask.collaborator_agents.map((id: string) => agentMap[id] || id).join("、")}
              </div>
            )}
            {selectedTask.review_result && (
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="font-medium">
                  审核结果：{selectedTask.review_result.approved ? "✅ 通过" : "❌ 需返工"}
                </div>
                <div className="text-gray-600 mt-1">{selectedTask.review_result.feedback}</div>
              </div>
            )}
            {selectedTask.outputs?.length > 0 && (
              <div>
                <div className="font-medium mb-1">产出 ({selectedTask.outputs.length}项)：</div>
                {selectedTask.outputs.map((o: any, i: number) => (
                  <pre key={i} className="text-xs bg-gray-50 p-2 rounded mt-1 overflow-auto max-h-40">
                    {JSON.stringify(o, null, 2)}
                  </pre>
                ))}
              </div>
            )}
            <div className="text-xs text-gray-400">
              创建：{selectedTask.created_at} | 更新：{selectedTask.updated_at}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
