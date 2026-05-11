"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { FileUp, Play, RefreshCw, Trash2, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import { frontendLogger } from "@/lib/logger"
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
      if (preflight.warnings.length > 0) {
        setNotice(preflight.warnings.join("；"))
      } else {
        setNotice("系统可用性测试通过，正在创建运行。")
      }
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
    const confirmed = window.confirm(`确认删除运行 ${run.id}？相关任务、产出和事件记录都会从数据库移除。`)
    if (!confirmed) return
    try {
      await api.deleteRun(run.id)
      setRuns((current) => current.filter((item) => item.id !== run.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除运行失败")
    }
  }

  return (
    <div className="space-y-6">
      <Card className="border-slate-200 shadow-sm">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>创建研究任务</CardTitle>
              <CardDescription>输入研究目标，可附加 PDF、Markdown、文本、图片等材料。运行前会自动检查当前模型和解析能力。</CardDescription>
            </div>
            {mockMode !== null && <Badge variant={mockMode ? "secondary" : "default"}>{mockMode ? "Mock 模式" : "真实 LLM 模式"}</Badge>}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            className="min-h-[150px] w-full resize-y rounded-lg border border-slate-200 p-3 text-sm outline-none focus:ring-2 focus:ring-slate-900"
            placeholder={exampleGoal}
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
          />

          <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <FileUp className="size-4" />
                  多模态资料
                </div>
                <p className="mt-1 text-xs text-slate-500">PDF 会尽量提取为 Markdown 上下文；图片需要关闭 Mock 并配置支持多模态的模型。</p>
              </div>
              <label className="inline-flex cursor-pointer items-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
                添加附件
                <input className="hidden" type="file" multiple accept=".pdf,.md,.txt,.csv,.json,image/*,application/pdf,text/*" onChange={(event) => handleFiles(event.target.files)} />
              </label>
            </div>
            {attachments.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {attachments.map((file, index) => (
                  <span key={`${file.name}-${index}`} className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700">
                    {file.name}
                    <button type="button" onClick={() => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="text-slate-400 hover:text-slate-900">
                      <X className="size-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleSubmit} disabled={loading || !goal.trim()}>
              <Play className="size-4" />
              {loading ? "正在创建..." : "创建并运行"}
            </Button>
            <Button variant="ghost" type="button" onClick={() => setGoal(exampleGoal)}>
              使用示例目标
            </Button>
          </div>
          {notice && <div className="rounded-lg bg-sky-50 p-3 text-sm text-sky-700">{notice}</div>}
          {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        </CardContent>
      </Card>

      <Card className="border-slate-200 shadow-sm">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>最近运行</CardTitle>
              <CardDescription>点击进入运行详情。已结束或未启动的运行可以直接删除。</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={refreshRuns}>
              <RefreshCw className="size-3.5" />
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {runs.length === 0 && <div className="text-sm text-gray-500">还没有运行记录。</div>}
          {runs.slice(0, 10).map((run) => (
            <div key={run.id} className="flex items-center gap-2 rounded-lg border bg-white p-3 text-sm hover:bg-gray-50">
              <button onClick={() => router.push(`/runs/${run.id}`)} className="min-w-0 flex-1 text-left">
                <div className="font-medium text-gray-900">{run.id}</div>
                <div className="truncate text-gray-500">{primaryGoal(run.research_goal)}</div>
              </button>
              <Badge variant="secondary">{RUN_STATUS_LABELS[run.status] || run.status}</Badge>
              <Button variant="ghost" size="sm" disabled={!["created", "completed", "failed", "cancelled"].includes(run.status)} onClick={() => handleDelete(run)}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
