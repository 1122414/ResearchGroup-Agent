"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Activity, Clock3, FileUp, Paperclip, Play, RefreshCw, Sparkles, Trash2, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import { frontendLogger } from "@/lib/logger"
import { runDisplayName } from "@/lib/run-display"
import { RUN_STATUS_LABELS, type Run } from "@/lib/types"

type UploadAttachment = {
  name: string
  mime_type: string
  size: number
  data_url: string
}

function primaryGoal(goal: string) {
  return goal.split("## 用户上传的多模态附件上下文", 1)[0].trim()
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ""))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function formatTime(value?: string | null) {
  if (!value) return "尚未开始"
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function HomePage() {
  const router = useRouter()
  const [goal, setGoal] = useState("")
  const [runs, setRuns] = useState<Run[]>([])
  const [attachments, setAttachments] = useState<UploadAttachment[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [mockMode, setMockMode] = useState<boolean | null>(null)

  const exampleGoal = "调研 ima 和 Obsidian 的区别、作用和适用场景，并输出一份可直接阅读的最终研究报告。"

  const refreshRuns = () => api.getRuns().then(({ runs }) => setRuns(runs)).catch(() => setRuns([]))

  useEffect(() => {
    frontendLogger.info("HomePage mounted")
    api.health().then((data) => setMockMode(data.mock_mode)).catch(() => setMockMode(null))
    refreshRuns()
  }, [])

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return
    setError("")
    try {
      const next = await Promise.all(
        Array.from(files).map(async (file) => ({
          name: file.name,
          mime_type: file.type || "application/octet-stream",
          size: file.size,
          data_url: await readFileAsDataUrl(file),
        })),
      )
      setAttachments((current) => [...current, ...next])
      setNotice(`已添加 ${next.length} 个附件，运行前会先做可用性测试。`)
    } catch {
      setError("读取附件失败，请重新选择文件。")
    }
  }

  const handleSubmit = async () => {
    if (!goal.trim()) return
    setLoading(true)
    setError("")
    setNotice("正在进行系统可用性测试...")
    frontendLogger.info(`HomePage handleSubmit | goal=${goal.trim().substring(0, 60)}`)
    try {
      const preflight = await api.preflightRun(goal.trim(), attachments)
      if (!preflight.ok) {
        setError(preflight.errors.join("；"))
        return
      }
      setNotice(
        preflight.warnings.length > 0
          ? preflight.warnings.join("；")
          : "系统可用性测试通过，正在创建运行。",
      )
      const { run_id } = await api.createRun(goal.trim(), attachments)
      frontendLogger.setRunId(run_id)
      await api.startRun(run_id)
      await refreshRuns()
      router.push(`/runs/${run_id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : "创建运行失败"
      frontendLogger.error(`HomePage handleSubmit failed | error=${msg}`)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (run: Run) => {
    const confirmed = window.confirm(`确认删除运行 ${runDisplayName(run)}？相关任务、产出和事件记录都会从数据库移除。`)
    if (!confirmed) return
    try {
      await api.deleteRun(run.id)
      setRuns((current) => current.filter((item) => item.id !== run.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除运行失败")
    }
  }

  const latestRun = runs[0]
  const activeRuns = runs.filter((run) => !["completed", "failed", "cancelled"].includes(run.status)).length

  return (
    <div className="page-stack">
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="page-hero min-h-[260px]">
          <div className="eyebrow">
            <Sparkles className="size-3.5" />
            Multi-agent research studio
          </div>
          <h1 className="page-title max-w-4xl">把一个研究目标交给导师 Agent，让课题组协作跑完拆解、执行、审核和报告。</h1>
          <p className="page-copy">
            面向研究生课题组协作的任务工作台。系统会先做可用性预检查，再由导师 Agent 拆解任务、调度研究生 Agent，并把阶段产出沉淀为最终 Markdown 报告。
          </p>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <HeroMetric label="运行记录" value={String(runs.length)} />
            <HeroMetric label="活跃运行" value={String(activeRuns)} />
            <HeroMetric label="模型模式" value={mockMode === null ? "检测中" : mockMode ? "Mock" : "LLM"} />
          </div>
        </div>

        <div className="dark-panel p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-medium uppercase tracking-wider text-white/45">Latest run</div>
              <div className="mt-1 text-lg font-semibold">{latestRun ? RUN_STATUS_LABELS[latestRun.status] || latestRun.status : "等待创建"}</div>
            </div>
            <Activity className="size-5 text-[var(--rg-linear)]" />
          </div>
          <div className="mt-5 rounded-lg border border-white/10 bg-white/[0.03] p-3">
            <div className="line-clamp-3 text-sm leading-6 text-white/78">
              {latestRun ? primaryGoal(latestRun.research_goal) : "输入一个研究目标后，这里会显示最近运行的摘要与状态。"}
            </div>
            <div className="mt-4 flex items-center gap-2 text-xs text-white/45">
              <Clock3 className="size-3.5" />
              {latestRun ? formatTime(latestRun.created_at) : "暂无时间线"}
            </div>
          </div>
          <Button
            className="mt-4 w-full bg-[var(--rg-linear)] text-white hover:bg-[#828fff]"
            disabled={!latestRun}
            onClick={() => latestRun && router.push(`/runs/${latestRun.id}`)}
          >
            查看最近运行
          </Button>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="surface-card">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle>创建研究任务</CardTitle>
                <CardDescription>填写研究目标，可附加 PDF、Markdown、文本、CSV、JSON 或图片资料。</CardDescription>
              </div>
              {mockMode !== null && (
                <Badge variant={mockMode ? "secondary" : "default"}>{mockMode ? "Mock 模式" : "真实 LLM 模式"}</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <textarea
              className="control-input min-h-[172px] w-full resize-y p-3 text-sm leading-6"
              placeholder={exampleGoal}
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
            />

            <div className="soft-card p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-[var(--rg-ink)]">
                    <FileUp className="size-4 text-[var(--rg-coral)]" />
                    多模态资料
                  </div>
                  <p className="mt-1 text-xs leading-5 text-[var(--rg-muted)]">
                    PDF 会尽量提取为 Markdown 上下文；图片需要关闭 Mock 并配置支持多模态的模型。
                  </p>
                </div>
                <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-[var(--rg-hairline)] bg-white px-3 text-sm font-medium text-[var(--rg-ink)] shadow-sm hover:bg-[var(--rg-surface-soft)]">
                  <Paperclip className="size-4" />
                  添加附件
                  <input className="hidden" type="file" multiple accept=".pdf,.md,.txt,.csv,.json,image/*,application/pdf,text/*" onChange={(event) => handleFiles(event.target.files)} />
                </label>
              </div>
              {attachments.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {attachments.map((file, index) => (
                    <span key={`${file.name}-${index}`} className="inline-flex items-center gap-2 rounded-full border border-[var(--rg-hairline)] bg-white px-3 py-1 text-xs text-[var(--rg-body)]">
                      {file.name}
                      <button type="button" onClick={() => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="text-[var(--rg-muted)] hover:text-[var(--rg-ink)]">
                        <X className="size-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={handleSubmit} disabled={loading || !goal.trim()} className="bg-[var(--rg-linear)] text-white hover:bg-[#828fff]">
                <Play className="size-4" />
                {loading ? "正在创建..." : "创建并运行"}
              </Button>
              <Button variant="ghost" type="button" onClick={() => setGoal(exampleGoal)}>
                使用示例目标
              </Button>
            </div>
            {notice && <div className="info-banner p-3 text-sm">{notice}</div>}
            {error && <div className="error-banner p-3 text-sm">{error}</div>}
          </CardContent>
        </Card>

        <Card className="surface-card">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle>最近运行</CardTitle>
                <CardDescription>快速回到运行详情，或清理已结束的记录。</CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={refreshRuns}>
                <RefreshCw className="size-3.5" />
                刷新
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {runs.length === 0 && <div className="soft-card p-5 text-center text-sm text-[var(--rg-muted)]">还没有运行记录。</div>}
            {runs.slice(0, 10).map((run, index) => (
              <div key={run.id} className="data-row flex items-center gap-2 p-3 text-sm">
                <button onClick={() => router.push(`/runs/${run.id}`)} className="min-w-0 flex-1 text-left">
                  <div className="font-medium text-[var(--rg-ink)]">{runDisplayName(run, index)}</div>
                  <div className="mt-0.5 truncate text-[var(--rg-muted)]">{primaryGoal(run.research_goal)}</div>
                </button>
                <Badge variant="secondary">{RUN_STATUS_LABELS[run.status] || run.status}</Badge>
                <Button variant="ghost" size="icon-sm" disabled={!["created", "completed", "failed", "cancelled"].includes(run.status)} onClick={() => handleDelete(run)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>
    </div>
  )
}

function HeroMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <div className="text-xs text-[var(--rg-muted)]">{label}</div>
      <div className="mt-1 text-xl font-semibold text-[var(--rg-ink)]">{value}</div>
    </div>
  )
}
