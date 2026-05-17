import type {
  AgentSkill,
  ApprovalRequest,
  DashboardOverview,
  EvidenceAssessment,
  EvidenceClaim,
  EvidenceExcerpt,
  EvidenceLink,
  EvidenceSource,
  ExperimentPlan,
  ExperimentProtocol,
  ExperimentResultRecord,
  ExperimentFinding,
  GraduateAgent,
  LLMUsage,
  MemoryRecord,
  Output,
  ResearchState,
  ResearchLoopSnapshot,
  ReviewDecision,
  Run,
  RunEvent,
  RunSummary,
  SkillOwner,
  Task,
  TaskAttempt,
  TaskCreateInput,
  TaskGraph,
} from "./types"
import { frontendLogger } from "./logger"
import { requestCache } from "./request-cache"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"
const CACHE_TTL = {
  volatile: 4_000,
  shared: 8_000,
  catalog: 30_000,
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method || "GET"
  frontendLogger.info(`API ${method} ${path}`)
  const start = performance.now()
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  const duration = Math.round(performance.now() - start)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }))
    frontendLogger.error(`API ${method} ${path} failed | status=${res.status} | duration=${duration}ms`)
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  frontendLogger.info(`API ${method} ${path} success | status=${res.status} | duration=${duration}ms`)
  return res.json()
}

function fetchCachedApi<T>(path: string, ttlMs = CACHE_TTL.shared): Promise<T> {
  return requestCache.get(`GET:${path}`, () => fetchApi<T>(path), ttlMs)
}

function invalidateCaches(...prefixes: string[]) {
  prefixes.forEach((prefix) => requestCache.invalidate(`GET:${prefix}`))
}

