"use client"

import { useState, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"

export default function OutputsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-gray-500">加载中...</div>}>
      <OutputsContent />
    </Suspense>
  )
}

function OutputsContent() {
  const searchParams = useSearchParams()
  const runId = searchParams.get("run_id")
  const [outputs, setOutputs] = useState<any[]>([])
  const [runs, setRuns] = useState<any[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(runId)
  const [report, setReport] = useState("")

  useEffect(() => {
    api.getRuns().then(({ runs }) => setRuns(runs))
  }, [])

  useEffect(() => {
    if (selectedRun) {
      api.getOutputs(selectedRun).then(({ outputs: fetchedOutputs }) => {
        setOutputs(fetchedOutputs)
        const finalReport = fetchedOutputs.find((o: any) => o.output_type === "final_report")
        if (finalReport) setReport(finalReport.content)
      })
    }
  }, [selectedRun])

  const taskOutputs = outputs.filter((o) => o.output_type === "task_result")
  const subagentOutputs = outputs.filter((o) => o.output_type === "subagent_result")
  const reviewOutputs = outputs.filter((o) => o.output_type === "review")
  const finalReportOutput = outputs.find((o) => o.output_type === "final_report")

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">产出管理</h2>

      <div className="flex gap-2 flex-wrap">
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={() => setSelectedRun(run.id)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              selectedRun === run.id ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"
            }`}
          >
            {run.id}
          </button>
        ))}
        {runs.length === 0 && <span className="text-sm text-gray-500">暂无运行记录</span>}
      </div>

      {finalReportOutput && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{finalReportOutput.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-sm whitespace-pre-wrap font-mono bg-gray-50 p-4 rounded-lg max-h-[600px] overflow-auto">
              {finalReportOutput.content}
            </pre>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              任务结果
              <Badge variant="secondary">{taskOutputs.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[400px] overflow-auto">
            {taskOutputs.map((o) => (
              <details key={o.id} className="text-sm">
                <summary className="cursor-pointer hover:text-blue-600">{o.title}</summary>
                <pre className="text-xs mt-1 bg-gray-50 p-2 rounded whitespace-pre-wrap">
                  {o.content.slice(0, 500)}{o.content.length > 500 ? "..." : ""}
                </pre>
              </details>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              SubAgent结果 & 审核
              <Badge variant="secondary">{subagentOutputs.length + reviewOutputs.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[400px] overflow-auto">
            {subagentOutputs.map((o) => (
              <details key={o.id} className="text-sm">
                <summary className="cursor-pointer hover:text-pink-600">🤖 {o.title}</summary>
                <pre className="text-xs mt-1 bg-gray-50 p-2 rounded whitespace-pre-wrap">
                  {o.content.slice(0, 300)}
                </pre>
              </details>
            ))}
            {reviewOutputs.map((o) => (
              <details key={o.id} className="text-sm">
                <summary className="cursor-pointer hover:text-purple-600">📋 {o.title}</summary>
                <pre className="text-xs mt-1 bg-gray-50 p-2 rounded whitespace-pre-wrap">
                  {o.content.slice(0, 300)}
                </pre>
              </details>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
