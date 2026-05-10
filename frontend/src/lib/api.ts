import type { GraduateAgent, LLMUsage, Output, Run, RunEvent, RunSummary, Task } from "./types"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => fetchApi<{ status: string; mock_mode: boolean; model?: string }>("/health"),

  getAgents: () => fetchApi<{ agents: GraduateAgent[] }>("/agents"),
  getAgent: (id: string) => fetchApi<{ agent: GraduateAgent }>(`/agents/${id}`),

  getTasks: (runId?: string) =>
    fetchApi<{ tasks: Task[] }>(`/tasks${runId ? `?run_id=${runId}` : ""}`),
  getTask: (id: string) => fetchApi<{ task: Task }>(`/tasks/${id}`),

  createRun: (researchGoal: string) =>
    fetchApi<{ run_id: string; status: string }>("/runs", {
      method: "POST",
      body: JSON.stringify({ research_goal: researchGoal }),
    }),
  getRun: (id: string) => fetchApi<{ run: Run; tasks: Task[] }>(`/runs/${id}`),
  getRuns: () => fetchApi<{ runs: Run[] }>("/runs"),
  runAll: (id: string) => fetchApi<unknown>(`/runs/${id}/run_all`, { method: "POST" }),
  startRun: (id: string) => fetchApi<unknown>(`/runs/${id}/start`, { method: "POST" }),
  cancelRun: (id: string) => fetchApi<unknown>(`/runs/${id}/cancel`, { method: "POST" }),
  getRunSummary: (id: string) => fetchApi<RunSummary>(`/runs/${id}/summary`),
  getRunEvents: (id: string, limit = 100) =>
    fetchApi<{ events: RunEvent[]; next_after_id?: string }>(`/runs/${id}/events?limit=${limit}`),
  getRunUsage: (id: string) =>
    fetchApi<{ summary: RunSummary["usage"]; items: LLMUsage[] }>(`/runs/${id}/usage`),

  getOutputs: (runId?: string) =>
    fetchApi<{ outputs: Output[] }>(`/outputs${runId ? `?run_id=${runId}` : ""}`),
  getOutput: (id: string) => fetchApi<{ output: Output }>(`/outputs/${id}`),

  getSettings: () => fetchApi<Record<string, string | number | boolean>>("/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    fetchApi<{ updated: Record<string, unknown>; message: string }>("/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  getOfficeState: (runId: string) =>
    fetchApi<import("./types").OfficeState>(`/monitor/office-state?run_id=${runId}`),
}
