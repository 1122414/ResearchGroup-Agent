"use client"

import { Fragment, Suspense, useEffect, useMemo, useState, type ReactNode } from "react"
import { useSearchParams } from "next/navigation"
import { Download, FileText, Filter, FolderOpen, ListChecks } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import { runDisplayName } from "@/lib/run-display"
import { OUTPUT_TYPE_LABELS, RUN_STATUS_LABELS, type Output, type Run, type Task } from "@/lib/types"

function primaryGoal(goal: string) {
  return goal.split("## 用户上传的多模态附件上下文", 1)[0].trim()
}

function formatRunName(run: Run, index: number) {
  return runDisplayName(run, index)
}

function taskName(task: Task, index: number) {
  return `任务 ${String(index + 1).padStart(2, "0")} · ${task.title}`
}

function safeFilename(text: string) {
  return primaryGoal(text)
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 80) || "research-report"
}

function safeRunFilename(run: Run) {
  return (run.display_name || safeFilename(run.research_goal)).replace(/[\\/:*?"<>|]+/g, "-")
}

function downloadMarkdown(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename.endsWith(".md") ? filename : `${filename}.md`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export default function OutputsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm text-[var(--rg-muted)]">正在加载输出...</div>}>
      <OutputsContent />
    </Suspense>
  )
}

function OutputsContent() {
  const searchParams = useSearchParams()
  const queryRunId = searchParams.get("run_id")
  const [outputs, setOutputs] = useState<Output[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(queryRunId)
  const [selectedTaskId, setSelectedTaskId] = useState<string | "">("")
  const [selectedType, setSelectedType] = useState<string | "">("")

  useEffect(() => {
    api.getRuns().then(({ runs }) => {
      setRuns(runs)
      const queryExists = queryRunId && runs.some((run) => run.id === queryRunId)
      setSelectedRun(queryExists ? queryRunId : runs[0]?.id || null)
    })
  }, [queryRunId])

  useEffect(() => {
    if (!selectedRun) {
      queueMicrotask(() => {
        setOutputs([])
        setTasks([])
      })
      return
    }
    let cancelled = false
    Promise.all([api.getOutputs(selectedRun), api.getTasks(selectedRun)]).then(([{ outputs }, { tasks }]) => {
      if (cancelled) return
      setOutputs(outputs)
      setTasks(tasks)
    })
    return () => {
      cancelled = true
    }
  }, [selectedRun])

  const taskMap = useMemo(() => {
    return Object.fromEntries(tasks.map((task, index) => [task.id, { task, label: taskName(task, index) }]))
  }, [tasks])

  const selectedRunData = runs.find((run) => run.id === selectedRun) || null
  const outputTypes = useMemo(() => Array.from(new Set(outputs.map((o) => o.output_type))), [outputs])

  const filteredOutputs = useMemo(() => {
    return outputs.filter((output) => {
      if (selectedTaskId && output.task_id !== selectedTaskId) return false
      if (selectedType && output.output_type !== selectedType) return false
      return true
    })
  }, [outputs, selectedTaskId, selectedType])

  const finalReport = filteredOutputs.find((output) => output.output_type === "final_report")
  const otherOutputs = filteredOutputs.filter((output) => output.output_type !== "final_report")

  return (
    <div className="page-stack">
      <div className="page-hero">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="eyebrow">
              <FolderOpen className="size-4" />
              Research artifacts
            </div>
            <h2 className="page-title">输出中心</h2>
            <p className="page-copy">查看任务产出、写作初稿、导师审核汇总和最终 Markdown 报告。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={selectedRun || ""}
              onChange={(event) => {
                setSelectedRun(event.target.value)
                setSelectedTaskId("")
                setSelectedType("")
              }}
              className="control-input h-9 min-w-[320px] px-3 text-sm"
            >
              {runs.map((run, index) => (
                <option key={run.id} value={run.id}>
                  {formatRunName(run, index)} ({RUN_STATUS_LABELS[run.status] || run.status})
                </option>
              ))}
            </select>
            {finalReport && selectedRunData && (
              <Button size="sm" onClick={() => downloadMarkdown(`${safeRunFilename(selectedRunData)}.md`, finalReport.content)}>
                <Download className="size-3.5" />
                下载 Markdown
              </Button>
            )}
          </div>
        </div>

        {selectedRunData && (
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="运行状态" value={RUN_STATUS_LABELS[selectedRunData.status] || selectedRunData.status} />
            <Metric label="任务数" value={String(tasks.length)} />
            <Metric label="产出数" value={String(outputs.length)} />
            <Metric label="最终报告" value={finalReport ? "已生成" : "未生成"} />
          </div>
        )}
      </div>

      {selectedRun && (
        <div className="surface-card flex flex-wrap items-center gap-3 p-3">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--rg-muted)]">
            <Filter className="size-4" />
            筛选
          </div>
          <select value={selectedTaskId} onChange={(event) => setSelectedTaskId(event.target.value)} className="control-input h-9 min-w-[260px] px-3 text-sm">
            <option value="">全部任务</option>
            {tasks.map((task, index) => (
              <option key={task.id} value={task.id}>
                {taskName(task, index)}
              </option>
            ))}
          </select>
          <select value={selectedType} onChange={(event) => setSelectedType(event.target.value)} className="control-input h-9 min-w-[180px] px-3 text-sm">
            <option value="">全部类型</option>
            {outputTypes.map((type) => (
              <option key={type} value={type}>
                {OUTPUT_TYPE_LABELS[type] || type}
              </option>
            ))}
          </select>
          {(selectedTaskId || selectedType) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSelectedTaskId("")
                setSelectedType("")
              }}
            >
              清空筛选
            </Button>
          )}
        </div>
      )}

      {finalReport && (
        <Card className="surface-card">
          <CardHeader className="border-b border-[var(--rg-hairline)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-lg">
                <FileText className="size-5 text-[var(--rg-coral)]" />
                {finalReport.title}
              </CardTitle>
              {selectedRunData && (
                <Button variant="outline" size="sm" onClick={() => downloadMarkdown(`${safeRunFilename(selectedRunData)}.md`, finalReport.content)}>
                  <Download className="size-3.5" />
                  下载 .md
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="pt-5">
            <MarkdownArticle content={finalReport.content} />
          </CardContent>
        </Card>
      )}

      <section className="space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-[var(--rg-body)]">
          <ListChecks className="size-4" />
          过程产出
          <Badge variant="secondary">{otherOutputs.length}</Badge>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {otherOutputs.map((output) => (
            <OutputCard key={output.id} output={output} taskLabel={output.task_id ? taskMap[output.task_id]?.label : undefined} />
          ))}
        </div>
      </section>

      {selectedRun && filteredOutputs.length === 0 && (
        <div className="surface-card border-dashed p-8 text-center text-sm text-[var(--rg-muted)]">
          当前筛选下还没有产出。运行完成后会在这里展示 Markdown 报告和过程文件。
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <div className="text-xs text-[var(--rg-muted)]">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-[var(--rg-ink)]">{value}</div>
    </div>
  )
}

function MarkdownArticle({ content }: { content: string }) {
  return (
    <article className="max-h-[680px] overflow-auto rounded-lg border border-[var(--rg-hairline)] bg-[#fffdf8] px-6 py-5 text-[var(--rg-body)] shadow-inner">
      {renderMarkdown(content)}
    </article>
  )
}

function renderMarkdown(content: string) {
  const blocks: ReactNode[] = []
  const lines = normalizeMarkdownTables(content).replace(/\r\n/g, "\n").split("\n")
  let paragraph: string[] = []
  let list: string[] = []
  let table: string[] = []
  let code: string[] | null = null

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(
      <p key={`p-${blocks.length}`} className="my-3 leading-8 text-[var(--rg-body)]">
        {renderInline(paragraph.join(" "))}
      </p>,
    )
    paragraph = []
  }

  const flushTable = () => {
    if (table.length < 2) {
      if (table.length) paragraph.push(...table)
      table = []
      return
    }
    const rows = table.map(parseTableRow).filter((row) => row.length > 0)
    const separatorIndex = rows.findIndex((row) => row.every((cell) => /^:?-{3,}:?$/.test(cell)))
    if (separatorIndex < 1 || rows.length <= separatorIndex + 1) {
      paragraph.push(...table)
      table = []
      return
    }
    const headers = rows[separatorIndex - 1]
    const bodyRows = rows.slice(separatorIndex + 1).filter((row) => row.some(Boolean))
    blocks.push(
      <div key={`table-${blocks.length}`} className="my-4 overflow-x-auto rounded-lg border border-[var(--rg-hairline)]">
        <table className="min-w-full border-collapse text-left text-sm">
          <thead className="bg-[var(--rg-surface-soft)] text-[var(--rg-ink)]">
            <tr>
              {headers.map((header, index) => (
                <th key={index} className="border-b border-[var(--rg-hairline)] px-3 py-2 font-semibold">
                  {renderInline(header)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, rowIndex) => (
              <tr key={rowIndex} className="odd:bg-white even:bg-[var(--rg-surface-soft)]/45">
                {headers.map((_, cellIndex) => (
                  <td key={cellIndex} className="border-t border-[var(--rg-hairline)] px-3 py-2 align-top leading-6">
                    {renderInline(row[cellIndex] || "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    )
    table = []
  }

  const flushList = () => {
    if (!list.length) return
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-3 list-disc space-y-2 pl-6 text-[var(--rg-body)]">
        {list.map((item, index) => (
          <li key={index}>{renderInline(item)}</li>
        ))}
      </ul>,
    )
    list = []
  }

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (code) {
        blocks.push(
          <pre key={`code-${blocks.length}`} className="code-panel my-4 overflow-auto p-4 text-xs leading-6">
            {code.join("\n")}
          </pre>,
        )
        code = null
      } else {
        flushParagraph()
        flushList()
        flushTable()
        code = []
      }
      return
    }

    if (code) {
      code.push(line)
      return
    }

    const trimmed = line.trim()
    if (!trimmed) {
      flushParagraph()
      flushList()
      flushTable()
      return
    }

    if (isTableLine(trimmed)) {
      flushParagraph()
      flushList()
      table.push(trimmed)
      return
    }

    if (trimmed === "---") {
      flushParagraph()
      flushList()
      flushTable()
      blocks.push(<hr key={`hr-${blocks.length}`} className="my-5 border-[var(--rg-hairline)]" />)
      return
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      flushParagraph()
      flushList()
      flushTable()
      const level = heading[1].length
      const className =
        level === 1
          ? "mt-1 mb-5 text-2xl font-bold text-[var(--rg-ink)]"
          : level === 2
            ? "mt-7 mb-3 text-lg font-semibold text-[var(--rg-ink)]"
            : "mt-5 mb-2 text-base font-semibold text-[var(--rg-ink)]"
      blocks.push(
        <div key={`h-${blocks.length}`} className={className}>
          {renderInline(heading[2])}
        </div>,
      )
      return
    }

    const bullet = trimmed.match(/^[-*]\s+(.*)$/)
    if (bullet) {
      flushParagraph()
      flushTable()
      list.push(bullet[1])
      return
    }

    paragraph.push(trimmed)
  })

  flushParagraph()
  flushList()
  flushTable()
  const pendingCode = code as string[] | null
  if (pendingCode) {
    blocks.push(
      <pre key={`code-${blocks.length}`} className="code-panel my-4 overflow-auto p-4 text-xs leading-6">
        {pendingCode.join("\n")}
      </pre>,
    )
  }
  return blocks
}

function normalizeMarkdownTables(content: string) {
  return content.replace(/\s+\|\s*\|\s*/g, " |\n| ")
}

function isTableLine(line: string) {
  const trimmed = line.trim()
  return trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.split("|").length >= 3
}

function parseTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim())
}

function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index} className="font-semibold text-[var(--rg-ink)]">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index} className="rounded bg-[var(--rg-surface-card)] px-1.5 py-0.5 text-[0.9em] text-[var(--rg-ink)]">{part.slice(1, -1)}</code>
    }
    return <Fragment key={index}>{part}</Fragment>
  })
}

function OutputCard({ output, taskLabel }: { output: Output; taskLabel?: string }) {
  return (
    <Card className="surface-card">
      <CardHeader className="pb-2">
        <CardTitle className="space-y-2 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="line-clamp-2">{output.title}</span>
            <Badge variant="secondary" className="shrink-0">{OUTPUT_TYPE_LABELS[output.output_type] || output.output_type}</Badge>
          </div>
          {taskLabel && <div className="text-xs font-normal text-[var(--rg-muted)]">{taskLabel}</div>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="max-h-[280px] overflow-auto rounded-lg border border-[var(--rg-hairline)] bg-[var(--rg-surface-soft)] p-3 text-xs leading-5 text-[var(--rg-body)] whitespace-pre-wrap">
          {output.content}
        </pre>
      </CardContent>
    </Card>
  )
}
