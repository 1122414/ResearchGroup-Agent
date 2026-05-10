"use client"

import { Suspense, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { TASK_STATUS_LABELS, TASK_TYPE_LABELS, type GraduateAgent, type Task } from "@/lib/types"

const STATUS_COLUMNS = [
  "pending",
  "assigned",
  "running",
  "waiting_collab",
  "waiting_subagent",
  "waiting_review",
  "need_revision",
  "completed",
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
}

export default function TasksPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-gray-500">正在加载任务板...</div>}>
      <TasksContent />
    </Suspense>
  )
}

function TasksContent() {
  const searchParams = useSearchParams()
  const runId = searchParams.get("run_id")
  const [tasks, setTasks] = useState<Task[]>([])
  const [agents, setAgents] = useState<GraduateAgent[]>([])
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)

  useEffect(() => {
    api.getTasks(runId || undefined).then(({ tasks }) => setTasks(tasks))
    api.getAgents().then(({ agents }) => setAgents(agents))
  }, [runId])

  const agentMap = Object.fromEntries(agents.map((agent) => [agent.id, agent.name]))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">任务板</h2>
          <p className="text-sm text-gray-500">按状态查看任务流转、负责人和审核情况。</p>
        </div>
        {runId && <span className="text-sm text-gray-500">Run: {runId}</span>}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4 lg:grid-cols-8">
        {STATUS_COLUMNS.map((status) => {
          const columnTasks = tasks.filter((task) => task.status === status)
          return (
            <div key={status} className="min-h-[220px] rounded-lg bg-gray-50 p-3">
              <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase text-gray-500">
                {TASK_STATUS_LABELS[status] || status}
                <Badge variant="secondary" className="text-xs">{columnTasks.length}</Badge>
              </div>
              <div className="space-y-2">
                {columnTasks.map((task) => (
                  <button
                    key={task.id}
                    onClick={() => setSelectedTask(task)}
                    className={`w-full rounded-md border p-2 text-left text-xs transition-colors hover:shadow ${STATUS_COLORS[task.status] || "bg-white"}`}
                  >
                    <div className="truncate font-medium">{task.title}</div>
                    <div className="mt-1 text-gray-500">
                      {task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"}
                    </div>
                    <div className="mt-1 flex gap-1">
                      <Badge variant="outline" className="px-1 py-0 text-[10px]">P{task.priority}</Badge>
                      <Badge variant="outline" className="px-1 py-0 text-[10px]">C{task.complexity}</Badge>
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
                {TASK_STATUS_LABELS[selectedTask.status] || selectedTask.status}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <span className="font-medium">任务说明：</span>
              {selectedTask.description}
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <div><span className="font-medium">类型：</span>{TASK_TYPE_LABELS[selectedTask.task_type] || selectedTask.task_type}</div>
              <div><span className="font-medium">优先级：</span>{selectedTask.priority}/10</div>
              <div><span className="font-medium">复杂度：</span>{selectedTask.complexity}/10</div>
              <div><span className="font-medium">可拆解：</span>{selectedTask.decomposability}/10</div>
            </div>
            <Separator />
            <div>
              <span className="font-medium">负责人：</span>
              {selectedTask.owner_agent ? agentMap[selectedTask.owner_agent] || selectedTask.owner_agent : "未分配"}
            </div>
            <div>
              <span className="font-medium">协作者：</span>
              {selectedTask.collaborator_agents?.length
                ? selectedTask.collaborator_agents.map((id) => agentMap[id] || id).join("、")
                : "暂无"}
            </div>
            {selectedTask.review_result && (
              <div className="rounded-lg bg-gray-50 p-3">
                <div className="font-medium">
                  审核结果：{selectedTask.review_result.approved ? "通过" : "需要修改"}
                </div>
                <div className="mt-1 text-gray-600">{selectedTask.review_result.feedback}</div>
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
