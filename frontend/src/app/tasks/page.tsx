"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Archive, CheckCircle2, ChevronDown, CircleDashed, LayoutDashboard, RotateCcw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { SKILL_NAMES, TASK_STATUS_LABELS, TASK_TYPE_LABELS, type GraduateAgent, type Run, type Task } from "@/lib/types"

const ACTIVE_COLUMNS = ["pending", "assigned", "running", "waiting_collab", "waiting_subagent", "waiting_review", "need_revision"]

const STATUS_STYLES: Record<string, string> = {
  pending: "border-slate-200 bg-slate-50 text-slate-700",
  assigned: "border-sky-200 bg-sky-50 text-sky-800",
  running: "border-indigo-200 bg-indigo-50 text-indigo-800",
  waiting_collab: "border-violet-200 bg-violet-50 text-violet-800",
  waiting_subagent: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
  waiting_review: "border-amber-200 bg-amber-50 text-amber-800",
  need_revision: "border-rose-200 bg-rose-50 text-rose-800",
  completed: "border-emerald-200 bg-emerald-50 text-emerald-800",
}

function primaryGoal(goal: string) {
  return goal.split("## 用户上传的多模态附件上下文", 1)[0].trim()
}

function formatRunLabel(run: Run, index: number) {
  const date = run.created_at ? new Date(run.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""
  const goal = primaryGoal(run.research_goal || "") || "未命名研究"
  const prefix = index === 0 ? "最新运行" : `历史运行 ${index + 1}`
  return `${prefix} · ${goal.slice(0, 24)}${goal.length > 24 ? "..." : ""}${date ? ` · ${date}` : ""}`
}

export default function TasksPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm text-slate-500">正在加载任务板...</div>}>
      <TasksContent />
    </Suspense>
  )
}

