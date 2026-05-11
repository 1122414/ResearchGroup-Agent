"use client"

import { useEffect, useState, type ReactNode } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

type SystemSettings = Record<string, string | number | boolean>

const TEXT_FIELDS = [
  ["llm_api_key", "LLM API Key", "password"],
  ["llm_base_url", "API Base URL", "text"],
  ["llm_model_name", "默认模型", "text"],
  ["advisor_model_name", "导师模型", "text"],
  ["graduate_model_name", "研究生模型", "text"],
  ["subagent_model_name", "SubAgent 模型", "text"],
  ["log_level", "日志级别", "text"],
] as const

const NUMBER_FIELDS = [
  ["llm_timeout", "LLM 超时秒数"],
  ["llm_max_retries", "LLM 重试次数"],
  ["scheduler_skill_weight", "调度技能权重"],
  ["scheduler_idle_weight", "调度空闲权重"],
  ["collab_complexity_threshold", "协作复杂度阈值"],
  ["collab_load_threshold", "协作负载阈值"],
  ["subagent_complexity_threshold", "SubAgent 复杂度阈值"],
  ["subagent_decomposability_threshold", "SubAgent 可拆解阈值"],
  ["run_poll_interval_ms", "运行轮询间隔 ms"],
  ["token_estimate_chars_per_token", "Token 估算字符数"],
  ["default_input_cost_per_token", "输入成本/Token"],
  ["default_output_cost_per_token", "输出成本/Token"],
  ["mock_input_cost_per_token", "Mock 输入成本/Token"],
  ["mock_output_cost_per_token", "Mock 输出成本/Token"],
] as const

export function SettingsButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button onClick={() => setOpen(true)} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900" title="系统设置">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.1a2 2 0 0 1-1-1.72v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      </button>
      {open && <SettingsPanel onClose={() => setOpen(false)} />}
    </>
  )
}

function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [draft, setDraft] = useState<SystemSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => {
    api.getSettings()
      .then((data) => {
        setDraft(data)
      })
      .finally(() => setLoading(false))
  }, [])

  const setValue = (key: string, value: string | number | boolean) => {
    setDraft((current) => (current ? { ...current, [key]: value } : current))
  }

  const save = async () => {
    if (!draft) return
    setSaving(true)
    setMessage("")
    try {
      const res = await api.updateSettings(draft)
      const updated = res.updated as SystemSettings
      setDraft((current) => (current ? { ...current, ...updated } : current))
      setMessage(res.message || "配置已保存并同步到 .env")
      setTimeout(() => setMessage(""), 3500)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "保存配置失败")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
        <div className="rounded-xl bg-white p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
          正在加载系统设置...
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-3xl overflow-auto rounded-xl bg-white p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold">系统设置</h2>
            <p className="mt-1 text-xs text-gray-500">保存后会同步当前后端进程配置，并写回项目 .env 文件。</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <X className="size-4" />
          </button>
        </div>

        {message && <div className="mb-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">{message}</div>}

        {draft && (
          <div className="space-y-4 text-sm">
            <Section title="运行模式">
              <ToggleRow label="Mock 模式" description="开启后不调用真实 LLM，适合本地演示和 UI 调试。" checked={Boolean(draft.mock_mode)} onChange={(value) => setValue("mock_mode", value)} />
              <ToggleRow label="运行取消检查" description="执行阶段是否定期响应取消请求。" checked={Boolean(draft.run_cancel_check_enabled)} onChange={(value) => setValue("run_cancel_check_enabled", value)} />
            </Section>

            <Section title="模型与 API">
              <div className="grid gap-3 md:grid-cols-2">
                {TEXT_FIELDS.map(([key, label, type]) => (
                  <Field key={key} label={label} type={type} value={String(draft[key] ?? "")} onChange={(value) => setValue(key, value)} />
                ))}
              </div>
            </Section>

            <Section title="调度、成本与轮询">
              <div className="grid gap-3 md:grid-cols-2">
                {NUMBER_FIELDS.map(([key, label]) => (
                  <Field key={key} label={label} type="number" value={String(draft[key] ?? "")} onChange={(value) => setValue(key, Number(value))} />
                ))}
              </div>
            </Section>

            <div className="rounded-lg bg-amber-50 p-3 text-xs leading-6 text-amber-800">
              API Key 会写入本机项目的 <code>.env</code>。端口等启动期配置会保存，但需要重启对应服务后完全生效。
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose}>关闭</Button>
              <Button onClick={save} disabled={saving || !draft}>{saving ? "保存中..." : "保存并同步 .env"}</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200">
      <div className="border-b bg-gray-50 px-3 py-2 text-xs font-semibold uppercase text-gray-500">{title}</div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function Field({ label, type, value, onChange }: { label: string; type: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-gray-200 px-3 text-sm outline-none focus:border-gray-400"
      />
    </label>
  )
}

function ToggleRow({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-gray-100 p-3">
      <div>
        <div className="font-medium text-gray-900">{label}</div>
        <div className="text-xs text-gray-500">{description}</div>
      </div>
      <button onClick={() => onChange(!checked)} className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-gray-900" : "bg-gray-200"}`}>
        <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${checked ? "translate-x-5" : ""}`} />
      </button>
    </div>
  )
}
