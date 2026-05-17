"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { runDisplayName } from "@/lib/run-display"
import {
  AGENT_STATUS_LABELS,
  RUN_STATUS_LABELS,
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
  type ApprovalRequest,
  type EvidenceAssessment,
  type EvidenceClaim,
  type EvidenceExcerpt,
  type EvidenceLink,
  type EvidenceSource,
  type ExperimentFinding,
  type ExperimentProtocol,
  type ExperimentResultRecord,
  type LLMUsage,
  type MemoryRecord,
  type ResearchClaim,
  type ResearchLoopSnapshot,
  type ReviewDecision,
  type RunEvent,
  type RunSummary,
  type TaskAttempt,
  type TaskGraph,
} from "@/lib/types"

const FINAL_STATUSES = new Set(["completed", "failed", "cancelled"])
const RESEARCH_CLAIM_STATUS_LABELS: Record<string, string> = {
  draft: "待验证",
  supported: "已支持",
  contested: "有争议",
  retracted: "已撤回",
}

export default function RunDetailPage() {
  const params = useParams<{ run_id: string }>()
  const router = useRouter()
  const runId = params.run_id
  const startedRef = useRef(false)
  const [summary, setSummary] = useState<RunSummary | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [usageItems, setUsageItems] = useState<LLMUsage[]>([])
  const [graph, setGraph] = useState<TaskGraph | null>(null)
  const [memory, setMemory] = useState<MemoryRecord[]>([])
  const [sources, setSources] = useState<EvidenceSource[]>([])
  const [claims, setClaims] = useState<EvidenceClaim[]>([])
  const [researchClaims, setResearchClaims] = useState<ResearchClaim[]>([])
  const [excerpts, setExcerpts] = useState<EvidenceExcerpt[]>([])
  const [assessments, setAssessments] = useState<EvidenceAssessment[]>([])
  const [links, setLinks] = useState<EvidenceLink[]>([])
  const [protocols, setProtocols] = useState<ExperimentProtocol[]>([])
  const [experimentResults, setExperimentResults] = useState<ExperimentResultRecord[]>([])
  const [experimentFindings, setExperimentFindings] = useState<ExperimentFinding[]>([])
  const [loopSnapshot, setLoopSnapshot] = useState<ResearchLoopSnapshot | null>(null)
  const [reviews, setReviews] = useState<ReviewDecision[]>([])
  const [attempts, setAttempts] = useState<TaskAttempt[]>([])
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [view, setView] = useState<"overview" | "workbench" | "evidence" | "audit">("overview")
  const [selectedEventIndex, setSelectedEventIndex] = useState(0)
  const [error, setError] = useState("")
  const [canceling, setCanceling] = useState(false)

  const refresh = useCallback(async () => {
    const [
      summaryData,
      eventsData,
      usageData,
      graphData,
      memoryData,
      evidenceData,
      researchStateData,
      researchLoopData,
      protocolData,
      experimentResultData,
      experimentFindingData,
      reviewData,
      attemptData,
      approvalData,
    ] = await Promise.all([
      api.getRunSummary(runId),
      api.getRunEvents(runId, 200),
      api.getRunUsage(runId),
      api.getRunGraph(runId),
      api.getRunMemory(runId),
      api.getRunEvidence(runId),
      api.getRunResearchState(runId),
      api.getRunResearchLoop(runId),
      api.getExperimentProtocols(runId),
      api.getExperimentResults(runId),
      api.getExperimentFindings(runId),
      api.getRunReviews(runId),
      api.getRunAttempts(runId),
      api.getRunApprovals(runId),
    ])
    setSummary(summaryData)
    setEvents(eventsData.events)
    setUsageItems(usageData.items)
    setGraph(graphData)
    setMemory(memoryData.items)
    setSources(evidenceData.sources)
    setClaims(evidenceData.claims)
    setResearchClaims(researchStateData.claims)
    setExcerpts(evidenceData.excerpts)
    setAssessments(evidenceData.assessments)
    setLinks(evidenceData.links)
    setLoopSnapshot(researchLoopData)
    setProtocols(protocolData.protocols)
    setExperimentResults(experimentResultData.results)
    setExperimentFindings(experimentFindingData.findings)
    setReviews(reviewData.items)
    setAttempts(attemptData.items)
    setApprovals(approvalData.items)
    setSelectedEventIndex((index) => Math.min(index, Math.max(eventsData.events.length - 1, 0)))
  }, [runId])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        await refresh()
        if (cancelled) return
        const current = await api.getRun(runId)
        if (current.run.status === "created" && !startedRef.current) {
          startedRef.current = true
          await api.startRun(runId)
        }
        setError("")
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败")
      }
    }
    load()
    const timer = window.setInterval(() => {
      setSummary((current) => {
        if (!current || FINAL_STATUSES.has(current.run.status)) return current
        refresh().catch(() => undefined)
        return current
      })
    }, 1500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refresh, runId])

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
    setCanceling(true)
    try {
      await api.cancelRun(summary.run.id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消失败")
    } finally {
      setCanceling(false)
    }
  }

  const handleApproval = async (request: ApprovalRequest, approved: boolean) => {
    await api.resolveApproval(request.id, approved)
    await refresh()
  }

  if (!summary) return <div className="page-stack text-sm text-[var(--rg-muted)]">正在加载运行详情...</div>

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
              <Button variant="outline" onClick={() => router.push(`/tasks?run_id=${summary.run.id}`)}>
                查看任务板
              </Button>
              <Button variant="destructive" onClick={handleCancel} disabled={FINAL_STATUSES.has(summary.run.status) || canceling}>
                {canceling ? "取消中..." : "停止运行"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 text-sm md:grid-cols-5">
          <Metric label="当前阶段" value={summary.run.current_step || "等待开始"} />
          <Metric label="任务总数" value={String(summary.counts.tasks_total)} />
          <Metric label="待确认" value={String(summary.counts.pending_approvals || 0)} />
          <Metric label="累计 Token" value={String(summary.usage.total_tokens || 0)} />
          <Metric label="累计成本 USD" value={(summary.usage.total_cost_usd || 0).toFixed(6)} />
        </CardContent>
      </Card>

      {error && <div className="error-banner p-3 text-sm">{error}</div>}
      <ApprovalPanel items={approvals} onResolve={handleApproval} />

      <div className="inline-flex w-fit rounded-xl border border-[var(--rg-hairline)] bg-white p-1">
        {[
          { key: "overview", label: "Overview" },
          { key: "workbench", label: "Workbench" },
          { key: "evidence", label: "Evidence & Report" },
          { key: "audit", label: "审计视图" },
        ].map((item) => (
          <button
            key={item.key}
            onClick={() => setView(item.key as typeof view)}
            className={`rounded-lg px-3 py-1.5 text-sm transition ${
              view === item.key ? "bg-[var(--rg-linear)] text-white" : "text-[var(--rg-body)] hover:bg-[var(--rg-surface-soft)]"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {view === "overview" && (
        <OverviewPanel
          summary={summary}
          researchClaims={researchClaims}
          loopSnapshot={loopSnapshot}
          approvals={approvals}
        />
      )}

      {view === "workbench" && (
        <>
          <TaskGraphPanel graph={graph} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TaskStatusPanel summary={summary} agentMap={agentMap} />
            <AttemptPanel attempts={attempts} />
          </div>
          <ExperimentProtocolPanel protocols={protocols} results={experimentResults} />
        </>
      )}

      {view === "evidence" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <ResearchTracePanel events={events} />
          <EvidenceWorkbenchPanel
            sources={sources}
            claims={claims}
            researchClaims={researchClaims}
            excerpts={excerpts}
            assessments={assessments}
            links={links}
          />
          <ExperimentFindingPanel findings={experimentFindings} results={experimentResults} />
          <MemoryPanel items={memory} />
          <ReviewPanel items={reviews} />
        </div>
      )}

      {view === "audit" && (
        <>
          <EventFlowGraph
            events={events}
            selectedIndex={selectedEventIndex}
            onSelect={setSelectedEventIndex}
            agentMap={agentMap}
            agentRoleMap={agentRoleMap}
          />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <TimelinePanel events={events} agentMap={agentMap} selectedIndex={selectedEventIndex} onSelect={setSelectedEventIndex} />
            <UsagePanel summary={summary} items={usageItems} />
          </div>
        </>
      )}

      <Card className="surface-card">
        <CardHeader>
          <CardTitle className="text-base">Agent 状态</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-2">
          {summary.agents
            .filter((agent) => ["researcher", "engineer", "experimenter", "analyst", "writer"].includes(agent.type))
            .map((agent) => (
              <div key={agent.id} className="data-row p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-medium">{agent.name}</div>
                  <Badge variant="secondary">{AGENT_STATUS_LABELS[agent.status] || agent.status}</Badge>
                </div>
                <div className="mt-1 text-xs text-[var(--rg-muted)]">
                  当前负载 {Math.round(agent.current_load * 100)}% · 当前任务 {agent.current_tasks?.length ? agent.current_tasks.join("、") : "暂无"}
                </div>
              </div>
            ))}
        </CardContent>
      </Card>
    </div>
  )
}

function ApprovalPanel({ items, onResolve }: { items: ApprovalRequest[]; onResolve: (item: ApprovalRequest, approved: boolean) => void }) {
  const pending = items.filter((item) => item.status === "pending")
  if (!pending.length) return null
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">待确认事项</CardTitle>
        <CardDescription>关键节点会在这里暂停，确认后继续执行。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {pending.map((item) => (
          <div key={item.id} className="data-row flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
            <div>
              <div className="font-medium">{item.title}</div>
              <div className="mt-1 text-[var(--rg-muted)]">{item.message}</div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => onResolve(item, false)}>
                拒绝
              </Button>
              <Button size="sm" onClick={() => onResolve(item, true)}>
                确认
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function OverviewPanel({
  summary,
  researchClaims,
  loopSnapshot,
  approvals,
}: {
  summary: RunSummary
  researchClaims: ResearchClaim[]
  loopSnapshot: ResearchLoopSnapshot | null
  approvals: ApprovalRequest[]
}) {
  const leadingClaim = researchClaims
    .slice()
    .sort((a, b) => b.confidence - a.confidence)[0]
  const pendingApproval = approvals.find((item) => item.status === "pending")
  const nextGap = loopSnapshot?.gaps[0]
  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
      <Card className="surface-card">
        <CardHeader>
          <CardTitle className="text-base">当前研究判断</CardTitle>
          <CardDescription>{summary.run.research_goal}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Metric label="当前阶段" value={loopSnapshot?.phase || summary.run.current_step || "待评估"} />
          <div className="data-row p-3 text-sm">
            <div className="text-xs text-[var(--rg-muted)]">关键结论</div>
            <div className="mt-1 font-medium">{leadingClaim?.statement || "尚未形成关键结论"}</div>
            <div className="mt-2 text-xs text-[var(--rg-muted)]">
              状态：{leadingClaim ? RESEARCH_CLAIM_STATUS_LABELS[leadingClaim.status] || leadingClaim.status : "待生成"}
              {leadingClaim ? ` · 置信度 ${Math.round(leadingClaim.confidence * 100)}%` : ""}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="surface-card">
        <CardHeader>
          <CardTitle className="text-base">下一步与用户介入</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="data-row p-3">
            <div className="text-xs text-[var(--rg-muted)]">最大不确定性 / 下一步</div>
            <div className="mt-1 font-medium">{nextGap?.reason || loopSnapshot?.stop_reason || "当前没有新的显式缺口"}</div>
          </div>
          <div className="data-row p-3">
            <div className="text-xs text-[var(--rg-muted)]">需要你确认</div>
            <div className="mt-1 font-medium">{pendingApproval?.title || "暂无待确认事项"}</div>
            {pendingApproval && <div className="mt-2 text-xs text-[var(--rg-muted)]">{pendingApproval.message}</div>}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function ExperimentProtocolPanel({
  protocols,
  results,
}: {
  protocols: ExperimentProtocol[]
  results: ExperimentResultRecord[]
}) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">实验协议</CardTitle>
        <CardDescription>从 hypothesis 显式落到协议、指标、基线与结果。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {protocols.length === 0 && <div className="text-sm text-[var(--rg-muted)]">尚未生成实验协议。</div>}
        {protocols.map((protocol) => {
          const relatedResults = results.filter((item) => item.protocol_id === protocol.id)
          return (
            <div key={protocol.id} className="data-row p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{protocol.title}</div>
                <Badge variant="secondary">{protocol.status}</Badge>
              </div>
              <div className="mt-2 text-xs text-[var(--rg-muted)]">
                指标：{protocol.metrics.map((item) => item.name).join(" / ")} · 基线：{protocol.baselines.map((item) => item.name).join(" / ")}
              </div>
              <div className="mt-2 text-xs text-[var(--rg-muted)]">
                结果：{relatedResults[0]?.summary || "尚未执行"}
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function ExperimentFindingPanel({
  findings,
  results,
}: {
  findings: ExperimentFinding[]
  results: ExperimentResultRecord[]
}) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">实验 finding</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {findings.length === 0 && <div className="text-sm text-[var(--rg-muted)]">尚未形成实验 finding。</div>}
        {findings.map((finding) => {
          const result = results.find((item) => item.id === finding.result_id)
          return (
            <div key={finding.id} className="data-row p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="font-medium">{finding.statement}</div>
                <Badge variant="secondary">{finding.relation_type}</Badge>
              </div>
              <div className="mt-1 text-xs text-[var(--rg-muted)]">
                置信度 {Math.round(finding.confidence * 100)}% · {result?.summary || "无结果摘要"}
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function TaskGraphPanel({ graph }: { graph: TaskGraph | null }) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">任务依赖图</CardTitle>
        <CardDescription>展示 DAG、关键路径和当前可执行任务。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!graph && <div className="text-sm text-[var(--rg-muted)]">暂无任务图。</div>}
        {graph?.nodes.map((task) => {
          const deps = graph.edges.filter((edge) => edge.task_id === task.id)
          return (
            <div key={task.id} className="data-row p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{task.title}</div>
                <div className="flex gap-2">
                  {task.is_critical_path && <Badge variant="secondary">关键路径</Badge>}
                  <Badge variant="secondary">{TASK_STATUS_LABELS[task.status] || task.status}</Badge>
                </div>
              </div>
              <div className="mt-1 text-xs text-[var(--rg-muted)]">
                前置依赖：{deps.length ? deps.map((item) => item.depends_on_task_id).join("、") : "无"} · {graph.ready_task_ids.includes(task.id) ? "可执行" : "等待"}
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function TaskStatusPanel({ summary, agentMap }: { summary: RunSummary; agentMap: Record<string, string> }) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">任务管理</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {summary.tasks.map((task) => (
          <div key={task.id} className="data-row p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{task.title}</div>
              <Badge variant="secondary">{TASK_STATUS_LABELS[task.status] || task.status}</Badge>
            </div>
            <div className="mt-1 text-xs text-[var(--rg-muted)]">
              {TASK_TYPE_LABELS[task.task_type] || task.task_type} · 负责人 {task.owner_agent ? agentMap[task.owner_agent] || task.owner_agent : "未分配"} · 尝试 {task.attempt_count}
            </div>
            {task.blocked_reason && <div className="mt-2 text-xs text-[#964b36]">{task.blocked_reason}</div>}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function AttemptPanel({ attempts }: { attempts: TaskAttempt[] }) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">失败恢复</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {attempts.length === 0 && <div className="text-sm text-[var(--rg-muted)]">暂无尝试记录。</div>}
        {attempts.map((item) => (
          <div key={item.id} className="data-row p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="font-medium">{item.task_id} · 第 {item.attempt_number} 次</div>
              <Badge variant="secondary">{item.status}</Badge>
            </div>
            <div className="mt-1 text-xs text-[var(--rg-muted)]">{item.failure_message || item.checkpoint || "执行完成"}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function MemoryPanel({ items }: { items: MemoryRecord[] }) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">研究记忆</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 && <div className="text-sm text-[var(--rg-muted)]">暂无结构化记忆。</div>}
        {items.map((item) => (
          <div key={item.id} className="data-row p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="font-medium">{item.category}</div>
              <Badge variant="secondary">{item.scope}</Badge>
            </div>
            <div className="mt-1 leading-6 text-[var(--rg-body)]">{item.summary}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function ReviewPanel({ items }: { items: ReviewDecision[] }) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">导师质量门禁</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 && <div className="text-sm text-[var(--rg-muted)]">暂无审核结果。</div>}
        {items.map((item) => (
          <div key={item.id} className="data-row p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="font-medium">{item.task_id}</div>
              <Badge variant="secondary">{item.approved ? "通过" : "返工"}</Badge>
            </div>
            <div className="mt-1 text-xs text-[var(--rg-muted)]">
              {Object.entries(item.scores)
                .map(([key, value]) => `${key} ${Math.round(value * 100)}%`)
                .join(" · ")}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function ResearchTracePanel({ events }: { events: RunEvent[] }) {
  const traces = events
    .filter((event) => event.event_type === "evidence.search.completed" || event.event_type === "evidence.verification.completed")
    .slice()
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  return (
    <Card className="surface-card lg:col-span-3">
      <CardHeader>
        <CardTitle className="text-base">调研轨迹</CardTitle>
        <CardDescription>查看研究生围绕原始课题实际查了什么、哪些来源返回了结果、哪些候选在核验阶段被剔除。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {traces.length === 0 && <div className="text-sm text-[var(--rg-muted)]">暂无可展示的调研轨迹。</div>}
        {traces.map((event) => {
          const query = typeof event.payload.query === "string" ? event.payload.query : ""
          const attempts = Array.isArray(event.payload.attempts) ? event.payload.attempts : []
          const candidateCount = typeof event.payload.candidate_count === "number" ? event.payload.candidate_count : null
          const acceptedCount = typeof event.payload.accepted_count === "number" ? event.payload.accepted_count : null
          const rejectedCount = typeof event.payload.rejected_count === "number" ? event.payload.rejected_count : null
          const browserDiscovered = typeof event.payload.browser_discovered === "number" ? event.payload.browser_discovered : null

          return (
            <div key={event.id} className="data-row p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{event.title}</div>
                <Badge variant="secondary">{event.created_at}</Badge>
              </div>
              {query && <div className="mt-2 rounded-lg bg-[var(--rg-surface-soft)] px-3 py-2 text-xs">检索式：{query}</div>}
              {event.event_type === "evidence.search.completed" && (
                <div className="mt-3 space-y-2">
                  <div className="text-xs text-[var(--rg-muted)]">
                    候选来源 {candidateCount ?? 0} 条{browserDiscovered !== null ? ` / 浏览器额外发现 ${browserDiscovered} 条` : ""}
                  </div>
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                    {attempts.map((item, index) => {
                      const attempt = item as Record<string, unknown>
                      const provider = typeof attempt.provider === "string" ? attempt.provider : `provider-${index + 1}`
                      const enabled = Boolean(attempt.enabled)
                      const resultCount = typeof attempt.result_count === "number" ? attempt.result_count : 0
                      const error = typeof attempt.error === "string" ? attempt.error : ""
                      return (
                        <div key={`${provider}-${index}`} className="rounded-lg border border-[var(--rg-hairline)] bg-white p-3 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-medium">{provider}</div>
                            <Badge variant="secondary">{enabled ? "已启用" : "未启用"}</Badge>
                          </div>
                          <div className="mt-2 text-[var(--rg-muted)]">返回 {resultCount} 条</div>
                          {error && <div className="mt-1 text-[#964b36]">{error}</div>}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              {event.event_type === "evidence.verification.completed" && (
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <Badge variant="secondary">候选 {candidateCount ?? 0}</Badge>
                  <Badge variant="secondary">保留 {acceptedCount ?? 0}</Badge>
                  <Badge variant="secondary">剔除 {rejectedCount ?? 0}</Badge>
                </div>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function TimelinePanel({
  events,
  agentMap,
  selectedIndex,
  onSelect,
}: {
  events: RunEvent[]
  agentMap: Record<string, string>
  selectedIndex: number
  onSelect: (index: number) => void
}) {
  const orderedEvents = events.slice().sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  return (
    <Card className="surface-card lg:col-span-2">
      <CardHeader>
        <CardTitle className="text-base">事件时间线</CardTitle>
      </CardHeader>
      <CardContent className="max-h-[520px] space-y-3 overflow-auto">
        {orderedEvents
          .slice()
          .reverse()
          .map((event, reverseIndex) => {
            const index = orderedEvents.length - 1 - reverseIndex
            return (
            <button
              key={event.id}
              onClick={() => onSelect(index)}
              className={`data-row w-full p-3 text-left text-sm transition ${
                index === selectedIndex ? "border-[#cfd3ff] bg-[#eef0ff]" : ""
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{event.title}</div>
                <Badge variant="secondary">{event.phase}</Badge>
              </div>
              <div className="mt-1 text-[var(--rg-body)]">{event.message}</div>
              <div className="mt-2 text-xs text-[var(--rg-muted)]">
                {event.created_at}
                {event.agent_id ? ` · ${agentMap[event.agent_id] || event.agent_id}` : ""}
              </div>
            </button>
          )})}
      </CardContent>
    </Card>
  )
}

