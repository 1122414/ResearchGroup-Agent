"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

interface SystemSettings {
  mock_mode: boolean
  llm_model_name: string
  advisor_model_name: string
  graduate_model_name: string
  subagent_model_name: string
  llm_base_url: string
  llm_timeout: number
  llm_max_retries: number
  scheduler_skill_weight: number
  scheduler_idle_weight: number
  collab_complexity_threshold: number
  collab_load_threshold: number
  subagent_complexity_threshold: number
  subagent_decomposability_threshold: number
  run_poll_interval_ms: number
  run_cancel_check_enabled: boolean
  token_estimate_chars_per_token: number
  default_input_cost_per_token: number
  default_output_cost_per_token: number
  mock_input_cost_per_token: number
  mock_output_cost_per_token: number
  log_level: string
  backend_port: number
  frontend_port: number
}

export function SettingsButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        title="系统设置"
      >
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
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => {
    api.getSettings()
      .then((data) => {
        setSettings(data as unknown as SystemSettings)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleToggleMock = async () => {
    if (!settings) return
    setSaving(true)
    try {
      const res = await api.updateSettings({ mock_mode: !settings.mock_mode })
      setSettings((prev) => (prev ? { ...prev, mock_mode: !prev.mock_mode } : prev))
      setMessage(res.message || "已更新")
      setTimeout(() => setMessage(""), 3000)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "更新失败")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
        <div className="rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
          正在加载设置...
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="max-h-[85vh] w-[520px] overflow-auto rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold">系统设置</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {message && (
          <div className="mb-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">{message}</div>
        )}

        {settings && (
          <div className="space-y-4 text-sm">
            <Section title="运行模式">
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <div className="font-medium">Mock 模式</div>
                  <div className="text-xs text-gray-500">离线演示模式，不消耗真实 API</div>
                </div>
                <button
                  onClick={handleToggleMock}
                  disabled={saving}
                  className={`relative h-6 w-11 rounded-full transition-colors ${settings.mock_mode ? "bg-gray-900" : "bg-gray-200"}`}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${settings.mock_mode ? "translate-x-5" : ""}`} />
                </button>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                <span>当前模型：</span>
                <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono">{settings.llm_model_name}</span>
              </div>
            </Section>

            <Section title="模型配置">
              <ReadOnlyRow label="基础模型" value={settings.llm_model_name} />
              <ReadOnlyRow label="导师模型" value={settings.advisor_model_name} />
              <ReadOnlyRow label="研究生模型" value={settings.graduate_model_name} />
              <ReadOnlyRow label="SubAgent 模型" value={settings.subagent_model_name} />
              <ReadOnlyRow label="API 地址" value={settings.llm_base_url} />
              <ReadOnlyRow label="超时" value={`${settings.llm_timeout} 秒`} />
              <ReadOnlyRow label="最大重试" value={String(settings.llm_max_retries)} />
            </Section>

            <Section title="调度器参数">
              <ReadOnlyRow label="技能权重" value={String(settings.scheduler_skill_weight)} />
              <ReadOnlyRow label="空闲权重" value={String(settings.scheduler_idle_weight)} />
              <ReadOnlyRow label="协作复杂度阈值" value={String(settings.collab_complexity_threshold)} />
              <ReadOnlyRow label="协作负载阈值" value={String(settings.collab_load_threshold)} />
              <ReadOnlyRow label="SubAgent 复杂度阈值" value={String(settings.subagent_complexity_threshold)} />
              <ReadOnlyRow label="SubAgent 可拆解阈值" value={String(settings.subagent_decomposability_threshold)} />
            </Section>

            <Section title="成本估算">
              <ReadOnlyRow label="Token 估算字符比" value={`1/${settings.token_estimate_chars_per_token}`} />
              <ReadOnlyRow label="输入成本/Token" value={`$${settings.default_input_cost_per_token}`} />
              <ReadOnlyRow label="输出成本/Token" value={`$${settings.default_output_cost_per_token}`} />
              <ReadOnlyRow label="Mock 输入成本" value={`$${settings.mock_input_cost_per_token}`} />
              <ReadOnlyRow label="Mock 输出成本" value={`$${settings.mock_output_cost_per_token}`} />
            </Section>

            <Section title="运行时">
              <ReadOnlyRow label="轮询间隔" value={`${settings.run_poll_interval_ms}ms`} />
              <ReadOnlyRow label="取消检查" value={settings.run_cancel_check_enabled ? "开启" : "关闭"} />
              <ReadOnlyRow label="日志级别" value={settings.log_level} />
            </Section>

            <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
              <strong>提示：</strong>大部分配置修改需要编辑项目根目录的 <code>.env</code> 文件并重启服务才能永久生效。
              此处仅支持热切换 Mock 模式等少量配置。
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border">
      <div className="border-b bg-gray-50 px-3 py-2 text-xs font-semibold uppercase text-gray-500">{title}</div>
      <div className="divide-y">{children}</div>
    </div>
  )
}

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2">
      <span className="text-gray-600">{label}</span>
      <span className="font-mono text-gray-900">{value || "-"}</span>
    </div>
  )
}
