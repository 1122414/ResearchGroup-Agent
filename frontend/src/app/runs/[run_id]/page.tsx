"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { frontendLogger } from "@/lib/logger"
import { runDisplayName } from "@/lib/run-display"
import {
  AGENT_STATUS_LABELS,
  RUN_STATUS_LABELS,
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
  type LLMUsage,
  type RunEvent,
  type RunSummary,
} from "@/lib/types"

const FINAL_STATUSES = new Set(["completed", "failed", "cancelled"])

export default function RunDetailPage() {
  const params = useParams<{ run_id: string }>()
  const router = useRouter()
  const runId = params.run_id
  const [summary, setSummary] = useState<RunSummary | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [usageItems, setUsageItems] = useState<LLMUsage[]>([])
  const [error, setError] = useState("")
  const [canceling, setCanceling] = useState(false)
  const [selectedEventIndex, setSelectedEventIndex] = useState(0)
  const startedRef = useRef(false)

  useEffect(() => {
    frontendLogger.info(`RunDetailPage mounted | run_id=${runId}`)
    frontendLogger.setRunId(runId)
    let cancelled = false

    const fetchData = async () => {
      try {
        const [summaryData, eventsData, usageData] = await Promise.all([
          api.getRunSummary(runId),
          api.getRunEvents(runId, 200),
          api.getRunUsage(runId),
        ])
        if (cancelled) return
        setSummary(summaryData)
        setEvents(eventsData.events)
        setSelectedEventIndex((index) => Math.min(index, Math.max(eventsData.events.length - 1, 0)))
        setUsageItems(usageData.items)
        setError("")
        frontendLogger.debug(`RunDetailPage data refreshed | run_id=${runId} | status=${summaryData.run.status}`)

        if (summaryData.run.status === "created" && !startedRef.current) {
          startedRef.current = true
          frontendLogger.info(`RunDetailPage auto-starting run | run_id=${runId}`)
          api.startRun(runId).catch((err) => {
            const msg = err instanceof Error ? err.message : "启动运行失败"
            frontendLogger.error(`RunDetailPage auto-start failed | run_id=${runId} | error=${msg}`)
            setError(msg)
          })
        }
      } catch (err) {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : "加载运行详情失败"
        frontendLogger.error(`RunDetailPage fetch failed | run_id=${runId} | error=${msg}`)
        setError(msg)
      }
    }

    fetchData()
    const timer = window.setInterval(() => {
      setSummary((prev) => {
        if (!prev || FINAL_STATUSES.has(prev.run.status)) {
          return prev
        }
        fetchData()
        return prev
      })
    }, 1500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      frontendLogger.info(`RunDetailPage unmounted | run_id=${runId}`)
    }
  }, [runId])

  const canCancel = summary && !FINAL_STATUSES.has(summary.run.status) && summary.run.status !== "cancelling"
  const agentMap = useMemo(
    () => Object.fromEntries((summary?.agents || []).map((agent) => [agent.id, agent.name])),
    [summary],
  )
  const agentRoleMap = useMemo(
    () => Object.fromEntries((summary?.agents || []).map((agent) => [agent.id, agent.type])),
    [summary],
  )

  const handleCancel = async () => {
    if (!summary) return
    const confirmed = window.confirm("确定要停止这个运行吗？已生成的任务、事件和产出会保留。")
    if (!confirmed) return
    frontendLogger.info(`RunDetailPage cancel requested | run_id=${summary.run.id}`)
    setCanceling(true)
    try {
      await api.cancelRun(summary.run.id)
      frontendLogger.info(`RunDetailPage cancel success | run_id=${summary.run.id}`)
      const [summaryData, eventsData, usageData] = await Promise.all([
        api.getRunSummary(runId),
        api.getRunEvents(runId, 200),
        api.getRunUsage(runId),
      ])
      setSummary(summaryData)
      setEvents(eventsData.events)
      setUsageItems(usageData.items)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "停止运行失败"
      frontendLogger.error(`RunDetailPage cancel failed | run_id=${summary.run.id} | error=${msg}`)
      setError(msg)
    } finally {
      setCanceling(false)
    }
  }

  if (!summary) {
    return (
      <div className="page-stack">
        <div className="text-sm text-[var(--rg-muted)]">正在加载运行详情...</div>
        {error && <div className="error-banner p-3 text-sm">{error}</div>}
      </div>
    )
  }

  return (
    <div className="page-stack">
      <Card className="surface-card">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle>{runDisplayName(summary.run)}</CardTitle>
                <Badge variant={FINAL_STATUSES.has(summary.run.status) ? "secondary" : "default"}>
                  {RUN_STATUS_LABELS[summary.run.status] || summary.run.status}
                </Badge>
              </div>
              <div className="text-xs text-[var(--rg-muted)]">内部 ID：{summary.run.id}</div>
              {summary.run.artifact_dir && <div className="break-all text-xs text-[var(--rg-muted)]">产物目录：{summary.run.artifact_dir}</div>}
              <CardDescription className="max-w-4xl leading-6">{summary.run.research_goal}</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => router.push(`/tasks?run_id=${summary.run.id}`)}
              >
                查看任务板
              </Button>
              <Button
                variant="destructive"
                onClick={handleCancel}
                disabled={!canCancel || canceling}
              >
                {canceling || summary.run.status === "cancelling" ? "正在停止" : "停止运行"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 text-sm md:grid-cols-4">
          <Metric label="当前阶段" value={summary.run.current_step || "等待更新"} />
          <Metric label="任务总数" value={String(summary.counts.tasks_total)} />
          <Metric label="累计 Token" value={String(summary.usage.total_tokens || 0)} />
          <Metric label="累计成本 USD" value={(summary.usage.total_cost_usd || 0).toFixed(6)} />
        </CardContent>
      </Card>

      {error && <div className="error-banner p-3 text-sm">{error}</div>}

      <EventFlowGraph
        events={events}
        selectedIndex={selectedEventIndex}
        onSelect={setSelectedEventIndex}
        agentMap={agentMap}
        agentRoleMap={agentRoleMap}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="surface-card lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">事件时间线</CardTitle>
            <CardDescription>系统每个阶段发生了什么，会持续写入这里。</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[520px] space-y-3 overflow-auto">
            {events.length === 0 && <div className="text-sm text-[var(--rg-muted)]">暂无事件。</div>}
            {events.slice().reverse().map((event) => (
              <div key={event.id} className="data-row p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium">{event.title}</div>
                  <Badge variant="secondary">{event.phase}</Badge>
                </div>
                <div className="mt-1 text-[var(--rg-body)]">{event.message}</div>
                <div className="mt-2 text-xs text-[var(--rg-muted)]">
                  {event.created_at}
                  {event.agent_id ? ` | ${agentMap[event.agent_id] || event.agent_id}` : ""}
                  {event.task_id ? ` | ${event.task_id}` : ""}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader>
            <CardTitle className="text-base">成本监测</CardTitle>
            <CardDescription>Mock 模式成本为 0，但仍会记录 token 估算。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Metric label="LLM 调用次数" value={String(summary.usage.total_llm_calls || 0)} />
            <Metric label="失败调用" value={String(summary.usage.failed_llm_calls || 0)} />
            <Metric label="累计 Token" value={String(summary.usage.total_tokens || 0)} />
            <Metric label="累计成本" value={`$${(summary.usage.total_cost_usd || 0).toFixed(6)}`} />
            <Separator />
            <div className="max-h-[260px] space-y-2 overflow-auto">
              {usageItems.map((item) => (
                <div key={item.id} className="rounded-lg bg-[var(--rg-surface-soft)] p-2 text-xs">
                  <div className="font-medium">{item.role} · {item.model}</div>
                  <div className="text-[var(--rg-muted)]">
                    {item.total_tokens} tokens · ${item.cost_usd.toFixed(6)} · {item.latency_ms}ms
                  </div>
                </div>
              ))}
              {usageItems.length === 0 && <div className="text-xs text-[var(--rg-muted)]">暂无调用记录。</div>}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="surface-card">
          <CardHeader>
            <CardTitle className="text-base">任务执行表</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {summary.tasks.map((task) => (
              <div key={task.id} className="data-row p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium">{task.title}</div>
                  <Badge variant="secondary">{TASK_STATUS_LABELS[task.status] || task.status}</Badge>
                </div>
                <div className="mt-1 text-xs text-[var(--rg-muted)]">
                  {TASK_TYPE_LABELS[task.task_type] || task.task_type} · 负责人：
                  {task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"} · P{task.priority} C{task.complexity}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader>
            <CardTitle className="text-base">Agent 活动</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {summary.agents
              .filter((agent) => ["researcher", "engineer", "experimenter", "analyst", "writer"].includes(agent.type))
              .map((agent) => (
                <div key={agent.id} className="data-row p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium">{agent.name}</div>
                    <Badge variant="secondary">{AGENT_STATUS_LABELS[agent.status] || agent.status}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-[var(--rg-muted)]">
                    负载 {Math.round(agent.current_load * 100)}% · 当前任务：
                    {agent.current_tasks?.length ? agent.current_tasks.join("、") : "暂无"}
                  </div>
                </div>
              ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function EventFlowGraph({
  events,
  selectedIndex,
  onSelect,
  agentMap,
  agentRoleMap,
}: {
  events: RunEvent[]
  selectedIndex: number
  onSelect: (index: number) => void
  agentMap: Record<string, string>
  agentRoleMap: Record<string, string>
}) {
  const orderedEvents = useMemo(() => {
    return events.slice().sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  }, [events])
  const selectedEvent = orderedEvents[selectedIndex] || orderedEvents[0] || null
  const relation = selectedEvent ? inferEventRelation(selectedEvent, agentMap, agentRoleMap) : null

  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">事件关系图</CardTitle>
        <CardDescription>点击时间节点，查看导师、研究生 Agent、本科 SubAgent 和系统之间的协作关系。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {orderedEvents.length === 0 || !relation || !selectedEvent ? (
          <div className="soft-card p-6 text-center text-sm text-[var(--rg-muted)]">暂无事件关系。</div>
        ) : (
          <>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {orderedEvents.map((event, index) => (
                <button
                  key={event.id}
                  onClick={() => onSelect(index)}
                  className={`shrink-0 rounded-full border px-3 py-1.5 text-xs transition ${
                    index === selectedIndex
                      ? "border-[var(--rg-linear)] bg-[#eef0ff] text-[#3b4395]"
                      : "border-[var(--rg-hairline)] bg-white text-[var(--rg-muted)] hover:text-[var(--rg-ink)]"
                  }`}
                >
                  {index + 1}. {event.phase}
                </button>
              ))}
            </div>

            <div className="grid gap-3 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
              <ActorNode title={relation.sourceTitle} subtitle={relation.sourceSubtitle} tone={relation.sourceTone} />
              <div className="flex flex-col items-center gap-2 text-center">
                <div className="hidden h-px w-20 bg-[var(--rg-hairline)] lg:block" />
                <div className="rounded-full border border-[var(--rg-hairline)] bg-white px-3 py-1 text-xs font-medium text-[var(--rg-body)]">
                  {relation.action}
                </div>
                <div className="hidden h-px w-20 bg-[var(--rg-hairline)] lg:block" />
              </div>
              <ActorNode title={relation.targetTitle} subtitle={relation.targetSubtitle} tone={relation.targetTone} />
            </div>

            <div className="soft-card p-3 text-sm">
              <div className="font-medium text-[var(--rg-ink)]">{selectedEvent.title}</div>
              <div className="mt-1 leading-6 text-[var(--rg-body)]">{selectedEvent.message}</div>
              <div className="mt-2 text-xs text-[var(--rg-muted)]">
                {selectedEvent.created_at}
                {selectedEvent.task_id ? ` · ${selectedEvent.task_id}` : ""}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function ActorNode({ title, subtitle, tone }: { title: string; subtitle: string; tone: "advisor" | "graduate" | "subagent" | "system" }) {
  const toneClass = {
    advisor: "border-[#ead1c6] bg-[#fff3ef] text-[#964b36]",
    graduate: "border-[#cfd3ff] bg-[#eef0ff] text-[#3b4395]",
    subagent: "border-[#d9dce3] bg-[#f4f5f7] text-[#4b5563]",
    system: "border-[var(--rg-hairline)] bg-[var(--rg-surface-soft)] text-[var(--rg-body)]",
  }[tone]

  return (
    <div className={`rounded-xl border p-4 ${toneClass}`}>
      <div className="text-xs font-semibold uppercase tracking-wide opacity-70">{subtitle}</div>
      <div className="mt-2 text-lg font-semibold">{title}</div>
    </div>
  )
}

function inferEventRelation(event: RunEvent, agentMap: Record<string, string>, agentRoleMap: Record<string, string>) {
  const text = `${event.title} ${event.message} ${event.phase} ${event.event_type}`.toLowerCase()
  const agentName = event.agent_id ? agentMap[event.agent_id] || event.agent_id : ""
  const agentRole = event.agent_id ? agentRoleMap[event.agent_id] || "" : ""
  const isAdvisor = event.agent_id === "advisor" || agentRole === "advisor" || text.includes("导师")
  const isSubagent = Boolean(event.subagent_id) || text.includes("subagent") || text.includes("本科")
  const isRevision = text.includes("返工") || text.includes("修改") || text.includes("revision") || text.includes("驳回")
  const isReview = text.includes("审核") || text.includes("review")
  const isSkill = text.includes("skill")

  if (isSubagent) {
    return {
      sourceTitle: agentName || "研究生 Agent",
      sourceSubtitle: "委派方",
      sourceTone: "graduate" as const,
      action: "委派/整合",
      targetTitle: event.subagent_id || "本科 SubAgent",
      targetSubtitle: "临时执行者",
      targetTone: "subagent" as const,
    }
  }

  if (isRevision) {
    return {
      sourceTitle: "导师 Agent",
      sourceSubtitle: "审核方",
      sourceTone: "advisor" as const,
      action: "要求返工",
      targetTitle: agentName || "研究生 Agent",
      targetSubtitle: "执行方",
      targetTone: "graduate" as const,
    }
  }

  if (isReview && !isAdvisor) {
    return {
      sourceTitle: agentName || "研究生 Agent",
      sourceSubtitle: "提交方",
      sourceTone: "graduate" as const,
      action: "提交审核",
      targetTitle: "导师 Agent",
      targetSubtitle: "审核方",
      targetTone: "advisor" as const,
    }
  }

  if (isAdvisor) {
    return {
      sourceTitle: "导师 Agent",
      sourceSubtitle: "调度/审核",
      sourceTone: "advisor" as const,
      action: isSkill ? "沉淀经验" : "分派/确认",
      targetTitle: agentName && agentName !== "advisor" ? agentName : "研究生团队",
      targetSubtitle: "协作对象",
      targetTone: "graduate" as const,
    }
  }

  if (event.agent_id) {
    return {
      sourceTitle: agentName || event.agent_id,
      sourceSubtitle: "研究生 Agent",
      sourceTone: "graduate" as const,
      action: isSkill ? "沉淀 Skill" : "执行任务",
      targetTitle: isSkill ? "Skill Library" : "任务板",
      targetSubtitle: isSkill ? "经验库" : "系统状态机",
      targetTone: "system" as const,
    }
  }

  return {
    sourceTitle: "系统",
    sourceSubtitle: "状态机",
    sourceTone: "system" as const,
    action: "推进流程",
    targetTitle: isReview ? "导师 Agent" : "任务板",
    targetSubtitle: isReview ? "审核方" : "协作面板",
    targetTone: isReview ? ("advisor" as const) : ("system" as const),
  }
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <div className="text-xs text-[var(--rg-muted)]">{label}</div>
      <div className="mt-1 break-words text-lg font-semibold text-[var(--rg-ink)]">{value}</div>
    </div>
  )
}
