"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import { RUN_STATUS_LABELS } from "@/lib/types"

export default function HomePage() {
  const router = useRouter()
  const [goal, setGoal] = useState("")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState("")

  const exampleGoal = "请让课题组围绕「面向研究生课题组协作的多Agent系统」完成一次阶段性调研，输出相关项目调研、系统架构建议、实验验证方案、数据分析指标和周报总结。"

  const handleSubmit = async () => {
    if (!goal.trim()) return
    setLoading(true)
    setError("")
    setResult(null)
    try {
      const { run_id } = await api.createRun(goal.trim())
      const runResult = await api.runAll(run_id)
      const runData = await api.getRun(run_id)
      setResult({ ...runResult, run: runData.run, tasks: runData.tasks })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>启动虚拟课题组</CardTitle>
          <CardDescription>
            输入研究目标，导师Agent将拆解任务并分配给五类研究生Agent协作完成
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            className="w-full min-h-[120px] p-3 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
            placeholder={exampleGoal}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <div className="flex gap-3 items-center">
            <button
              onClick={handleSubmit}
              disabled={loading || !goal.trim()}
              className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                  运行中...
                </span>
              ) : (
                "启动虚拟课题组"
              )}
            </button>
            <button
              onClick={() => setGoal(exampleGoal)}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              填入示例
            </button>
          </div>
          {error && (
            <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
          )}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              运行结果
              <Badge variant={result.status === "completed" ? "default" : "destructive"}>
                {RUN_STATUS_LABELS[result.run?.status] || result.run?.status}
              </Badge>
            </CardTitle>
            <CardDescription>
              研究目标：{result.run?.research_goal?.slice(0, 80)}...
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <div className="bg-blue-50 rounded-lg p-4 text-center">
                <div className="text-2xl font-bold text-blue-700">{result.tasks_total}</div>
                <div className="text-sm text-blue-600">总任务数</div>
              </div>
              <div className="bg-green-50 rounded-lg p-4 text-center">
                <div className="text-2xl font-bold text-green-700">{result.tasks_completed}</div>
                <div className="text-sm text-green-600">已完成</div>
              </div>
              <div className="bg-amber-50 rounded-lg p-4 text-center">
                <div className="text-2xl font-bold text-amber-700">{result.tasks_need_revision}</div>
                <div className="text-sm text-amber-600">需返工</div>
              </div>
            </div>

            <Separator />

            <div className="flex gap-3">
              <button
                onClick={() => router.push(`/tasks?run_id=${result.run?.id}`)}
                className="px-4 py-2 bg-gray-100 rounded-lg text-sm hover:bg-gray-200"
              >
                查看任务板 →
              </button>
              <button
                onClick={() => router.push("/agents")}
                className="px-4 py-2 bg-gray-100 rounded-lg text-sm hover:bg-gray-200"
              >
                查看Agent状态 →
              </button>
              <button
                onClick={() => router.push(`/outputs?run_id=${result.run?.id}`)}
                className="px-4 py-2 bg-gray-100 rounded-lg text-sm hover:bg-gray-200"
              >
                查看产出 →
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>系统概览</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-gray-600">
          <p><strong>导师Agent</strong> — 负责任务拆解、分配、审核和阶段性总结</p>
          <p><strong>五类研究生Agent</strong> — 调研/工程/实验/数据分析/写作，按能力画像分工协作</p>
          <p><strong>本科生SubAgent</strong> — 临时创建处理短期子任务，用完即销毁</p>
          <p><strong>任务板</strong> — 看板形式展示所有任务的状态流转</p>
        </CardContent>
      </Card>
    </div>
  )
}
