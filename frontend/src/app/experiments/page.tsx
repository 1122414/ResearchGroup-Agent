"use client"

import { useCallback, useEffect, useState } from "react"
import { CheckCircle2, FlaskConical, Play, RefreshCw, ShieldAlert, XCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import type { ExperimentFile, ExperimentPlan } from "@/lib/types"

const EMPTY_FORM = {
  title: "",
  objective: "",
  run_id: "",
  task_id: "",
  agent_id: "experiment_agent",
  workspace_dir: "",
  commands: "python -c \"print('experiment ok')\"",
  files: "[]",
  env_vars: "{}",
}

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  needs_review: "待审查",
  approved: "已批准",
  rejected: "已驳回",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
}

const RISK_LABELS: Record<string, string> = {
  safe: "低风险",
  needs_review: "需审查",
  dangerous: "高风险",
}

export default function ExperimentsPage() {
  const [plans, setPlans] = useState<ExperimentPlan[]>([])
  const [config, setConfig] = useState<Record<string, string | number | boolean>>({})
  const [form, setForm] = useState(EMPTY_FORM)
  const [selected, setSelected] = useState<ExperimentPlan | null>(null)
  const [message, setMessage] = useState("")

  const load = useCallback(async () => {
    const [{ config }, { plans }] = await Promise.all([api.getExperimentConfig(), api.getExperimentPlans()])
    setConfig(config)
    setPlans(plans)
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      load().catch((err) => setMessage(err instanceof Error ? err.message : "加载实验配置失败"))
    }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const saveConfig = async (key: string, value: string | number | boolean) => {
    const result = await api.updateExperimentConfig({ [key]: value })
    setConfig((current) => ({ ...current, ...(result.updated as Record<string, string | number | boolean>) }))
    setMessage("实验配置已写入 .env")
  }

  const createPlan = async () => {
    try {
      const files = JSON.parse(form.files || "[]") as ExperimentFile[]
      const envVars = JSON.parse(form.env_vars || "{}") as Record<string, string>
      const commands = form.commands
        .split("\n")
        .map((command) => command.trim())
        .filter(Boolean)
        .map((command) => ({ command }))
      const payload = {
        title: form.title,
        objective: form.objective,
        run_id: form.run_id || null,
        task_id: form.task_id || null,
        agent_id: form.agent_id,
        workspace_dir: form.workspace_dir || undefined,
        files,
        commands,
        env_vars: envVars,
      }
      if (!payload.title || commands.length === 0) {
        setMessage("请填写实验标题和至少一条命令")
        return
      }
      const result = await api.createExperimentPlan(payload)
      setSelected(result.plan)
      setMessage("实验计划已创建，已完成风险扫描")
      await load()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "实验计划创建失败，请检查 JSON")
    }
  }

  const runAction = async (action: () => Promise<{ plan: ExperimentPlan }>, success: string) => {
    try {
      const result = await action()
      setSelected(result.plan)
      setMessage(success)
      await load()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "操作失败")
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase text-slate-500">Experiment Executor</div>
          <h1 className="mt-1 text-2xl font-bold text-slate-950">实验执行与审查</h1>
          <p className="mt-1 text-sm text-slate-500">实验 Agent 的代码、命令和环境变量先进入审查队列，批准后才允许在配置工作区运行。</p>
        </div>
        <Button variant="outline" onClick={() => load().catch((err) => setMessage(err instanceof Error ? err.message : "刷新失败"))}>
          <RefreshCw className="mr-2 size-4" />
          刷新
        </Button>
      </div>

      {message && <div className="rounded-lg border border-sky-100 bg-sky-50 px-3 py-2 text-sm text-sky-700">{message}</div>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">执行配置</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Toggle label="启用本地执行" value={Boolean(config.experiment_execution_enabled)} onChange={(value) => saveConfig("experiment_execution_enabled", value)} />
          <Toggle label="执行前必须审查" value={Boolean(config.experiment_require_review)} onChange={(value) => saveConfig("experiment_require_review", value)} />
          <Toggle label="允许网络访问" value={Boolean(config.experiment_allow_network)} onChange={(value) => saveConfig("experiment_allow_network", value)} />
          <Toggle label="允许安装依赖" value={Boolean(config.experiment_allow_package_install)} onChange={(value) => saveConfig("experiment_allow_package_install", value)} />
          <Field label="工作区" value={String(config.experiment_workspace_dir || "")} onChange={(value) => saveConfig("experiment_workspace_dir", value)} />
          <Field label="执行后端" value={String(config.experiment_execution_backend || "local")} onChange={(value) => saveConfig("experiment_execution_backend", value)} />
          <Field label="命令超时秒数" type="number" value={String(config.experiment_command_timeout_seconds || 300)} onChange={(value) => saveConfig("experiment_command_timeout_seconds", Number(value))} />
          <Field label="最大输出字符" type="number" value={String(config.experiment_max_output_chars || 20000)} onChange={(value) => saveConfig("experiment_max_output_chars", Number(value))} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[420px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="flex items-center text-base">
              <FlaskConical className="mr-2 size-4" />
              新建实验计划
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Field label="标题" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
            <Field label="目标" value={form.objective} onChange={(value) => setForm({ ...form, objective: value })} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Run ID" value={form.run_id} onChange={(value) => setForm({ ...form, run_id: value })} />
              <Field label="Task ID" value={form.task_id} onChange={(value) => setForm({ ...form, task_id: value })} />
            </div>
            <Field label="Agent ID" value={form.agent_id} onChange={(value) => setForm({ ...form, agent_id: value })} />
            <Field label="工作区覆盖" value={form.workspace_dir} onChange={(value) => setForm({ ...form, workspace_dir: value })} />
            <TextArea label="命令，每行一条" rows={5} value={form.commands} onChange={(value) => setForm({ ...form, commands: value })} />
            <TextArea label="文件 JSON" rows={5} value={form.files} onChange={(value) => setForm({ ...form, files: value })} />
            <TextArea label="环境变量 JSON" rows={4} value={form.env_vars} onChange={(value) => setForm({ ...form, env_vars: value })} />
            <Button onClick={createPlan} className="w-full">提交审查</Button>
          </CardContent>
        </Card>

        <div className="space-y-3">
          {plans.map((plan) => (
            <Card key={plan.id} className="transition-shadow hover:shadow-md">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold text-slate-950">{plan.title}</h2>
                      <Badge variant="outline">{STATUS_LABELS[plan.status] || plan.status}</Badge>
                      <Badge variant={plan.risk_level === "dangerous" ? "destructive" : "outline"}>{RISK_LABELS[plan.risk_level] || plan.risk_level}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{plan.objective || "暂无实验目标说明"}</p>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                      <span>{plan.id}</span>
                      <span>{plan.agent_id}</span>
                      <span>{plan.commands.length} commands</span>
                      <span>{plan.workspace_dir}</span>
                    </div>
                    {plan.risk_reasons.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {plan.risk_reasons.map((reason) => <span key={reason} className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">{reason}</span>)}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => setSelected(plan)}>查看</Button>
                    <Button variant="outline" onClick={() => runAction(() => api.scanExperimentPlan(plan.id), "风险扫描已更新")}>
                      <ShieldAlert className="mr-2 size-4" />
                      扫描
                    </Button>
                    <Button variant="outline" onClick={() => runAction(() => api.approveExperimentPlan(plan.id), "实验计划已批准")}>
                      <CheckCircle2 className="mr-2 size-4" />
                      批准
                    </Button>
                    <Button variant="outline" onClick={() => runAction(() => api.rejectExperimentPlan(plan.id, "user rejected"), "实验计划已驳回")}>
                      <XCircle className="mr-2 size-4" />
                      驳回
                    </Button>
                    <Button onClick={() => runAction(() => api.executeExperimentPlan(plan.id), "实验执行已完成")}>
                      <Play className="mr-2 size-4" />
                      执行
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {plans.length === 0 && (
            <Card>
              <CardContent className="p-8 text-center text-sm text-slate-500">暂无实验计划。先提交一份计划进入审查队列。</CardContent>
            </Card>
          )}
        </div>
      </div>

      {selected && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">实验详情：{selected.title}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 lg:grid-cols-2">
            <Preview title="命令" value={selected.commands.map((item) => item.command).join("\n")} />
            <Preview title="文件" value={JSON.stringify(selected.files, null, 2)} />
            <Preview title="结果 stdout" value={selected.result?.stdout || "暂无输出"} />
            <Preview title="结果 stderr" value={selected.result?.stderr || "暂无错误输出"} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-slate-400" />
    </label>
  )
}

function TextArea({ label, value, onChange, rows }: { label: string; value: string; onChange: (value: string) => void; rows: number }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={rows} className="w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs outline-none focus:border-slate-400" />
    </label>
  )
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm">
      <span className="text-slate-700">{label}</span>
      <input type="checkbox" checked={value} onChange={(event) => onChange(event.target.checked)} className="size-4" />
    </label>
  )
}

function Preview({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-600">{title}</div>
      <pre className="max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{value}</pre>
    </div>
  )
}
