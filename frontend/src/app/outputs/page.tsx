"use client"

import { Suspense, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api"
import { OUTPUT_TYPE_LABELS, type Output, type Run } from "@/lib/types"

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
  const [selectedRun, setSelectedRun] = useState<string | null>(runId)

  useEffect(() => {
    api.getRuns().then(({ runs }) => setRuns(runs))
  }, [])

  useEffect(() => {
    if (selectedRun) {
      api.getOutputs(selectedRun).then(({ outputs }) => setOutputs(outputs))
    }
  }, [selectedRun])

  const finalReport = outputs.find((output) => output.output_type === "final_report")
  const otherOutputs = outputs.filter((output) => output.output_type !== "final_report")

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold">输出中心</h2>
        <p className="text-sm text-gray-500">查看任务产出、SubAgent 产出、导师审核和最终报告。</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={() => setSelectedRun(run.id)}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
              selectedRun === run.id ? "bg-gray-900 text-white" : "bg-gray-100 hover:bg-gray-200"
            }`}
          >
            {run.id}
          </button>
        ))}
        {runs.length === 0 && <span className="text-sm text-gray-500">暂无运行记录。</span>}
      </div>

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
    </div>
  )
}
