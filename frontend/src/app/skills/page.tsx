"use client"

import { useEffect, useMemo, useState } from "react"
import { Archive, CheckCircle2, Edit3, Plus, RotateCcw, Save, Search, XCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import type { AgentSkill, GraduateAgent } from "@/lib/types"

const EMPTY_FORM = {
  id: "",
  agent_id: "",
  title: "",
  description: "",
  content: "",
  status: "active" as AgentSkill["status"],
  confidence: 1,
  tags: "",
}

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  active: "启用",
  disabled: "禁用",
  archived: "归档",
}

export default function SkillsPage() {
  const [agents, setAgents] = useState<GraduateAgent[]>([])
  const [skills, setSkills] = useState<AgentSkill[]>([])
  const [agentFilter, setAgentFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<AgentSkill | null>(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [message, setMessage] = useState("")

  const agentOptions = useMemo(() => [{ id: "advisor", name: "导师 Agent" }, ...agents], [agents])
  const agentName = (id: string) => agentOptions.find((agent) => agent.id === id)?.name || id

  async function load() {
    const [{ agents }, { skills }] = await Promise.all([
      api.getAgents(),
      api.getAgentSkills({ agent_id: agentFilter || undefined, status: statusFilter || undefined, q: query || undefined }),
    ])
    setAgents(agents)
    setSkills(skills)
  }

  function refresh() {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "刷新失败"))
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      load().catch((err) => setMessage(err instanceof Error ? err.message : "加载 Skill 失败"))
    }, 0)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentFilter, statusFilter])

  const startCreate = () => {
    setSelected(null)
    setForm({ ...EMPTY_FORM, agent_id: agentFilter || "advisor" })
  }

  const startEdit = (skill: AgentSkill) => {
    setSelected(skill)
    setForm({
      id: skill.id,
      agent_id: skill.agent_id,
      title: skill.title,
      description: skill.description,
      content: skill.content,
      status: skill.status,
      confidence: skill.confidence,
      tags: skill.tags.join(", "),
    })
  }

  const save = async () => {
    const payload = {
      agent_id: form.agent_id,
      title: form.title,
      description: form.description,
      content: form.content,
      status: form.status,
      confidence: Number(form.confidence),
      tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
    }
    if (!payload.agent_id || !payload.title || !payload.content) {
      setMessage("Agent、标题和内容不能为空")
      return
    }
    const result = selected
      ? await api.updateAgentSkill(selected.id, payload)
      : await api.createAgentSkill(payload)
    setSelected(result.skill)
    startEdit(result.skill)
    setMessage("Skill 已保存")
    refresh()
  }

  const archiveSkill = async (skill: AgentSkill) => {
    if (!window.confirm(`确认归档 Skill：${skill.title}？归档后不会参与 Agent 上下文注入。`)) return
    await api.archiveAgentSkill(skill.id)
    setMessage("Skill 已归档")
    refresh()
  }

  const setStatus = async (skill: AgentSkill, status: "active" | "disabled") => {
    if (status === "active") await api.enableAgentSkill(skill.id)
    else await api.disableAgentSkill(skill.id)
    setMessage(status === "active" ? "Skill 已启用" : "Skill 已禁用")
    refresh()
  }

  const restore = async (skill: AgentSkill) => {
    await api.restoreAgentSkill(skill.id)
    setMessage("Skill 已恢复")
    refresh()
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase text-slate-500">Agent Skill Library</div>
          <h1 className="mt-1 text-2xl font-bold text-slate-950">Agent Skills</h1>
          <p className="mt-1 text-sm text-slate-500">管理每个 Agent 的专属技能沉淀。只有启用状态的 skill 才会被后续任务使用。</p>
        </div>
        <Button onClick={startCreate}>
          <Plus className="mr-2 size-4" />
          新增 Skill
        </Button>
      </div>

      {message && <div className="rounded-lg border border-sky-100 bg-sky-50 px-3 py-2 text-sm text-sky-700">{message}</div>}

      <Card>
        <CardContent className="flex flex-wrap gap-3 pt-6">
          <select value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} className="h-9 rounded-lg border border-slate-200 px-3 text-sm">
            <option value="">全部 Agent</option>
            {agentOptions.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="h-9 rounded-lg border border-slate-200 px-3 text-sm">
            <option value="">全部状态</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <div className="flex h-9 min-w-64 items-center gap-2 rounded-lg border border-slate-200 px-3">
            <Search className="size-4 text-slate-400" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、描述或标签" className="w-full text-sm outline-none" />
          </div>
          <Button variant="outline" onClick={refresh}>刷新</Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-3">
          {skills.map((skill) => (
            <Card key={skill.id} className="transition-shadow hover:shadow-md">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold text-slate-950">{skill.title}</h2>
                      <Badge variant="outline">{STATUS_LABELS[skill.status] || skill.status}</Badge>
                      <Badge variant="outline">{agentName(skill.agent_id)}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{skill.description || "暂无描述"}</p>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                      <span>置信度 {Math.round(skill.confidence * 100)}%</span>
                      <span>使用 {skill.usage_count}</span>
                      <span>失败 {skill.failure_count}</span>
                      <span>更新 {new Date(skill.updated_at).toLocaleString()}</span>
                    </div>
                    {skill.tags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {skill.tags.map((tag) => <span key={tag} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{tag}</span>)}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => startEdit(skill)}><Edit3 className="mr-2 size-4" />编辑</Button>
                    {skill.status === "archived" ? (
                      <Button variant="outline" onClick={() => restore(skill)}><RotateCcw className="mr-2 size-4" />恢复</Button>
                    ) : (
                      <>
                        {skill.status === "active" ? (
                          <Button variant="outline" onClick={() => setStatus(skill, "disabled")}><XCircle className="mr-2 size-4" />禁用</Button>
                        ) : (
                          <Button variant="outline" onClick={() => setStatus(skill, "active")}><CheckCircle2 className="mr-2 size-4" />启用</Button>
                        )}
                        <Button variant="outline" onClick={() => archiveSkill(skill)}><Archive className="mr-2 size-4" />归档</Button>
                      </>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {skills.length === 0 && (
            <Card>
              <CardContent className="p-8 text-center text-sm text-slate-500">暂无 Skill，点击右上角新增一个。</CardContent>
            </Card>
          )}
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">{selected ? "编辑 Skill" : "新增 Skill"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Field label="Agent" as="select" value={form.agent_id} onChange={(value) => setForm({ ...form, agent_id: value })}>
              <option value="">请选择 Agent</option>
              {agentOptions.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </Field>
            <Field label="标题" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
            <Field label="描述" value={form.description} onChange={(value) => setForm({ ...form, description: value })} />
            <Field label="标签，逗号分隔" value={form.tags} onChange={(value) => setForm({ ...form, tags: value })} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="状态" as="select" value={form.status} onChange={(value) => setForm({ ...form, status: value as AgentSkill["status"] })}>
                {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </Field>
              <Field label="置信度" type="number" value={String(form.confidence)} onChange={(value) => setForm({ ...form, confidence: Number(value) })} />
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-600">内容</span>
              <textarea value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} rows={12} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
            </label>
            <Button onClick={save} className="w-full">
              <Save className="mr-2 size-4" />
              保存 Skill
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function Field({ label, value, onChange, type = "text", as, children }: { label: string; value: string; onChange: (value: string) => void; type?: string; as?: "select"; children?: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {as === "select" ? (
        <select value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-slate-400">
          {children}
        </select>
      ) : (
        <input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-slate-400" />
      )}
    </label>
  )
}
