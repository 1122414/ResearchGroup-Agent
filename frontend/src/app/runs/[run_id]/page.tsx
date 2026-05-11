"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { frontendLogger } from "@/lib/logger"
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
      <div className="space-y-4">
        <div className="text-sm text-gray-500">正在加载运行详情...</div>
        {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle>{summary.run.id}</CardTitle>
                <Badge variant={FINAL_STATUSES.has(summary.run.status) ? "secondary" : "default"}>
                  {RUN_STATUS_LABELS[summary.run.status] || summary.run.status}
                </Badge>
              </div>
              <CardDescription className="max-w-4xl leading-6">{summary.run.research_goal}</CardDescription>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => router.push(`/tasks?run_id=${summary.run.id}`)}
                className="rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
              >
                查看任务板
              </button>
              <button
                onClick={handleCancel}
                disabled={!canCancel || canceling}
                className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {canceling || summary.run.status === "cancelling" ? "正在停止" : "停止运行"}
              </button>
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

      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">事件时间线</CardTitle>
            <CardDescription>系统每个阶段发生了什么，会持续写入这里。</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[520px] space-y-3 overflow-auto">
            {events.length === 0 && <div className="text-sm text-gray-500">暂无事件。</div>}
            {events.slice().reverse().map((event) => (
              <div key={event.id} className="rounded-lg border bg-white p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium">{event.title}</div>
                  <Badge variant="secondary">{event.phase}</Badge>
                </div>
                <div className="mt-1 text-gray-600">{event.message}</div>
                <div className="mt-2 text-xs text-gray-400">
                  {event.created_at}
                  {event.agent_id ? ` | ${agentMap[event.agent_id] || event.agent_id}` : ""}
                  {event.task_id ? ` | ${event.task_id}` : ""}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
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
                <div key={item.id} className="rounded-lg bg-gray-50 p-2 text-xs">
                  <div className="font-medium">{item.role} · {item.model}</div>
                  <div className="text-gray-500">
                    {item.total_tokens} tokens · ${item.cost_usd.toFixed(6)} · {item.latency_ms}ms
                  </div>
                </div>
              ))}
              {usageItems.length === 0 && <div className="text-xs text-gray-500">暂无调用记录。</div>}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">任务执行表</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {summary.tasks.map((task) => (
              <div key={task.id} className="rounded-lg border bg-white p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium">{task.title}</div>
                  <Badge variant="secondary">{TASK_STATUS_LABELS[task.status] || task.status}</Badge>
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  {TASK_TYPE_LABELS[task.task_type] || task.task_type} · 负责人：
                  {task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"} · P{task.priority} C{task.complexity}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent 活动</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {summary.agents
              .filter((agent) => ["researcher", "engineer", "experimenter", "analyst", "writer"].includes(agent.type))
              .map((agent) => (
                <div key={agent.id} className="rounded-lg border bg-white p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium">{agent.name}</div>
                    <Badge variant="secondary">{AGENT_STATUS_LABELS[agent.status] || agent.status}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 break-words text-lg font-semibold text-gray-900">{value}</div>
    </div>
  )
}
