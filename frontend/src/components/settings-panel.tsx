"use client"

import { useEffect, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { KeyRound, Save, Settings, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

type SystemSettings = Record<string, string | number | boolean>

const MODEL_TEXT_FIELDS = [
  ["llm_base_url", "API Base URL", "text"],
  ["llm_model_name", "默认模型", "text"],
  ["advisor_model_name", "导师模型", "text"],
  ["graduate_model_name", "研究生模型", "text"],
  ["subagent_model_name", "SubAgent 模型", "text"],
  ["vision_model_name", "视觉模型", "text"],
  ["log_level", "日志级别", "text"],
] as const

const MODEL_NUMBER_FIELDS = [
  ["llm_timeout", "LLM 超时秒数"],
  ["llm_max_retries", "LLM 重试次数"],
  ["llm_max_tokens", "LLM 最大输出 Tokens"],
  ["advisor_temperature", "导师温度"],
  ["graduate_temperature", "研究生温度"],
  ["subagent_temperature", "SubAgent 温度"],
] as const

const RUNTIME_NUMBER_FIELDS = [
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
] as const

const COST_NUMBER_FIELDS = [
  ["default_input_cost_per_token", "输入单 Token 成本"],
  ["default_output_cost_per_token", "输出单 Token 成本"],
  ["mock_input_cost_per_token", "Mock 输入单 Token 成本"],
  ["mock_output_cost_per_token", "Mock 输出单 Token 成本"],
] as const

const SKILL_NUMBER_FIELDS = [
  ["skill_min_confidence", "Skill 最低置信度"],
  ["skill_max_injected", "每次最多注入 Skill 数"],
] as const

const EXPERIMENT_TEXT_FIELDS = [
  ["experiment_workspace_dir", "实验 workspace"],
  ["experiment_execution_backend", "执行后端"],
  ["experiment_env_file", "环境变量文件"],
  ["experiment_remote_host", "远程服务器地址"],
  ["experiment_docker_image", "Docker 镜像"],
  ["experiment_queue_backend", "队列后端"],
] as const

const EXPERIMENT_NUMBER_FIELDS = [
  ["experiment_command_timeout_seconds", "命令超时秒数"],
  ["experiment_max_output_chars", "最大输出字符"],
  ["experiment_remote_port", "远程端口"],
] as const

export function SettingsButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button onClick={() => setOpen(true)} className="rounded-lg p-2 text-[var(--rg-muted)] hover:bg-[var(--rg-surface-card)] hover:text-[var(--rg-ink)]" title="系统设置">
        <Settings className="size-5" />
      </button>
      {open && createPortal(<SettingsPanel onClose={() => setOpen(false)} />, document.body)}
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1011]/55 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="surface-card max-h-[88vh] w-full max-w-5xl overflow-auto p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-[var(--rg-ink)]">系统设置</h2>
            <p className="mt-1 text-sm text-[var(--rg-muted)]">这里的修改会同步写入项目根目录 .env。密钥只写入，不回显。</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-[var(--rg-muted)] hover:bg-[var(--rg-surface-soft)] hover:text-[var(--rg-ink)]">
            <X className="size-4" />
          </button>
        </div>

        {message && <div className="info-banner mb-4 p-3 text-sm">{message}</div>}

        {loading && <div className="soft-card p-4 text-sm text-[var(--rg-muted)]">正在读取系统设置...</div>}

        {draft && (
          <div className="space-y-4 text-sm">
            <Section title="运行开关">
              <div className="grid gap-3 md:grid-cols-2">
                <ToggleRow label="Mock 模式" description="开启后使用本地模拟结果，不调用真实 LLM。" checked={Boolean(draft.mock_mode)} onChange={(value) => setValue("mock_mode", value)} />
                <ToggleRow label="运行取消检查" description="开启后执行链路会在阶段边界响应取消。" checked={Boolean(draft.run_cancel_check_enabled)} onChange={(value) => setValue("run_cancel_check_enabled", value)} />
                <ToggleRow label="多模态输入" description="开启后允许图片进入可用性检查，需配置视觉模型。" checked={Boolean(draft.multimodal_enabled)} onChange={(value) => setValue("multimodal_enabled", value)} />
                <ToggleRow label="Agent Skill 系统" description="开启后允许维护和使用 Agent 专属 skill。" checked={Boolean(draft.agent_skill_enabled)} onChange={(value) => setValue("agent_skill_enabled", value)} />
                <ToggleRow label="自动沉淀 Skill" description="开启后任务完成时会生成并评估 skill 候选。" checked={Boolean(draft.skill_auto_capture_enabled)} onChange={(value) => setValue("skill_auto_capture_enabled", value)} />
                <ToggleRow label="Skill 敏感信息扫描" description="开启后写入 skill 前会过滤密钥、环境变量和隐私内容。" checked={Boolean(draft.skill_sensitive_scan_enabled)} onChange={(value) => setValue("skill_sensitive_scan_enabled", value)} />
                <ToggleRow label="实验执行器" description="开启后实验 Agent 可以提交待审查实验计划。" checked={Boolean(draft.experiment_execution_enabled)} onChange={(value) => setValue("experiment_execution_enabled", value)} />
                <ToggleRow label="实验强制审查" description="开启后所有实验计划都必须用户确认后执行。" checked={Boolean(draft.experiment_require_review)} onChange={(value) => setValue("experiment_require_review", value)} />
                <ToggleRow label="允许实验联网" description="仅影响风险扫描，危险命令仍会要求确认。" checked={Boolean(draft.experiment_allow_network)} onChange={(value) => setValue("experiment_allow_network", value)} />
                <ToggleRow label="允许安装依赖" description="允许 pip/npm/conda 安装类命令进入可审查流程。" checked={Boolean(draft.experiment_allow_package_install)} onChange={(value) => setValue("experiment_allow_package_install", value)} />
              </div>
            </Section>

            <Section title="模型与 API">
              <div className="soft-card mb-3 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-[var(--rg-muted)]">
                  <KeyRound className="size-4" />
                  LLM API Key
                  {draft.has_llm_api_key ? <span className="rounded-full bg-[#f0fbf2] px-2 py-0.5 text-[#2f7341]">{String(draft.llm_api_key_masked)}</span> : <span className="rounded-full bg-white px-2 py-0.5 text-[var(--rg-muted)]">未配置</span>}
                </div>
                <input
                  type="password"
                  value={apiKeyDraft}
                  placeholder="留空表示不修改现有密钥"
                  onChange={(event) => setApiKeyDraft(event.target.value)}
                  className="control-input h-9 w-full px-3 text-sm"
                />
                <label className="mt-2 flex items-center gap-2 text-xs text-[var(--rg-muted)]">
                  <input type="checkbox" checked={clearApiKey} onChange={(event) => setClearApiKey(event.target.checked)} />
                  清空当前 API Key
                </label>
              </div>
              <FieldGrid fields={MODEL_TEXT_FIELDS} draft={draft} setValue={setValue} />
              <FieldGrid fields={MODEL_NUMBER_FIELDS} draft={draft} setValue={setValue} type="number" />
            </Section>

            <Section title="调度、运行与成本">
              <FieldGrid fields={RUNTIME_NUMBER_FIELDS} draft={draft} setValue={setValue} type="number" />
              <FieldGrid fields={COST_NUMBER_FIELDS} draft={draft} setValue={setValue} type="number" />
            </Section>

            <Section title="Agent Skill">
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="默认 Skill 状态" type="text" value={String(draft.skill_default_status ?? "")} onChange={(value) => setValue("skill_default_status", value)} />
                {SKILL_NUMBER_FIELDS.map(([key, label]) => (
                  <Field key={key} label={label} type="number" value={String(draft[key] ?? "")} onChange={(value) => setValue(key, Number(value))} />
                ))}
              </div>
            </Section>

            <Section title="实验执行器">
              <FieldGrid fields={EXPERIMENT_TEXT_FIELDS} draft={draft} setValue={setValue} />
              <FieldGrid fields={EXPERIMENT_NUMBER_FIELDS} draft={draft} setValue={setValue} type="number" />
            </Section>

            <div className="rounded-lg border border-[#f1d3a3] bg-[#fff6e8] p-3 text-xs leading-6 text-[#8b5a14]">
              修改模型、端口、跨域、实验 workspace 等启动或运行参数后，建议重启后端和前端服务。实验执行器默认关闭，开启后仍会经过审查和风险扫描。
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

function FieldGrid({ fields, draft, setValue, type = "text" }: { fields: readonly (readonly [string, string, string?])[]; draft: SystemSettings; setValue: (key: string, value: string | number | boolean) => void; type?: string }) {
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      {fields.map(([key, label, fieldType]) => (
        <Field key={key} label={label} type={fieldType || type} value={String(draft[key] ?? "")} onChange={(value) => setValue(key, (fieldType || type) === "number" ? Number(value) : value)} />
      ))}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--rg-hairline)]">
      <div className="border-b border-[var(--rg-hairline)] bg-[var(--rg-surface-soft)] px-3 py-2 text-xs font-semibold uppercase text-[var(--rg-muted)]">{title}</div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function Field({ label, type, value, onChange }: { label: string; type: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--rg-muted)]">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="control-input h-9 w-full px-3 text-sm"
      />
    </label>
  )
}

function ToggleRow({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-[var(--rg-hairline)] bg-white/55 p-3">
      <div>
        <div className="font-medium text-[var(--rg-ink)]">{label}</div>
        <div className="text-xs text-[var(--rg-muted)]">{description}</div>
      </div>
      <button type="button" onClick={() => onChange(!checked)} className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-[var(--rg-linear)]" : "bg-[var(--rg-surface-card)]"}`}>
        <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${checked ? "translate-x-5" : ""}`} />
      </button>
    </div>
  )
}
