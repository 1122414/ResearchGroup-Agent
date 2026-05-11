"use client"

import type { CSSProperties, ReactNode } from "react"
import { Suspense, useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Activity, ClipboardList, PauseCircle, RotateCcw, Square, TerminalSquare } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import {
  AGENT_STATUS_LABELS,
  RUN_STATUS_LABELS,
  TASK_STATUS_LABELS,
  type OfficeAgentState,
  type OfficeState,
  type OfficeSubAgentState,
  type OfficeTaskState,
  type Run,
} from "@/lib/types"

const ROLE_META: Record<string, { label: string; color: string; coat: string }> = {
  advisor: { label: "导师", color: "#7c4a32", coat: "#d9b57c" },
  researcher: { label: "文献", color: "#315f9d", coat: "#4f7ee8" },
  engineer: { label: "工程", color: "#237050", coat: "#35b780" },
  experimenter: { label: "实验", color: "#9a6418", coat: "#f1a11d" },
  analyst: { label: "分析", color: "#8b2d2d", coat: "#ef4444" },
  writer: { label: "写作", color: "#5c37a2", coat: "#8b5cf6" },
  subagent: { label: "Sub", color: "#6b7280", coat: "#9ca3af" },
}

const ZONE_META: Record<string, { label: string; style: CSSProperties; furniture: ReactNode }> = {
  advisor_office: {
    label: "导师办公室",
    style: { left: "3%", top: "7%", width: "25%", height: "30%" },
    furniture: <><PixelBoard /><PixelDesk /></>,
  },
  task_board: {
    label: "公共任务看板",
    style: { left: "31%", top: "7%", width: "34%", height: "30%" },
    furniture: <PixelNoticeWall />,
  },
  lab: {
    label: "实验与数据区",
    style: { left: "68%", top: "7%", width: "29%", height: "30%" },
    furniture: <><PixelServer /><PixelPlant /></>,
  },
  research_office: {
    label: "文献工位",
    style: { left: "3%", top: "42%", width: "18%", height: "27%" },
    furniture: <PixelBookshelf />,
  },
  engineer_office: {
    label: "工程工位",
    style: { left: "24%", top: "42%", width: "18%", height: "27%" },
    furniture: <PixelMonitor />,
  },
  experiment_office: {
    label: "实验工位",
    style: { left: "45%", top: "42%", width: "18%", height: "27%" },
    furniture: <PixelLabBench />,
  },
  analyst_office: {
    label: "分析工位",
    style: { left: "66%", top: "42%", width: "14%", height: "27%" },
    furniture: <PixelChartWall />,
  },
  writer_office: {
    label: "写作工位",
    style: { left: "83%", top: "42%", width: "14%", height: "27%" },
    furniture: <PixelTypewriter />,
  },
  rest_area: {
    label: "休息区",
    style: { left: "22%", top: "73%", width: "31%", height: "20%" },
    furniture: <><PixelSofa /><PixelCoffee /></>,
  },
  temp_desk: {
    label: "临时工位",
    style: { left: "56%", top: "73%", width: "41%", height: "20%" },
    furniture: <PixelTempDesks />,
  },
}

const AGENT_LAYOUT: Record<string, { x: number; y: number }> = {
  advisor: { x: 52, y: 58 },
  researcher: { x: 47, y: 56 },
  engineer: { x: 50, y: 55 },
  experimenter: { x: 49, y: 55 },
  analyst: { x: 50, y: 56 },
  writer: { x: 50, y: 56 },
}

function runLabel(run: Run, index: number) {
  const goal = run.research_goal?.trim() || "未命名研究"
  return `第 ${index + 1} 次运行 · ${goal.slice(0, 18)}${goal.length > 18 ? "..." : ""}`
}

export default function OfficePage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm text-slate-500">正在加载像素办公室...</div>}>
      <OfficeContent />
    </Suspense>
  )
}

function OfficeContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialRunId = searchParams.get("run_id")
  const [runId, setRunId] = useState<string | null>(initialRunId)
  const [state, setState] = useState<OfficeState | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedAgent, setSelectedAgent] = useState<OfficeAgentState | null>(null)
  const [selectedTask, setSelectedTask] = useState<OfficeTaskState | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    api.getRuns().then(({ runs }) => {
      setRuns(runs)
      const queryExists = initialRunId && runs.some((run) => run.id === initialRunId)
      setRunId(queryExists ? initialRunId : runs[0]?.id || null)
    })
  }, [initialRunId])

  useEffect(() => {
    if (!runId) return
    let cancelled = false

    const fetchState = async () => {
      try {
        const data = await api.getOfficeState(runId)
        if (!cancelled) {
          setState(data)
          setError("")
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载办公室状态失败")
        }
      }
    }

    fetchState()
    const timer = window.setInterval(fetchState, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [runId])

  const handleCancel = async () => {
    if (!runId) return
    const confirmed = window.confirm("确认停止这次运行吗？")
    if (!confirmed) return
    try {
      await api.cancelRun(runId)
      setState(await api.getOfficeState(runId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止运行失败")
    }
  }

  const selectedRun = runs.find((run) => run.id === runId)

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 rounded-xl border border-stone-300 bg-[#f3e4c8] p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-stone-700">
            <TerminalSquare className="size-4" />
            Pixel studio monitor
          </div>
          <h2 className="mt-1 text-2xl font-bold text-stone-950">像素办公室</h2>
          <p className="mt-1 text-sm text-stone-700">每 2 秒同步运行状态，Agent 在对应工位显示当前任务和工作动作。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={runId || ""}
            onChange={(e) => {
              setRunId(e.target.value)
              setSelectedAgent(null)
              setSelectedTask(null)
            }}
            className="h-9 min-w-[260px] rounded-lg border border-stone-300 bg-[#fff7e8] px-3 text-sm text-stone-900 shadow-sm outline-none focus:border-stone-500"
          >
            {runs.map((run, index) => (
              <option key={run.id} value={run.id}>
                {runLabel(run, index)} ({RUN_STATUS_LABELS[run.status] || run.status})
              </option>
            ))}
          </select>
          <Button variant="outline" size="sm" className="border-stone-300 bg-[#fff7e8]" onClick={() => runId && api.getOfficeState(runId).then(setState)}>
            <RotateCcw className="size-3.5" />
            刷新
          </Button>
          {state && !["completed", "failed", "cancelled"].includes(state.run.status) && (
            <Button variant="destructive" size="sm" onClick={handleCancel}>
              <PauseCircle className="size-3.5" />
              停止
            </Button>
          )}
          <Button variant="outline" size="sm" className="border-stone-300 bg-[#fff7e8]" onClick={() => runId && router.push(`/runs/${runId}`)}>
            运行详情
          </Button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {!state && !error && <div className="text-sm text-slate-500">正在加载办公室状态...</div>}

      {state && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <PixelStudio state={state} onSelectAgent={setSelectedAgent} onSelectTask={setSelectedTask} />
          <aside className="space-y-4">
            <RunPanel state={state} selectedRunTitle={selectedRun?.research_goal || ""} />
            {selectedAgent && <AgentPanel agent={selectedAgent} />}
            {selectedTask && <TaskPanel task={selectedTask} />}
            {!selectedAgent && !selectedTask && <EventPanel state={state} />}
          </aside>
        </div>
      )}
    </div>
  )
}

function PixelStudio({
  state,
  onSelectAgent,
  onSelectTask,
}: {
  state: OfficeState
  onSelectAgent: (agent: OfficeAgentState) => void
  onSelectTask: (task: OfficeTaskState) => void
}) {
  const agentsByZone = useMemo(() => {
    const grouped: Record<string, OfficeAgentState[]> = {}
    for (const agent of state.agents) {
      const zone = agent.office_zone || "rest_area"
      if (!grouped[zone]) grouped[zone] = []
      grouped[zone].push(agent)
    }
    return grouped
  }, [state.agents])

  const labAgents = [
    ...(agentsByZone.experiment_office || []),
    ...(agentsByZone.analyst_office || []),
  ]

  return (
    <div className="pixel-shell">
      <div className="pixel-room">
        <div className="pixel-wall top" />
        <div className="pixel-wall bottom" />
        <div className="pixel-wall left" />
        <div className="pixel-wall right" />
        <PixelZone meta={ZONE_META.advisor_office} agents={agentsByZone.advisor_office || []} onSelectAgent={onSelectAgent} />
        <TaskBoardZone tasks={state.tasks} onSelectTask={onSelectTask} />
        <PixelZone meta={ZONE_META.lab} agents={labAgents} onSelectAgent={onSelectAgent} />
        <PixelZone meta={ZONE_META.research_office} agents={agentsByZone.research_office || []} onSelectAgent={onSelectAgent} />
        <PixelZone meta={ZONE_META.engineer_office} agents={agentsByZone.engineer_office || []} onSelectAgent={onSelectAgent} />
        <PixelZone meta={ZONE_META.experiment_office} agents={[]} onSelectAgent={onSelectAgent} />
        <PixelZone meta={ZONE_META.analyst_office} agents={[]} onSelectAgent={onSelectAgent} />
        <PixelZone meta={ZONE_META.writer_office} agents={agentsByZone.writer_office || []} onSelectAgent={onSelectAgent} />
        <PixelZone meta={ZONE_META.rest_area} agents={agentsByZone.rest_area || []} onSelectAgent={onSelectAgent} />
        <TempZone subagents={state.subagents} agents={agentsByZone.temp_desk || []} onSelectAgent={onSelectAgent} />
      </div>
    </div>
  )
}

function PixelZone({
  meta,
  agents,
  onSelectAgent,
}: {
  meta: { label: string; style: CSSProperties; furniture: ReactNode }
  agents: OfficeAgentState[]
  onSelectAgent: (agent: OfficeAgentState) => void
}) {
  return (
    <section className="pixel-zone" style={meta.style}>
      <div className="pixel-zone-label">{meta.label}</div>
      <div className="pixel-furniture">{meta.furniture}</div>
      {agents.map((agent, index) => {
        const layout = AGENT_LAYOUT[agent.role] || { x: 48, y: 56 }
        return (
          <PixelAgent
            key={agent.id}
            agent={agent}
            onClick={() => onSelectAgent(agent)}
            style={{ left: `${layout.x + index * 10}%`, top: `${layout.y + (index % 2) * 12}%` }}
          />
        )
      })}
    </section>
  )
}

function TaskBoardZone({ tasks, onSelectTask }: { tasks: OfficeTaskState[]; onSelectTask: (task: OfficeTaskState) => void }) {
  const visibleTasks = tasks.filter((task) => task.status !== "completed").slice(0, 6)
  const completedCount = tasks.filter((task) => task.status === "completed").length
  return (
    <section className="pixel-zone" style={ZONE_META.task_board.style}>
      <div className="pixel-zone-label">{ZONE_META.task_board.label}</div>
      <div className="pixel-task-board">
        {visibleTasks.length === 0 ? (
          <div className="pixel-board-done">
            <Square className="size-4" />
            当前没有待处理任务
          </div>
        ) : (
          visibleTasks.map((task) => (
            <button key={task.id} onClick={() => onSelectTask(task)} className="pixel-note">
              <span>{task.title}</span>
              <small>{TASK_STATUS_LABELS[task.status] || task.status}</small>
            </button>
          ))
        )}
      </div>
      {completedCount > 0 && <div className="pixel-complete-tag">已完成 {completedCount}</div>}
    </section>
  )
}

function TempZone({
  subagents,
  agents,
  onSelectAgent,
}: {
  subagents: OfficeSubAgentState[]
  agents: OfficeAgentState[]
  onSelectAgent: (agent: OfficeAgentState) => void
}) {
  return (
    <section className="pixel-zone" style={ZONE_META.temp_desk.style}>
      <div className="pixel-zone-label">{ZONE_META.temp_desk.label}</div>
      <div className="pixel-furniture">{ZONE_META.temp_desk.furniture}</div>
      {agents.map((agent, index) => (
        <PixelAgent key={agent.id} agent={agent} onClick={() => onSelectAgent(agent)} style={{ left: `${28 + index * 14}%`, top: "48%" }} />
      ))}
      {subagents.map((sub, index) => (
        <div key={sub.id} className="pixel-subagent" style={{ left: `${36 + index * 14}%`, top: "43%" }}>
          <div className="pixel-subagent-body" />
          <span>{sub.status}</span>
        </div>
      ))}
      {subagents.length === 0 && agents.length === 0 && <div className="pixel-empty-desk">暂无临时 SubAgent</div>}
    </section>
  )
}

function PixelAgent({ agent, onClick, style }: { agent: OfficeAgentState; onClick: () => void; style: CSSProperties }) {
  const meta = ROLE_META[agent.role] || ROLE_META.subagent
  const working = !["idle", "done", "waiting"].includes(agent.activity_state)
  return (
    <button className={`pixel-agent ${working ? "is-working" : ""}`} style={style} onClick={onClick} title={agent.speech}>
      <span className="pixel-speech">{agent.speech}</span>
      <span className="pixel-head" style={{ backgroundColor: meta.color }} />
      <span className="pixel-body" style={{ backgroundColor: meta.coat }} />
      <span className="pixel-agent-name">{meta.label}</span>
    </button>
  )
}

function RunPanel({ state, selectedRunTitle }: { state: OfficeState; selectedRunTitle: string }) {
  return (
    <Card className="border-stone-200 bg-[#fffaf0] shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="size-4 text-stone-600" />
          运行概览
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {selectedRunTitle && <div className="line-clamp-2 font-medium text-stone-900">{selectedRunTitle}</div>}
        <PanelRow label="状态" value={RUN_STATUS_LABELS[state.run.status] || state.run.status} />
        <PanelRow label="当前阶段" value={state.run.current_step || "-"} />
        <PanelRow label="Token" value={String(state.run.total_tokens)} />
        <PanelRow label="成本" value={`$${state.run.total_cost_usd.toFixed(4)}`} />
      </CardContent>
    </Card>
  )
}

function AgentPanel({ agent }: { agent: OfficeAgentState }) {
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{agent.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{AGENT_STATUS_LABELS[agent.status] || agent.status}</Badge>
          <span className="text-xs text-stone-500">{agent.activity_state}</span>
        </div>
        <div className="rounded-lg bg-stone-50 p-3 text-xs leading-5 text-stone-700">{agent.speech}</div>
        {agent.current_task_title && <PanelRow label="当前任务" value={agent.current_task_title} />}
        <PanelRow label="负载" value={`${Math.round(agent.current_load * 100)}%`} />
      </CardContent>
    </Card>
  )
}

function TaskPanel({ task }: { task: OfficeTaskState }) {
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <ClipboardList className="size-4" />
          任务详情
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="font-medium leading-5 text-stone-900">{task.title}</div>
        <Badge variant="secondary">{TASK_STATUS_LABELS[task.status] || task.status}</Badge>
        <PanelRow label="优先级" value={`${task.priority}/10`} />
        <div className="rounded-lg bg-stone-50 p-3 text-xs leading-5 text-stone-700">{task.latest_event}</div>
      </CardContent>
    </Card>
  )
}

function EventPanel({ state }: { state: OfficeState }) {
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">最近事件</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        {state.events.length === 0 && <div className="text-stone-500">暂无事件</div>}
        {state.events.map((event) => (
          <div key={event.id} className="rounded-lg border border-stone-200 bg-stone-50 p-2">
            <div className="font-medium text-stone-900">{event.title}</div>
            <div className="mt-1 line-clamp-2 text-stone-600">{event.message}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function PanelRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-stone-100 pb-2 last:border-0 last:pb-0">
      <span className="text-stone-500">{label}</span>
      <span className="text-right font-medium text-stone-900">{value}</span>
    </div>
  )
}

function PixelBoard() {
  return <div className="pixel-board"><span /><span /><span /><span /></div>
}

function PixelDesk() {
  return <div className="pixel-desk"><span /></div>
}

function PixelNoticeWall() {
  return <div className="pixel-notice-wall" />
}

function PixelServer() {
  return <div className="pixel-server"><span /><span /><span /></div>
}

function PixelPlant() {
  return <div className="pixel-plant"><span /></div>
}

function PixelBookshelf() {
  return <div className="pixel-bookshelf" />
}

function PixelMonitor() {
  return <div className="pixel-monitor" />
}

function PixelLabBench() {
  return <div className="pixel-labbench" />
}

function PixelChartWall() {
  return <div className="pixel-chartwall" />
}

function PixelTypewriter() {
  return <div className="pixel-typewriter" />
}

function PixelSofa() {
  return <div className="pixel-sofa" />
}

function PixelCoffee() {
  return <div className="pixel-coffee" />
}

function PixelTempDesks() {
  return <div className="pixel-tempdesks" />
}