function TasksContent() {
  const searchParams = useSearchParams()
  const queryRunId = searchParams.get("run_id")
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(queryRunId)
  const [tasks, setTasks] = useState<Task[]>([])
  const [agents, setAgents] = useState<GraduateAgent[]>([])
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [showCompleted, setShowCompleted] = useState(false)

  useEffect(() => {
    Promise.all([api.getRuns(), api.getAgents()]).then(([{ runs }, { agents }]) => {
      setRuns(runs)
      setAgents(agents)
      const queryExists = queryRunId && runs.some((run) => run.id === queryRunId)
      setSelectedRunId(queryExists ? queryRunId : runs[0]?.id || null)
    })
  }, [queryRunId])

  useEffect(() => {
    if (!selectedRunId) {
      queueMicrotask(() => setTasks([]))
      return
    }
    api.getTasks(selectedRunId).then(({ tasks }) => setTasks(tasks))
  }, [selectedRunId])

  const agentMap = Object.fromEntries(agents.map((agent) => [agent.id, agent.name]))
  const completedTasks = tasks.filter((task) => task.status === "completed")
  const activeTasks = tasks.filter((task) => task.status !== "completed")
  const allDone = tasks.length > 0 && activeTasks.length === 0

  const counts = useMemo(() => {
    return tasks.reduce<Record<string, number>>((acc, task) => {
      acc[task.status] = (acc[task.status] || 0) + 1
      return acc
    }, {})
  }, [tasks])

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-slate-500">
              <LayoutDashboard className="size-4" />
              Research task board
            </div>
            <h2 className="mt-2 text-2xl font-bold text-slate-950">任务板</h2>
            <p className="mt-1 text-sm text-slate-500">每次进入默认查看最新运行。已完成任务归档，主看板只保留待处理工作。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={selectedRunId || ""}
              onChange={(event) => {
                setSelectedRunId(event.target.value)
                setSelectedTask(null)
                setShowCompleted(false)
              }}
              className="h-9 min-w-[300px] rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 shadow-sm outline-none focus:border-slate-400"
            >
              {runs.map((run, index) => (
                <option key={run.id} value={run.id}>
                  {formatRunLabel(run, index)}
                </option>
              ))}
            </select>
            <Button variant="outline" size="sm" onClick={() => selectedRunId && api.getTasks(selectedRunId).then(({ tasks }) => setTasks(tasks))}>
              <RotateCcw className="size-3.5" />
              刷新
            </Button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="全部任务" value={tasks.length} />
          <Metric label="执行中" value={(counts.running || 0) + (counts.waiting_collab || 0) + (counts.waiting_subagent || 0)} />
          <Metric label="待审核/修改" value={(counts.waiting_review || 0) + (counts.need_revision || 0)} />
          <Metric label="已完成归档" value={completedTasks.length} />
        </div>
      </div>

      {allDone && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="size-4" />
            当前运行的任务已经全部完成，主看板已清空，完成项收纳在归档区。
          </div>
          <Button variant="outline" size="sm" className="border-emerald-300 bg-white/80" onClick={() => setShowCompleted((value) => !value)}>
            <Archive className="size-3.5" />
            {showCompleted ? "收起归档" : "查看归档"}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-7">
        {ACTIVE_COLUMNS.map((status) => {
          const columnTasks = tasks.filter((task) => task.status === status)
          return (
            <div key={status} className="min-h-[260px] rounded-xl border border-slate-200 bg-slate-50/70 p-3">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-semibold uppercase text-slate-500">{TASK_STATUS_LABELS[status] || status}</div>
                <Badge variant="secondary" className="rounded-full bg-white text-xs">{columnTasks.length}</Badge>
              </div>
              {columnTasks.length === 0 ? (
                <div className="flex h-32 flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white/60 text-xs text-slate-400">
                  <CircleDashed className="mb-2 size-4" />
                  暂无任务
                </div>
              ) : (
                <div className="space-y-2">
                  {columnTasks.map((task) => (
                    <TaskCard key={task.id} task={task} agentMap={agentMap} onClick={() => setSelectedTask(task)} />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {completedTasks.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <button onClick={() => setShowCompleted((value) => !value)} className="flex w-full items-center justify-between px-4 py-3 text-left">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Archive className="size-4 text-emerald-700" />
              已完成归档
              <Badge variant="secondary" className="rounded-full">{completedTasks.length}</Badge>
            </div>
            <ChevronDown className={`size-4 text-slate-400 transition-transform ${showCompleted ? "rotate-180" : ""}`} />
          </button>
          {showCompleted && (
            <div className="grid grid-cols-1 gap-3 border-t border-slate-100 p-4 md:grid-cols-2 xl:grid-cols-4">
              {completedTasks.map((task) => (
                <TaskCard key={task.id} task={task} agentMap={agentMap} onClick={() => setSelectedTask(task)} compact />
              ))}
            </div>
          )}
        </section>
      )}

      {selectedTask && <TaskDetailCard task={selectedTask} agentMap={agentMap} onClose={() => setSelectedTask(null)} />}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-950">{value}</div>
    </div>
  )
}

function TaskCard({ task, agentMap, onClick, compact = false }: { task: Task; agentMap: Record<string, string>; onClick: () => void; compact?: boolean }) {
  return (
    <button onClick={onClick} className={`w-full rounded-lg border p-3 text-left text-xs shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${STATUS_STYLES[task.status] || "border-slate-200 bg-white text-slate-700"}`}>
      <div className="line-clamp-2 font-semibold leading-5">{task.title}</div>
      <div className="mt-1 text-slate-500">{task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"}</div>
      {!compact && task.description && <div className="mt-2 line-clamp-2 text-slate-500">{task.description}</div>}
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge variant="outline" className="bg-white/50 px-1.5 py-0 text-[10px]">P{task.priority}</Badge>
        <Badge variant="outline" className="bg-white/50 px-1.5 py-0 text-[10px]">C{task.complexity}</Badge>
        {task.assignment_info?.primary_skill && (
          <Badge variant="outline" className="bg-white/50 px-1.5 py-0 text-[10px]">
            {SKILL_NAMES[task.assignment_info.primary_skill] || task.assignment_info.primary_skill}
          </Badge>
        )}
        {task.subagent_triggered && <Badge variant="outline" className="border-fuchsia-300 bg-white/50 px-1.5 py-0 text-[10px] text-fuchsia-700">Sub</Badge>}
      </div>
    </button>
  )
}

function TaskDetailCard({ task, agentMap, onClose }: { task: Task; agentMap: Record<string, string>; onClose: () => void }) {
  const info = task.assignment_info || {}
  const topSkills = Object.entries(task.required_skills || {})
    .sort(([, a], [, b]) => (b as number) - (a as number))
    .slice(0, 3)

  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-lg">{task.title}</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>关闭</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid gap-3 md:grid-cols-4">
          <Info label="状态" value={TASK_STATUS_LABELS[task.status] || task.status} />
          <Info label="类型" value={TASK_TYPE_LABELS[task.task_type] || task.task_type} />
          <Info label="负责人" value={task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"} />
          <Info label="复杂度" value={`P${task.priority} / C${task.complexity}`} />
        </div>
        <Separator />
        <div>
          <div className="mb-1 font-semibold text-slate-800">任务描述</div>
          <p className="leading-7 text-slate-600">{task.description || "暂无描述"}</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <div className="mb-2 font-semibold text-slate-800">关键技能</div>
            <div className="flex flex-wrap gap-2">
              {topSkills.map(([skill, score]) => (
                <Badge key={skill} variant="outline">{SKILL_NAMES[skill] || skill} {String(score)}</Badge>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 font-semibold text-slate-800">调度评分</div>
            <div className="text-slate-600">
              {info.score ? `综合分 ${Number(info.score).toFixed(1)}，主技能 ${SKILL_NAMES[info.primary_skill || ""] || info.primary_skill || "未知"}` : "暂无调度信息"}
            </div>
          </div>
        </div>
        {task.outputs?.length > 0 && (
          <div>
            <div className="mb-2 font-semibold text-slate-800">任务产出</div>
            <pre className="max-h-64 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-700 whitespace-pre-wrap">
              {JSON.stringify(task.outputs, null, 2)}
            </pre>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
    </div>
  )
}
