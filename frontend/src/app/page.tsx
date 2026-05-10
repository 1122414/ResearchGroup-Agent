"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api"
import { RUN_STATUS_LABELS, type Run } from "@/lib/types"

export default function HomePage() {
  const router = useRouter()
  const [goal, setGoal] = useState("")
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [mockMode, setMockMode] = useState<boolean | null>(null)

  const exampleGoal = "研究一个可观测的多 Agent 课题组协作系统，要求能拆解任务、分配研究生 Agent、记录执行过程和生成阶段报告。"

  useEffect(() => {
    api.health().then((data) => setMockMode(data.mock_mode)).catch(() => setMockMode(null))
    api.getRuns().then(({ runs }) => setRuns(runs)).catch(() => setRuns([]))
  }, [])

  const handleSubmit = async () => {
    if (!goal.trim()) return
    setLoading(true)
    setError("")
    try {
      const { run_id } = await api.createRun(goal.trim())
      await api.runAll(run_id)
      router.push(`/runs/${run_id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建运行失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>创建研究任务</CardTitle>
              <CardDescription>
                输入研究目标，系统会由导师 Agent 拆解任务，并调度研究生 Agent 协作执行。
              </CardDescription>
            </div>
            {mockMode !== null && (
              <Badge variant={mockMode ? "secondary" : "default"}>
                {mockMode ? "Mock 模式" : "真实 LLM 模式"}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            className="min-h-[140px] w-full resize-y rounded-lg border p-3 text-sm outline-none focus:ring-2 focus:ring-gray-900"
            placeholder={exampleGoal}
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleSubmit}
              disabled={loading || !goal.trim()}
              className="rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "正在创建并执行..." : "创建并运行"}
            </button>
            <button
              onClick={() => setGoal(exampleGoal)}
              className="text-sm text-gray-600 hover:text-gray-900"
              type="button"
            >
              填入示例目标
            </button>
          </div>
          {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>最近运行</CardTitle>
          <CardDescription>继续查看已有 Run 的任务、状态和输出。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {runs.length === 0 && <div className="text-sm text-gray-500">还没有运行记录。</div>}
          {runs.slice(0, 8).map((run) => (
            <button
              key={run.id}
              onClick={() => router.push(`/runs/${run.id}`)}
              className="flex w-full items-center justify-between gap-4 rounded-lg border bg-white p-3 text-left text-sm hover:bg-gray-50"
            >
              <div className="min-w-0">
                <div className="font-medium text-gray-900">{run.id}</div>
                <div className="truncate text-gray-500">{run.research_goal}</div>
              </div>
              <Badge variant="secondary">{RUN_STATUS_LABELS[run.status] || run.status}</Badge>
            </button>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