function UsagePanel({ summary, items }: { summary: RunSummary; items: LLMUsage[] }) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">成本监测</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <Metric label="LLM 调用次数" value={String(summary.usage.total_llm_calls || 0)} />
        <Metric label="失败调用" value={String(summary.usage.failed_llm_calls || 0)} />
        <Separator />
        <div className="max-h-[260px] space-y-2 overflow-auto">
          {items.map((item) => (
            <div key={item.id} className="rounded-lg bg-[var(--rg-surface-soft)] p-2 text-xs">
              <div className="font-medium">{item.role} · {item.model}</div>
              <div className="text-[var(--rg-muted)]">{item.total_tokens} tokens · ${item.cost_usd.toFixed(6)} · {item.latency_ms}ms</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
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
  const orderedEvents = useMemo(() => events.slice().sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()), [events])
  const selected = orderedEvents[selectedIndex] || orderedEvents[0]
  const relation = selected ? inferRelation(selected, agentMap, agentRoleMap) : null
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">事件关系图</CardTitle>
        <CardDescription>点击节点查看不同时间点上的协作关系。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!selected || !relation ? (
          <div className="text-sm text-[var(--rg-muted)]">暂无事件。</div>
        ) : (
          <>
            <div className="flex gap-2 overflow-x-auto">
              {orderedEvents.map((event, index) => (
                <button
                  key={event.id}
                  onClick={() => onSelect(index)}
                  className={`rounded-full border px-3 py-1.5 text-xs ${
                    index === selectedIndex ? "border-[var(--rg-linear)] bg-[#eef0ff] text-[#3b4395]" : "border-[var(--rg-hairline)] bg-white"
                  }`}
                >
                  {index + 1}. {event.phase}
                </button>
              ))}
            </div>
            <div className="grid gap-3 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
              <ActorNode title={relation.source} subtitle={relation.sourceRole} />
              <div className="rounded-full border border-[var(--rg-hairline)] px-3 py-1 text-center text-xs">{relation.action}</div>
              <ActorNode title={relation.target} subtitle={relation.targetRole} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function ActorNode({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="rounded-xl border border-[var(--rg-hairline)] bg-[var(--rg-surface-soft)] p-4">
      <div className="text-xs text-[var(--rg-muted)]">{subtitle}</div>
      <div className="mt-2 text-lg font-semibold">{title}</div>
    </div>
  )
}

function inferRelation(event: RunEvent, agentMap: Record<string, string>, agentRoleMap: Record<string, string>) {
  const actor = event.agent_id ? agentMap[event.agent_id] || event.agent_id : "系统"
  const role = event.agent_id ? agentRoleMap[event.agent_id] || "agent" : "system"
  if (event.subagent_id) return { source: actor, sourceRole: role, action: "委派", target: event.subagent_id, targetRole: "subagent" }
  if (event.phase === "review") return { source: actor || "研究生", sourceRole: role, action: "提交审核", target: "导师 Agent", targetRole: "advisor" }
  if (event.phase === "approval") return { source: "系统", sourceRole: "system", action: "等待确认", target: actor, targetRole: role }
  return { source: actor, sourceRole: role, action: "推进任务", target: event.task_id || "任务板", targetRole: "task" }
}

function EvidenceWorkbenchPanel({
  sources,
  claims,
  researchClaims,
  excerpts,
  assessments,
  links,
}: {
  sources: EvidenceSource[]
  claims: EvidenceClaim[]
  researchClaims: ResearchClaim[]
  excerpts: EvidenceExcerpt[]
  assessments: EvidenceAssessment[]
  links: EvidenceLink[]
}) {
  return (
    <Card className="surface-card">
      <CardHeader>
        <CardTitle className="text-base">证据工作台</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {researchClaims.map((claim) => {
          const claimLinks = links.filter((item) => item.claim_id === claim.id)
          const supporting = claimLinks.filter((item) => item.relation_type === "supports").length
          const opposing = claimLinks.filter((item) => item.relation_type === "opposes").length
          const hasGap = claimLinks.length === 0
          return (
            <div key={claim.id} className="data-row p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="font-medium">{claim.statement}</div>
                <Badge variant="secondary">{RESEARCH_CLAIM_STATUS_LABELS[claim.status] || claim.status}</Badge>
              </div>
              <div className="mt-1 text-xs text-[var(--rg-muted)]">
                支持 {supporting} / 反驳 {opposing} / 置信度 {Math.round(claim.confidence * 100)}%
              </div>
              {hasGap && <div className="mt-2 text-xs text-[#964b36]">当前还没有绑定证据，结论暂不可采信。</div>}
            </div>
          )
        })}
        {sources.length === 0 && <div className="text-sm text-[var(--rg-muted)]">暂无证据来源。</div>}
        {sources.map((source) => (
          <div key={source.id} className="data-row p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{source.title}</div>
              <div className="flex flex-wrap gap-2">
                {typeof source.metadata.provider === "string" && <Badge variant="secondary">{source.metadata.provider}</Badge>}
                {source.metadata.browser_verification &&
                  typeof source.metadata.browser_verification === "object" &&
                  !Array.isArray(source.metadata.browser_verification) && (
                    <Badge variant="secondary">
                      {(source.metadata.browser_verification as Record<string, unknown>).accepted ? "浏览器已核验" : "待进一步核验"}
                    </Badge>
                  )}
              </div>
            </div>
            <div className="mt-1 text-xs text-[var(--rg-muted)]">
              {source.authors} {source.year ? `(${source.year})` : ""} / {claims.filter((item) => item.source_id === source.id).length} 条抽取主张 / {excerpts.filter((item) => item.source_id === source.id).length} 条摘录
            </div>
            {(source.doi || source.url) && (
              <div className="mt-1 break-all text-xs text-[var(--rg-muted)]">
                {source.doi ? `DOI ${source.doi}` : source.url}
              </div>
            )}
            {assessments
              .filter((item) => item.source_id === source.id)
              .slice(0, 1)
              .map((item) => (
                <div key={item.id} className="mt-2 text-xs text-[var(--rg-muted)]">
                  评分 {Math.round(item.overall_score * 100)}% / 一手来源 {item.is_primary ? "是" : "否"} / 同行评审 {item.is_peer_reviewed ? "是" : "否"}
                </div>
              ))}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <div className="text-xs text-[var(--rg-muted)]">{label}</div>
      <div className="mt-1 break-words text-lg font-semibold text-[var(--rg-ink)]">{value}</div>
    </div>
  )
}
