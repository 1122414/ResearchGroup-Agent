"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api"
import { OUTPUT_TYPE_LABELS, type Output, type Run, type Task } from "@/lib/types"

export default function OutputsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-gray-500">正在加载输出...</div>}>
      <OutputsContent />
    </Suspense>
  )
}

function OutputsContent() {
  const searchParams = useSearchParams()
  const runId = searchParams.get("run_id")
  const [outputs, setOutputs] = useState<Output[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(runId)
  const [selectedTaskId, setSelectedTaskId] = useState<string | "">("")
  const [selectedType, setSelectedType] = useState<string | "">("")

  useEffect(() => {
    api.getRuns().then(({ runs }) => setRuns(runs))
  }, [])

  useEffect(() => {
    if (!selectedRun) {
      queueMicrotask(() => {
        setOutputs([])
        setTasks([])
      })
      return
    }
    let cancelled = false
    Promise.all([api.getOutputs(selectedRun), api.getTasks(selectedRun)]).then(
      ([{ outputs }, { tasks }]) => {
        if (cancelled) return
        setOutputs(outputs)
        setTasks(tasks)
      },
    )
    return () => {
      cancelled = true
    }
  }, [selectedRun])

  const filteredOutputs = useMemo(() => {
    let result = outputs
    if (selectedTaskId) {
      result = result.filter((o) => o.task_id === selectedTaskId)
    }
    if (selectedType) {
      result = result.filter((o) => o.output_type === selectedType)
    }
    return result
  }, [outputs, selectedTaskId, selectedType])

  const finalReport = filteredOutputs.find((output) => output.output_type === "final_report")
  const otherOutputs = filteredOutputs.filter((output) => output.output_type !== "final_report")

  const outputTypes = useMemo(() => {
    const types = new Set(outputs.map((o) => o.output_type))
    return Array.from(types)
  }, [outputs])

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold">输出中心</h2>
        <p className="text-sm text-gray-500">查看任务产出、SubAgent 产出、导师审核和最终报告。</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm text-gray-500">Run：</div>
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={() => {
              setSelectedRun(run.id)
              setSelectedTaskId("")
              setSelectedType("")
            }}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
              selectedRun === run.id ? "bg-gray-900 text-white" : "bg-gray-100 hover:bg-gray-200"
            }`}
          >
            {run.id}
          </button>
        ))}
        {runs.length === 0 && <span className="text-sm text-gray-500">暂无运行记录。</span>}
      </div>

      {selectedRun && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-sm text-gray-500">任务过滤：</div>
          <select
            value={selectedTaskId}
            onChange={(e) => setSelectedTaskId(e.target.value)}
            className="rounded-lg border bg-white px-3 py-1.5 text-sm"
          >
            <option value="">全部任务</option>
            {tasks.map((task) => (
              <option key={task.id} value={task.id}>
                {task.title}
              </option>
            ))}
          </select>

          <div className="text-sm text-gray-500">类型过滤：</div>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="rounded-lg border bg-white px-3 py-1.5 text-sm"
          >
            <option value="">全部类型</option>
            {outputTypes.map((type) => (
              <option key={type} value={type}>
                {OUTPUT_TYPE_LABELS[type] || type}
              </option>
            ))}
          </select>

          {(selectedTaskId || selectedType) && (
            <button
              onClick={() => {
                setSelectedTaskId("")
                setSelectedType("")
              }}
              className="text-sm text-gray-500 hover:text-gray-900"
            >
              清除过滤
            </button>
          )}
        </div>
      )}

      {finalReport && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{finalReport.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <article className="max-h-[600px] overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-sm leading-6">
              {finalReport.content}
            </article>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {otherOutputs.map((output) => (
          <Card key={output.id}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{output.title}</span>
                <Badge variant="secondary">{OUTPUT_TYPE_LABELS[output.output_type] || output.output_type}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-xs">
                {output.content}
              </pre>
            </CardContent>
          </Card>
        ))}
      </div>

      {selectedRun && filteredOutputs.length === 0 && (
        <div className="text-center text-sm text-gray-500">
          该 Run 暂无输出，或当前过滤条件下无匹配结果。
        </div>
      )}
    </div>
  )
}
