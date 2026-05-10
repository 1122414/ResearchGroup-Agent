"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api"
import {
  AGENT_STATUS_LABELS,
  RUN_STATUS_LABELS,
  TASK_STATUS_LABELS,
  type OfficeAgentState,
  type OfficeState,
  type OfficeTaskState,
} from "@/lib/types"

const ZONE_POSITIONS: Record<string, { gridArea: string; label: string }> = {
  advisor_office: { gridArea: "advisor", label: "导师办公室" },
  research_office: { gridArea: "research", label: "文献办公室" },
  engineer_office: { gridArea: "engineer", label: "工程办公室" },
  experiment_office: { gridArea: "experiment", label: "实验办公室" },
  analyst_office: { gridArea: "analyst", label: "分析办公室" },
  writer_office: { gridArea: "writer", label: "写作办公室" },
  temp_desk: { gridArea: "temp", label: "临时工位" },
  rest_area: { gridArea: "rest", label: "休息区" },
  task_board: { gridArea: "board", label: "公共任务看板" },
}

const AGENT_COLORS: Record<string, string> = {
  advisor: "#6b4f9f",
  researcher: "#3b82f6",
  engineer: "#10b981",
  experimenter: "#f59e0b",
  analyst: "#ef4444",
  writer: "#8b5cf6",
  subagent: "#9ca3af",
}

const ACTIVITY_ANIMATION: Record<string, string> = {
  idle: "animate-bounce-slow",
  working: "animate-pulse-fast",
  researching: "animate-bounce-slow",
  coding: "animate-pulse-fast",
  experimenting: "animate-bounce-slow",
  analyzing: "animate-pulse-fast",
  writing: "animate-bounce-slow",
  reviewing: "animate-pulse",
  waiting: "animate-pulse-slow",
  blocked: "animate-shake",
  done: "animate-bounce-slow",
  decomposing: "animate-pulse",
  scheduling: "animate-pulse-fast",
}

export default function OfficePage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-gray-500">正在加载像素办公室...</div>}>
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
  const [runs, setRuns] = useState<{ id: string; status: string }[]>([])
  const [selectedAgent, setSelectedAgent] = useState<OfficeAgentState | null>(null)
  const [selectedTask, setSelectedTask] = useState<OfficeTaskState | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    api.getRuns().then(({ runs }) => {
      setRuns(runs.map((r) => ({ id: r.id, status: r.status })))
      if (!runId && runs.length > 0) {
        setRunId(runs[0].id)
      }
    })
  }, [runId])

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
    const confirmed = window.confirm("确定要停止这个运行吗？")
    if (!confirmed) return
    try {
      await api.cancelRun(runId)
      const data = await api.getOfficeState(runId)
      setState(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败")
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-bold">像素办公室</h2>
          <select
            value={runId || ""}
            onChange={(e) => {
              setRunId(e.target.value)
              setSelectedAgent(null)
              setSelectedTask(null)
            }}
            className="rounded-lg border bg-white px-3 py-1.5 text-sm"
          >
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.id} ({RUN_STATUS_LABELS[run.status] || run.status})
              </option>
            ))}
          </select>
        </div>

        {state && (
          <div className="flex items-center gap-3 text-sm">
            <Badge variant="secondary">{RUN_STATUS_LABELS[state.run.status] || state.run.status}</Badge>
            <span className="text-gray-500">成本 ${state.run.total_cost_usd.toFixed(4)}</span>
            <span className="text-gray-500">{state.run.total_tokens} tokens</span>
            {state.run.status !== "completed" && state.run.status !== "failed" && state.run.status !== "cancelled" && (
              <button
                onClick={handleCancel}
                className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700"
              >
                停止运行
              </button>
            )}
            <button
              onClick={() => runId && router.push(`/runs/${runId}`)}
              className="rounded-lg border px-3 py-1.5 text-xs hover:bg-gray-50"
            >
              运行详情
            </button>
          </div>
        )}
      </div>

      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {!state && !error && <div className="text-sm text-gray-500">正在加载办公室状态...</div>}

      {state && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
          <div className="lg:col-span-3">
            <OfficeCanvas
              state={state}
              onSelectAgent={setSelectedAgent}
              onSelectTask={setSelectedTask}
            />
          </div>

          <div className="space-y-4">
            {selectedAgent && <AgentDetail agent={selectedAgent} />}
            {selectedTask && <TaskDetail task={selectedTask} />}
            {!selectedAgent && !selectedTask && <RunDetail state={state} />}
          </div>
        </div>
      )}
    </div>
  )
}

