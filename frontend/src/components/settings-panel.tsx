"use client"

import { useEffect, useState, type ReactNode } from "react"
import { KeyRound, Save, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

type SystemSettings = Record<string, string | number | boolean>

const TEXT_FIELDS = [
  ["llm_base_url", "API Base URL", "text"],
  ["llm_model_name", "默认模型", "text"],
  ["advisor_model_name", "导师模型", "text"],
  ["graduate_model_name", "研究生模型", "text"],
  ["subagent_model_name", "SubAgent 模型", "text"],
  ["vision_model_name", "视觉模型", "text"],
  ["log_level", "日志级别", "text"],
] as const

const NUMBER_FIELDS = [
  ["llm_timeout", "LLM 超时秒数"],
  ["llm_max_retries", "LLM 重试次数"],
  ["llm_max_tokens", "LLM 最大输出 Tokens"],
  ["advisor_temperature", "导师温度"],
  ["graduate_temperature", "研究生温度"],
  ["subagent_temperature", "SubAgent 温度"],
  ["scheduler_skill_weight", "调度能力权重"],
  ["scheduler_idle_weight", "调度空闲权重"],
  ["scheduler_idle_scale", "空闲分缩放"],
  ["collab_complexity_threshold", "协作复杂度阈值"],
  ["collab_load_threshold", "协作负载阈值"],
  ["collab_max_count", "最大协作者数量"],
  ["subagent_complexity_threshold", "SubAgent 复杂度阈值"],
  ["subagent_decomposability_threshold", "SubAgent 可拆解阈值"],
  ["subagent_mentoring_threshold", "SubAgent 导师能力阈值"],
  ["run_poll_interval_ms", "运行轮询间隔 ms"],
  ["frontend_log_flush_interval_ms", "前端日志上报间隔 ms"],
  ["run_event_default_limit", "默认事件数量"],
  ["run_event_max_limit", "最大事件数量"],
  ["attachment_extract_max_chars", "附件提取最大字符"],
  ["attachment_max_file_size_mb", "附件最大 MB"],
  ["token_estimate_chars_per_token", "Token 估算字符数"],
  ["default_input_cost_per_token", "输入单 Token 成本"],
  ["default_output_cost_per_token", "输出单 Token 成本"],
  ["mock_input_cost_per_token", "Mock 输入单 Token 成本"],
  ["mock_output_cost_per_token", "Mock 输出单 Token 成本"],
] as const

export function SettingsButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button onClick={() => setOpen(true)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-950" title="系统设置">
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
  const [apiKeyDraft, setApiKeyDraft] = useState("")
  const [clearApiKey, setClearApiKey] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => {
    api.getSettings()
      .then((data) => setDraft(data))
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
      const payload: SystemSettings = { ...draft }
      delete payload.llm_api_key
      delete payload.llm_api_key_masked
      delete payload.has_llm_api_key
      if (apiKeyDraft.trim()) payload.llm_api_key = apiKeyDraft.trim()
      if (clearApiKey) payload.clear_llm_api_key = true

      const res = await api.updateSettings(payload)
      const updated = res.updated as SystemSettings
      setDraft((current) => (current ? { ...current, ...updated, llm_api_key: "" } : current))
      setApiKeyDraft("")
      setClearApiKey(false)
      setMessage(res.message || "配置已保存")
      setTimeout(() => setMessage(""), 3500)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "保存配置失败")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45" onClick={onClose}>
        <div className="rounded-xl bg-white p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
          正在读取系统设置...
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-4xl overflow-auto rounded-xl bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-950">系统设置</h2>
            <p className="mt-1 text-sm text-slate-500">这里的修改会同步写入项目根目录 .env。密钥只写入，不回显。</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="size-4" />
          </button>
        </div>

        {message && <div className="mb-4 rounded-lg bg-sky-50 p-3 text-sm text-sky-700">{message}</div>}

        {draft && (
          <div className="space-y-4 text-sm">
            <Section title="运行开关">
              <div className="grid gap-3 md:grid-cols-2">
                <ToggleRow label="Mock 模式" description="开启后使用本地模拟结果，不调用真实 LLM。" checked={Boolean(draft.mock_mode)} onChange={(value) => setValue("mock_mode", value)} />
                <ToggleRow label="运行取消检查" description="开启后执行链路会在阶段边界响应取消。" checked={Boolean(draft.run_cancel_check_enabled)} onChange={(value) => setValue("run_cancel_check_enabled", value)} />
                <ToggleRow label="多模态输入" description="开启后允许图片进入可用性检查，需配置视觉模型。" checked={Boolean(draft.multimodal_enabled)} onChange={(value) => setValue("multimodal_enabled", value)} />
              </div>
            </Section>

            <Section title="模型与 API">
              <div className="mb-3 rounded-lg border border-slate-200 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600">
                  <KeyRound className="size-4" />
                  LLM API Key
                  {draft.has_llm_api_key ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">{String(draft.llm_api_key_masked)}</span> : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-500">未配置</span>}
                </div>
                <input
                  type="password"
                  value={apiKeyDraft}
                  placeholder="留空表示不修改现有密钥"
                  onChange={(event) => setApiKeyDraft(event.target.value)}
                  className="h-9 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-slate-400"
                />
                <label className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                  <input type="checkbox" checked={clearApiKey} onChange={(event) => setClearApiKey(event.target.checked)} />
                  清空当前 API Key
                </label>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {TEXT_FIELDS.map(([key, label, type]) => (
                  <Field key={key} label={label} type={type} value={String(draft[key] ?? "")} onChange={(value) => setValue(key, value)} />
                ))}
              </div>
            </Section>

            <Section title="调度与运行参数">
              <div className="grid gap-3 md:grid-cols-2">
                {NUMBER_FIELDS.map(([key, label]) => (
                  <Field key={key} label={label} type="number" value={String(draft[key] ?? "")} onChange={(value) => setValue(key, Number(value))} />
                ))}
              </div>
            </Section>

            <div className="rounded-lg bg-amber-50 p-3 text-xs leading-6 text-amber-800">
              修改模型、端口、跨域等启动参数后，建议重启后端和前端服务。运行中的任务不会自动迁移到新配置。
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose}>取消</Button>
              <Button onClick={save} disabled={saving || !draft}>
                <Save className="mr-2 size-4" />
                {saving ? "保存中..." : "保存到 .env"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200">
      <div className="border-b bg-slate-50 px-3 py-2 text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function Field({ label, type, value, onChange }: { label: string; type: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-slate-400"
      />
    </label>
  )
}

function ToggleRow({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-100 p-3">
      <div>
        <div className="font-medium text-slate-950">{label}</div>
        <div className="text-xs text-slate-500">{description}</div>
      </div>
      <button type="button" onClick={() => onChange(!checked)} className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-slate-950" : "bg-slate-200"}`}>
        <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${checked ? "translate-x-5" : ""}`} />
      </button>
    </div>
  )
}
