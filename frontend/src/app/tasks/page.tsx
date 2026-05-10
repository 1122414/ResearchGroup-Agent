"use client"

import { Suspense, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { SKILL_NAMES, TASK_STATUS_LABELS, TASK_TYPE_LABELS, type GraduateAgent, type Task } from "@/lib/types"

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
                    <div className="mt-1 flex flex-wrap gap-1">
                      <Badge variant="outline" className="px-1 py-0 text-[10px]">P{task.priority}</Badge>
                      <Badge variant="outline" className="px-1 py-0 text-[10px]">C{task.complexity}</Badge>
                      {task.assignment_info?.primary_skill && (
                        <Badge variant="outline" className="px-1 py-0 text-[10px]">
                          {SKILL_NAMES[task.assignment_info.primary_skill] || task.assignment_info.primary_skill}
                        </Badge>
                      )}
                      {task.subagent_triggered && (
                        <Badge variant="outline" className="px-1 py-0 text-[10px] border-pink-300 text-pink-700">
                          Sub
                        </Badge>
                      )}
                      {task.outputs?.length > 0 && (
                        <Badge variant="outline" className="px-1 py-0 text-[10px]">
                          产出 {task.outputs.length}
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
        <TaskDetailCard task={selectedTask} agentMap={agentMap} onClose={() => setSelectedTask(null)} />
      )}
    </div>
  )
}

function TaskDetailCard({
  task,
  agentMap,
  onClose,
}: {
  task: Task
  agentMap: Record<string, string>
  onClose: () => void
}) {
  const info = task.assignment_info || {}
  const topSkills = Object.entries(task.required_skills || {})
    .sort(([, a], [, b]) => (b as number) - (a as number))
    .slice(0, 3)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            {task.title}
            <Badge className={STATUS_COLORS[task.status]}>
              {TASK_STATUS_LABELS[task.status] || task.status}
            </Badge>
          </CardTitle>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="leading-6 text-gray-700">{task.description}</div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <DetailItem label="类型" value={TASK_TYPE_LABELS[task.task_type] || task.task_type} />
          <DetailItem label="优先级" value={`${task.priority}/10`} />
          <DetailItem label="复杂度" value={`${task.complexity}/10`} />
          <DetailItem label="可拆解" value={`${task.decomposability}/10`} />
        </div>

        <Separator />

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-lg border bg-gray-50 p-3">
            <div className="mb-2 text-xs font-semibold uppercase text-gray-500">调度信息</div>
            <div className="space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-600">负责人</span>
                <span>{task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">协作者</span>
                <span>
                  {task.collaborator_agents?.length
                    ? task.collaborator_agents.map((id) => agentMap[id] || id).join("、")
                    : "无"}
                </span>
              </div>
              {info.score !== undefined && (
                <div className="flex justify-between">
                  <span className="text-gray-600">调度分</span>
                  <span className="font-mono">{info.score}</span>
                </div>
              )}
              {info.skill_match !== undefined && (
                <div className="flex justify-between">
                  <span className="text-gray-600">技能匹配</span>
                  <span className="font-mono">{info.skill_match}</span>
                </div>
              )}
              {info.primary_skill && (
                <div className="flex justify-between">
                  <span className="text-gray-600">主要技能</span>
                  <span>
                    {SKILL_NAMES[info.primary_skill] || info.primary_skill}
                    {info.primary_skill_score !== undefined && ` (${info.primary_skill_score})`}
                  </span>
                </div>
              )}
              {info.idle_factor !== undefined && (
                <div className="flex justify-between">
                  <span className="text-gray-600">空闲度</span>
                  <span className="font-mono">{(info.idle_factor * 100).toFixed(0)}%</span>
                </div>
              )}
            </div>
          </div>

          <div className="rounded-lg border bg-gray-50 p-3">
            <div className="mb-2 text-xs font-semibold uppercase text-gray-500">所需技能</div>
            <div className="space-y-1">
              {topSkills.map(([skill, score]) => (
                <div key={skill} className="flex items-center gap-2">
                  <span className="w-20 text-xs text-gray-500">{SKILL_NAMES[skill] || skill}</span>
                  <div className="h-1.5 flex-1 rounded-full bg-gray-200">
                    <div
                      className="h-1.5 rounded-full bg-gray-700"
                      style={{ width: `${(score as number) * 10}%` }}
                    />
                  </div>
                  <span className="w-5 text-right text-xs">{score as number}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <Separator />

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <DetailItem label="SubAgent" value={task.subagent_triggered ? "已触发" : "未触发"} />
          <DetailItem label="产出数量" value={String(task.outputs?.length || 0)} />
          <DetailItem
            label="审核结果"
            value={
              task.review_result
                ? task.review_result.approved
                  ? "通过"
                  : "需要修改"
                : "待审核"
            }
          />
        </div>

        {task.review_result && (
          <div className="rounded-lg bg-gray-50 p-3">
            <div className="text-xs font-semibold text-gray-500">导师反馈</div>
            <div className="mt-1 text-gray-700">{task.review_result.feedback}</div>
          </div>
        )}

        {task.outputs && task.outputs.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-gray-500">产出列表</div>
            {task.outputs.map((output, idx) => (
              <div key={idx} className="rounded-lg border bg-white p-2 text-xs">
                <pre className="max-h-[120px] overflow-auto whitespace-pre-wrap text-gray-600">
                  {typeof output === "string" ? output : JSON.stringify(output, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}

        <div className="text-xs text-gray-400">
          创建：{task.created_at} | 更新：{task.updated_at}
        </div>
      </CardContent>
    </Card>
  )
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-white p-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-0.5 font-medium">{value}</div>
    </div>
  )
}