export const api = {
  health: () => fetchApi<{ status: string; mock_mode: boolean; model?: string }>("/health"),

  getAgents: () => fetchCachedApi<{ agents: GraduateAgent[] }>("/agents", CACHE_TTL.catalog),
  getAgent: (id: string) => fetchApi<{ agent: GraduateAgent }>(`/agents/${id}`),

  getAgentSkills: (params: { agent_id?: string; status?: string; q?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.agent_id) query.set("agent_id", params.agent_id)
    if (params.status) query.set("status", params.status)
    if (params.q) query.set("q", params.q)
    const suffix = query.toString() ? `?${query.toString()}` : ""
    return fetchApi<{ skills: AgentSkill[] }>(`/agent-skills${suffix}`)
  },
  getAgentSkill: (id: string) => fetchApi<{ skill: AgentSkill }>(`/agent-skills/${id}`),
  getAgentSkillOwners: () => fetchApi<{ owners: SkillOwner[] }>("/agent-skills/owners"),
  createAgentSkill: (body: Partial<AgentSkill>) =>
    fetchApi<{ skill: AgentSkill }>("/agent-skills", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateAgentSkill: (id: string, body: Partial<AgentSkill>) =>
    fetchApi<{ skill: AgentSkill }>(`/agent-skills/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  archiveAgentSkill: (id: string) => fetchApi<{ skill: AgentSkill }>(`/agent-skills/${id}`, { method: "DELETE" }),
  deleteAgentSkill: (id: string) => fetchApi<{ id: string; deleted: boolean }>(`/agent-skills/${id}/physical`, { method: "DELETE" }),
  restoreAgentSkill: (id: string) => fetchApi<{ skill: AgentSkill }>(`/agent-skills/${id}/restore`, { method: "POST" }),
  enableAgentSkill: (id: string) => fetchApi<{ skill: AgentSkill }>(`/agent-skills/${id}/enable`, { method: "POST" }),
  disableAgentSkill: (id: string) => fetchApi<{ skill: AgentSkill }>(`/agent-skills/${id}/disable`, { method: "POST" }),

  getExperimentConfig: () => fetchApi<{ config: Record<string, string | number | boolean> }>("/experiments/config"),
  updateExperimentConfig: (body: Record<string, unknown>) =>
    fetchApi<{ updated: Record<string, unknown> }>("/experiments/config", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  getExperimentPlans: (params: { run_id?: string; task_id?: string; status?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.run_id) query.set("run_id", params.run_id)
    if (params.task_id) query.set("task_id", params.task_id)
    if (params.status) query.set("status", params.status)
    const suffix = query.toString() ? `?${query.toString()}` : ""
    return fetchApi<{ plans: ExperimentPlan[] }>(`/experiments/plans${suffix}`)
  },
  getExperimentProtocols: (runId: string) => fetchApi<{ protocols: ExperimentProtocol[] }>(`/experiments/protocols?run_id=${runId}`),
  getExperimentResults: (runId: string) => fetchApi<{ results: ExperimentResultRecord[] }>(`/experiments/results?run_id=${runId}`),
  getExperimentFindings: (runId: string) => fetchApi<{ findings: ExperimentFinding[] }>(`/experiments/findings?run_id=${runId}`),
  createExperimentPlan: (body: Partial<ExperimentPlan>) =>
    fetchApi<{ plan: ExperimentPlan }>("/experiments/plans", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateExperimentPlan: (id: string, body: Partial<ExperimentPlan>) =>
    fetchApi<{ plan: ExperimentPlan }>(`/experiments/plans/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  scanExperimentPlan: (id: string) => fetchApi<{ plan: ExperimentPlan }>(`/experiments/plans/${id}/scan`, { method: "POST" }),
  approveExperimentPlan: (id: string, approvedBy = "user") =>
    fetchApi<{ plan: ExperimentPlan }>(`/experiments/plans/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: approvedBy }),
    }),
  rejectExperimentPlan: (id: string, reason = "") =>
    fetchApi<{ plan: ExperimentPlan }>(`/experiments/plans/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  executeExperimentPlan: (id: string) => fetchApi<{ plan: ExperimentPlan }>(`/experiments/plans/${id}/execute`, { method: "POST" }),

  getTasks: (runId?: string) =>
    fetchCachedApi<{ tasks: Task[] }>(`/tasks${runId ? `?run_id=${runId}` : ""}`, CACHE_TTL.shared),
  createTask: (body: TaskCreateInput) =>
    fetchApi<{ task: Task; graph: TaskGraph }>("/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/", "/dashboard/")
      return result
    }),
  getTask: (id: string) => fetchApi<{ task: Task }>(`/tasks/${id}`),
  updateTaskDependencies: (id: string, dependsOnTaskIds: string[]) =>
    fetchApi<TaskGraph>(`/tasks/${id}/dependencies`, {
      method: "PATCH",
      body: JSON.stringify({ depends_on_task_ids: dependsOnTaskIds }),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/")
      return result
    }),
  retryTask: (id: string, reason = "") =>
    fetchApi<{ task: Task }>(`/tasks/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/")
      return result
    }),
  resumeTask: (id: string, reason = "") =>
    fetchApi<{ task: Task }>(`/tasks/${id}/resume`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/")
      return result
    }),
  rerunTaskBranch: (id: string, reason = "") =>
    fetchApi<{ task: Task }>(`/tasks/${id}/rerun-branch`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/")
      return result
    }),
  approveTask: (id: string, reason = "") =>
    fetchApi<{ task: Task }>(`/tasks/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/")
      return result
    }),
  requestTaskRevision: (id: string, reason = "") =>
    fetchApi<{ task: Task; revision_task: Task; approval_request: ApprovalRequest }>(`/tasks/${id}/request-revision`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }).then((result) => {
      invalidateCaches("/tasks", "/runs/")
      return result
    }),

  createRun: (researchGoal: string, attachments: Record<string, unknown>[] = []) =>
    fetchApi<{ run_id: string; status: string; display_name?: string; artifact_dir?: string }>("/runs", {
      method: "POST",
      body: JSON.stringify({ research_goal: researchGoal, attachments }),
    }).then((result) => {
      invalidateCaches("/runs", "/dashboard/")
      return result
    }),
  preflightRun: (researchGoal: string, attachments: Record<string, unknown>[] = []) =>
    fetchApi<{
      ok: boolean
      errors: string[]
      warnings: string[]
      supports_pdf_extract: boolean
      supports_image: boolean
    }>("/runs/preflight", {
      method: "POST",
      body: JSON.stringify({ research_goal: researchGoal, attachments }),
    }),
  getRun: (id: string) => fetchApi<{ run: Run; tasks: Task[] }>(`/runs/${id}`),
  getRuns: () => fetchCachedApi<{ runs: Run[] }>("/runs", CACHE_TTL.volatile),
  runAll: (id: string) =>
    fetchApi<unknown>(`/runs/${id}/run_all`, { method: "POST" }).then((result) => {
      invalidateCaches("/runs", "/tasks", "/dashboard/")
      return result
    }),
  startRun: (id: string) =>
    fetchApi<unknown>(`/runs/${id}/start`, { method: "POST" }).then((result) => {
      invalidateCaches("/runs", "/dashboard/")
      return result
    }),
  cancelRun: (id: string) =>
    fetchApi<unknown>(`/runs/${id}/cancel`, { method: "POST" }).then((result) => {
      invalidateCaches("/runs", "/dashboard/")
      return result
    }),
  deleteRun: (id: string) =>
    fetchApi<{ deleted: boolean; run_id: string }>(`/runs/${id}`, { method: "DELETE" }).then((result) => {
      invalidateCaches("/runs", "/tasks", "/outputs", "/dashboard/")
      return result
    }),
  getRunSummary: (id: string) => fetchApi<RunSummary>(`/runs/${id}/summary`),
  getRunEvents: (id: string, limit = 100) =>
    fetchApi<{ events: RunEvent[]; next_after_id?: string }>(`/runs/${id}/events?limit=${limit}`),
  getRunUsage: (id: string) =>
    fetchApi<{ summary: RunSummary["usage"]; items: LLMUsage[] }>(`/runs/${id}/usage`),
  getRunGraph: (id: string) => fetchCachedApi<TaskGraph>(`/runs/${id}/graph`, CACHE_TTL.shared),
  getRunMemory: (id: string) => fetchApi<{ items: MemoryRecord[] }>(`/runs/${id}/memory`),
  getRunEvidence: (id: string) =>
    fetchApi<{
      sources: EvidenceSource[]
      claims: EvidenceClaim[]
      excerpts: EvidenceExcerpt[]
      assessments: EvidenceAssessment[]
      links: EvidenceLink[]
    }>(`/runs/${id}/evidence`),
  getRunResearchState: (id: string) => fetchApi<ResearchState>(`/runs/${id}/research-state`),
  getRunResearchLoop: (id: string) => fetchApi<ResearchLoopSnapshot>(`/runs/${id}/research-loop`),
  createRunEvidenceSource: (id: string, body: Partial<EvidenceSource>) =>
    fetchApi<{ source: EvidenceSource }>(`/runs/${id}/evidence/sources`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getRunReviews: (id: string) => fetchApi<{ items: ReviewDecision[] }>(`/runs/${id}/reviews`),
  getRunAttempts: (id: string) => fetchApi<{ items: TaskAttempt[] }>(`/runs/${id}/attempts`),
  getRunApprovals: (id: string) => fetchApi<{ items: ApprovalRequest[] }>(`/runs/${id}/approvals`),
  resolveApproval: (id: string, approved: boolean) =>
    fetchApi<{ request: ApprovalRequest }>(`/runs/approvals/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),

  getOutputs: (runId?: string) =>
    fetchCachedApi<{ outputs: Output[] }>(`/outputs${runId ? `?run_id=${runId}` : ""}`, CACHE_TTL.shared),
  getOutput: (id: string) => fetchApi<{ output: Output }>(`/outputs/${id}`),

  getSettings: () => fetchApi<Record<string, string | number | boolean>>("/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    fetchApi<{ updated: Record<string, unknown>; message: string }>("/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  getOfficeState: (runId: string) =>
    fetchApi<import("./types").OfficeState>(`/monitor/office-state?run_id=${runId}`),

  getDashboardOverview: (runId?: string) =>
    fetchCachedApi<DashboardOverview>(`/dashboard/overview${runId ? `?run_id=${runId}` : ""}`, CACHE_TTL.volatile),
}