function OfficeCanvas({
  state,
  onSelectAgent,
  onSelectTask,
}: {
  state: OfficeState
  onSelectAgent: (agent: OfficeAgentState) => void
  onSelectTask: (task: OfficeTaskState) => void
}) {
  const agentsByZone: Record<string, OfficeAgentState[]> = {}
  for (const agent of state.agents) {
    const zone = agent.office_zone || "rest_area"
    if (!agentsByZone[zone]) agentsByZone[zone] = []
    agentsByZone[zone].push(agent)
  }

  const subagents = state.subagents || []

  return (
    <div className="rounded-xl border bg-gray-50 p-4">
      <div
        className="grid gap-3"
        style={{
          gridTemplateAreas: `
            "advisor board board board board"
            "research engineer experiment analyst writer"
            "rest rest temp temp temp"
          `,
          gridTemplateColumns: "repeat(5, 1fr)",
          gridTemplateRows: "auto auto auto",
        }}
      >
        <OfficeZone area="advisor" label={ZONE_POSITIONS.advisor_office.label}>
          {agentsByZone["advisor_office"]?.map((agent) => (
            <AgentPixel key={agent.id} agent={agent} onClick={() => onSelectAgent(agent)} />
          ))}
        </OfficeZone>

        <OfficeZone area="board" label={ZONE_POSITIONS.task_board.label}>
          <div className="grid grid-cols-2 gap-1">
            {state.tasks.slice(0, 6).map((task) => (
              <button
                key={task.id}
                onClick={() => onSelectTask(task)}
                className="rounded border bg-white p-1.5 text-left text-[10px] hover:bg-gray-50"
              >
                <div className="truncate font-medium">{task.title}</div>
                <div className="mt-0.5 text-gray-400">{task.latest_event}</div>
              </button>
            ))}
          </div>
        </OfficeZone>

        {["research_office", "engineer_office", "experiment_office", "analyst_office", "writer_office"].map(
          (zone) => (
            <OfficeZone key={zone} area={zone.replace("_office", "")} label={ZONE_POSITIONS[zone]?.label || zone}>
              {agentsByZone[zone]?.map((agent) => (
                <AgentPixel key={agent.id} agent={agent} onClick={() => onSelectAgent(agent)} />
              ))}
            </OfficeZone>
          ),
        )}

        <OfficeZone area="rest" label={ZONE_POSITIONS.rest_area.label}>
          {agentsByZone["rest_area"]?.map((agent) => (
            <AgentPixel key={agent.id} agent={agent} onClick={() => onSelectAgent(agent)} />
          ))}
        </OfficeZone>

        <OfficeZone area="temp" label={ZONE_POSITIONS.temp_desk.label}>
          {subagents.map((sub) => (
            <div
              key={sub.id}
              className="flex flex-col items-center gap-1 rounded-lg border border-dashed bg-white/50 p-2"
            >
              <div
                className="h-8 w-8 rounded bg-gray-300 opacity-60"
                style={{ backgroundColor: AGENT_COLORS.subagent }}
              />
              <div className="text-[10px] text-gray-500">SubAgent</div>
            </div>
          ))}
          {subagents.length === 0 && (
            <div className="text-center text-xs text-gray-400">暂无临时 SubAgent</div>
          )}
        </OfficeZone>
      </div>
    </div>
  )
}

function OfficeZone({
  area,
  label,
  children,
}: {
  area: string
  label: string
  children: React.ReactNode
}) {
  return (
    <div
      className="min-h-[120px] rounded-lg border bg-white p-2"
      style={{ gridArea: area }}
    >
      <div className="mb-2 text-[10px] font-semibold uppercase text-gray-400">{label}</div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  )
}

function AgentPixel({
  agent,
  onClick,
}: {
  agent: OfficeAgentState
  onClick: () => void
}) {
  const color = AGENT_COLORS[agent.role] || "#6b7280"
  const animClass = ACTIVITY_ANIMATION[agent.activity_state] || ""

  return (
    <button
      onClick={onClick}
      className="group relative flex flex-col items-center gap-1"
    >
      <div
        className={`relative h-10 w-10 rounded border-2 transition-transform hover:scale-110 ${animClass}`}
        style={{ backgroundColor: color, borderColor: color }}
      >
        <div className="absolute left-1.5 top-2.5 h-1 w-1 rounded-full bg-white" />
        <div className="absolute right-1.5 top-2.5 h-1 w-1 rounded-full bg-white" />
      </div>
      <div className="max-w-[80px] truncate text-[10px] font-medium">{agent.name}</div>

      <div className="absolute -top-8 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-lg bg-gray-900 px-2 py-1 text-[10px] text-white group-hover:block">
        {agent.speech}
        <div className="absolute -bottom-1 left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 bg-gray-900" />
      </div>
    </button>
  )
}

function AgentDetail({ agent }: { agent: OfficeAgentState }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{agent.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{AGENT_STATUS_LABELS[agent.status] || agent.status}</Badge>
          <span className="text-xs text-gray-500">{agent.activity_state}</span>
        </div>
        <div className="rounded-lg bg-gray-50 p-2 text-xs text-gray-600">{agent.speech}</div>
        {agent.current_task_title && (
          <div className="text-xs">
            <span className="text-gray-500">当前任务：</span> {agent.current_task_title}
          </div>
        )}
        <div className="text-xs text-gray-400">负载：{Math.round(agent.current_load * 100)}%</div>
      </CardContent>
    </Card>
  )
}

function TaskDetail({ task }: { task: OfficeTaskState }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <span className="truncate">{task.title}</span>
          <Badge variant="secondary">{TASK_STATUS_LABELS[task.status] || task.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="text-xs text-gray-500">优先级：{task.priority}/10</div>
        <div className="rounded-lg bg-gray-50 p-2 text-xs text-gray-600">{task.latest_event}</div>
      </CardContent>
    </Card>
  )
}

function RunDetail({ state }: { state: OfficeState }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">运行概览</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-gray-500">状态</span>
          <Badge>{RUN_STATUS_LABELS[state.run.status] || state.run.status}</Badge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">当前阶段</span>
          <span>{state.run.current_step || "-"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">成本</span>
          <span className="font-mono">${state.run.total_cost_usd.toFixed(4)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Token</span>
          <span className="font-mono">{state.run.total_tokens}</span>
        </div>
        <div className="h-px bg-gray-200" />
        <div className="text-xs text-gray-500">点击办公室中的角色或任务查看详情</div>
      </CardContent>
    </Card>
  )
}
