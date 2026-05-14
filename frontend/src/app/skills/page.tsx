"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Archive, CheckCircle2, Edit3, Plus, RotateCcw, Save, Search, Trash2, XCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import type { AgentSkill, SkillOwner } from "@/lib/types"

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
  disabled: "停用",
  archived: "归档",
}

const OWNER_SCOPE_LABELS: Record<string, string> = {
  advisor: "导师",
  graduate_agent: "研究生",
  undergraduate_subagent: "本科 SubAgent",
}

function formatSkillTime(value?: string | null) {
  if (!value) return "从未使用"
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

type Notice = {
  id: number
  text: string
}

export default function SkillsPage() {
  const [owners, setOwners] = useState<SkillOwner[]>([])
  const [skills, setSkills] = useState<AgentSkill[]>([])
  const [agentFilter, setAgentFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<AgentSkill | null>(null)
  const [checkedIds, setCheckedIds] = useState<string[]>([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [notices, setNotices] = useState<Notice[]>([])

  const ownerById = useMemo(() => new Map(owners.map((owner) => [owner.id, owner])), [owners])
  const ownerName = (id: string) => ownerById.get(id)?.name || id
  const checkedSet = useMemo(() => new Set(checkedIds), [checkedIds])
  const allVisibleChecked = skills.length > 0 && skills.every((skill) => checkedSet.has(skill.id))

  const notify = (text: string) => {
    setNotices((current) => [...current, { id: Date.now() + Math.random(), text }])
  }

  useEffect(() => {
    if (notices.length === 0) return
    const timer = window.setTimeout(() => {
      setNotices((current) => current.slice(1))
    }, 2400)
    return () => window.clearTimeout(timer)
  }, [notices])

  const load = useCallback(async () => {
    const [ownersResult, skillsResult] = await Promise.all([
      api.getAgentSkillOwners(),
      api.getAgentSkills({ agent_id: agentFilter || undefined, status: statusFilter || undefined, q: query || undefined }),
    ])
    setOwners(ownersResult.owners)
    setSkills(skillsResult.skills)
  }, [agentFilter, query, statusFilter])

  const refresh = () => {
    load().catch((err) => notify(err instanceof Error ? err.message : "刷新失败"))
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      load().catch((err) => notify(err instanceof Error ? err.message : "加载 Skill 失败，请确认后端已重启并包含 /api/agent-skills/owners"))
    }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const startCreate = () => {
    setSelected(null)
    setForm({ ...EMPTY_FORM, agent_id: agentFilter || owners[0]?.id || "advisor" })
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
      title: form.title.trim(),
      description: form.description.trim(),
      content: form.content.trim(),
      status: form.status,
      confidence: Number(form.confidence),
      tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
    }
    if (!payload.agent_id || !payload.title || !payload.content) {
      notify("请选择 Agent，并填写标题和内容")
      return
    }
    try {
      const result = selected
        ? await api.updateAgentSkill(selected.id, payload)
        : await api.createAgentSkill(payload)
      setSelected(result.skill)
      startEdit(result.skill)
      notify("Skill 已保存")
      await load()
    } catch (err) {
      notify(err instanceof Error ? err.message : "Skill 保存失败")
    }
  }

  const archiveSkill = async (skill: AgentSkill) => {
    if (!window.confirm(`确认归档 Skill「${skill.title}」？归档后不会被后续任务使用。`)) return
    await api.archiveAgentSkill(skill.id)
    notify("Skill 已归档")
    refresh()
  }

  const deleteSkill = async (skill: AgentSkill) => {
    if (!window.confirm(`确认删除 Skill「${skill.title}」？删除后会移除数据库记录和对应文件，不能从归档中恢复。`)) return
    await api.deleteAgentSkill(skill.id)
    notify("Skill 已删除")
    setCheckedIds((current) => current.filter((id) => id !== skill.id))
    if (selected?.id === skill.id) startCreate()
    refresh()
  }

  const setStatus = async (skill: AgentSkill, status: "active" | "disabled") => {
    if (status === "active") await api.enableAgentSkill(skill.id)
    else await api.disableAgentSkill(skill.id)
    notify(status === "active" ? "Skill 已启用" : "Skill 已停用")
    refresh()
  }

  const restore = async (skill: AgentSkill) => {
    await api.restoreAgentSkill(skill.id)
    notify("Skill 已恢复")
    refresh()
  }

  const toggleChecked = (skillId: string) => {
    setCheckedIds((current) => current.includes(skillId) ? current.filter((id) => id !== skillId) : [...current, skillId])
  }

  const selectedSkills = () => skills.filter((skill) => checkedSet.has(skill.id))

  const runBulk = async (action: "enable" | "disable" | "archive" | "delete") => {
    const targets = selectedSkills()
    if (targets.length === 0) return
    if (action === "delete" && !window.confirm(`确认删除选中的 ${targets.length} 条 Skill？删除后不能从归档中恢复。`)) return
    if (action === "archive" && !window.confirm(`确认归档选中的 ${targets.length} 条 Skill？归档后不会被后续任务使用。`)) return

    try {
      if (action === "enable") await Promise.all(targets.map((skill) => api.enableAgentSkill(skill.id)))
      if (action === "disable") await Promise.all(targets.map((skill) => api.disableAgentSkill(skill.id)))
      if (action === "archive") await Promise.all(targets.map((skill) => api.archiveAgentSkill(skill.id)))
      if (action === "delete") await Promise.all(targets.map((skill) => api.deleteAgentSkill(skill.id)))
      const actionLabel = action === "enable" ? "启用" : action === "disable" ? "停用" : action === "archive" ? "归档" : "删除"
      notify(`已${actionLabel} ${targets.length} 条 Skill`)
      setCheckedIds([])
      if (selected && targets.some((skill) => skill.id === selected.id)) startCreate()
      await load()
    } catch (err) {
      notify(err instanceof Error ? err.message : "批量操作失败")
    }
  }

  return (
    <div className="page-stack">
      <div className="page-hero flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">Agent Skill Library</div>
          <h1 className="page-title">Agent Skills</h1>
          <p className="page-copy">管理导师、研究生 Agent 和本科 SubAgent 共享池的技能沉淀。只有启用状态的 Skill 会被后续任务使用。</p>
        </div>
        <Button onClick={startCreate}>
          <Plus className="mr-2 size-4" />
          新增 Skill
        </Button>
      </div>

      {notices.length > 0 && (
        <div className="space-y-2">
          {notices.map((notice) => (
            <div key={notice.id} className="info-banner px-3 py-2 text-sm">{notice.text}</div>
          ))}
        </div>
      )}

      <Card className="surface-card">
        <CardContent className="flex flex-wrap gap-3 pt-6">
          <select value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} className="control-input h-9 px-3 text-sm">
            <option value="">全部 Agent</option>
            {owners.map((owner) => (
              <option key={owner.id} value={owner.id}>
                {owner.name}
              </option>
            ))}
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="control-input h-9 px-3 text-sm">
            <option value="">全部状态</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <div className="control-input flex h-9 min-w-64 items-center gap-2 px-3">
            <Search className="size-4 text-[var(--rg-muted)]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、描述或标签" className="w-full bg-transparent text-sm outline-none" />
          </div>
          <Button variant="outline" onClick={refresh}>刷新</Button>
        </CardContent>
      </Card>

      {checkedIds.length > 0 && (
        <div className="surface-card flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="text-sm text-[var(--rg-body)]">已选择 {checkedIds.length} 条 Skill</div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => runBulk("enable")}><CheckCircle2 className="mr-2 size-4" />批量启用</Button>
            <Button variant="outline" size="sm" onClick={() => runBulk("disable")}><XCircle className="mr-2 size-4" />批量停用</Button>
            <Button variant="outline" size="sm" onClick={() => runBulk("archive")}><Archive className="mr-2 size-4" />批量归档</Button>
            <Button variant="destructive" size="sm" onClick={() => runBulk("delete")}><Trash2 className="mr-2 size-4" />批量删除</Button>
            <Button variant="ghost" size="sm" onClick={() => setCheckedIds([])}>取消选择</Button>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-3">
          {skills.length > 0 && (
            <label className="flex w-fit items-center gap-2 text-sm text-[var(--rg-muted)]">
              <input
                type="checkbox"
                checked={allVisibleChecked}
                onChange={(event) => setCheckedIds(event.target.checked ? skills.map((skill) => skill.id) : [])}
              />
              选择当前列表全部 Skill
            </label>
          )}
          {skills.map((skill) => (
            <Card key={skill.id} className="surface-card transition-shadow hover:shadow-md">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 gap-3">
                    <input
                      type="checkbox"
                      className="mt-1 size-4"
                      checked={checkedSet.has(skill.id)}
                      onChange={() => toggleChecked(skill.id)}
                      aria-label={`选择 ${skill.title}`}
                    />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold text-[var(--rg-ink)]">{skill.title}</h2>
                        <Badge variant="outline">{STATUS_LABELS[skill.status] || skill.status}</Badge>
                        <Badge variant="outline">{ownerName(skill.agent_id)}</Badge>
                      </div>
                      <p className="mt-1 text-sm text-[var(--rg-muted)]">{skill.description || "暂无描述"}</p>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--rg-muted)]">
                        <span>置信度 {Math.round(skill.confidence * 100)}%</span>
                        <span>使用 {skill.usage_count}</span>
                        <span>最近使用 {formatSkillTime(skill.last_used_at)}</span>
                        <span>失败 {skill.failure_count}</span>
                        <span>更新 {new Date(skill.updated_at).toLocaleString()}</span>
                      </div>
                      {skill.tags.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {skill.tags.map((tag) => <span key={tag} className="rounded-full bg-[var(--rg-surface-soft)] px-2 py-0.5 text-xs text-[var(--rg-body)]">{tag}</span>)}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => startEdit(skill)}><Edit3 className="mr-2 size-4" />编辑</Button>
                    {skill.status === "archived" ? (
                      <Button variant="outline" onClick={() => restore(skill)}><RotateCcw className="mr-2 size-4" />恢复</Button>
                    ) : (
                      <>
                        {skill.status === "active" ? (
                          <Button variant="outline" onClick={() => setStatus(skill, "disabled")}><XCircle className="mr-2 size-4" />停用</Button>
                        ) : (
                          <Button variant="outline" onClick={() => setStatus(skill, "active")}><CheckCircle2 className="mr-2 size-4" />启用</Button>
                        )}
                        <Button variant="outline" onClick={() => archiveSkill(skill)}><Archive className="mr-2 size-4" />归档</Button>
                      </>
                    )}
                    <Button variant="destructive" onClick={() => deleteSkill(skill)}><Trash2 className="mr-2 size-4" />删除</Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {skills.length === 0 && (
            <Card className="surface-card">
              <CardContent className="p-8 text-center text-sm text-[var(--rg-muted)]">暂无 Skill，点击右上角新增一个。</CardContent>
            </Card>
          )}
        </div>

        <Card className="surface-card h-fit">
          <CardHeader>
            <CardTitle className="text-base">{selected ? "编辑 Skill" : "新增 Skill"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Field label="Agent" as="select" value={form.agent_id} onChange={(value) => setForm({ ...form, agent_id: value })}>
              <option value="">请选择 Agent</option>
              {owners.map((owner) => (
                <option key={owner.id} value={owner.id}>
                  {owner.name} · {OWNER_SCOPE_LABELS[owner.scope] || owner.scope}
                </option>
              ))}
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
              <textarea value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} rows={12} className="control-input w-full px-3 py-2 text-sm" />
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
      <span className="mb-1 block text-xs font-medium text-[var(--rg-muted)]">{label}</span>
      {as === "select" ? (
        <select value={value} onChange={(event) => onChange(event.target.value)} className="control-input h-9 w-full px-3 text-sm">
          {children}
        </select>
      ) : (
        <input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="control-input h-9 w-full px-3 text-sm" />
      )}
    </label>
  )
}
