const API_BASE = 'http://localhost:8000/api'

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => fetchApi<{ status: string; mock_mode: boolean }>('/health'),

  // Agents
  getAgents: () => fetchApi<{ agents: any[] }>('/agents'),
  getAgent: (id: string) => fetchApi<{ agent: any }>(`/agents/${id}`),

  // Tasks
  getTasks: (runId?: string) =>
    fetchApi<{ tasks: any[] }>(`/tasks${runId ? `?run_id=${runId}` : ''}`),
  getTask: (id: string) => fetchApi<{ task: any }>(`/tasks/${id}`),

  // Runs
  createRun: (researchGoal: string) =>
    fetchApi<{ run_id: string; status: string }>('/runs', {
      method: 'POST',
      body: JSON.stringify({ research_goal: researchGoal }),
    }),
  getRun: (id: string) => fetchApi<{ run: any; tasks: any[] }>(`/runs/${id}`),
  getRuns: () => fetchApi<{ runs: any[] }>('/runs'),
  runAll: (id: string) =>
    fetchApi<any>(`/runs/${id}/run_all`, { method: 'POST' }),

  // Outputs
  getOutputs: (runId?: string) =>
    fetchApi<{ outputs: any[] }>(`/outputs${runId ? `?run_id=${runId}` : ''}`),
  getOutput: (id: string) => fetchApi<{ output: any }>(`/outputs/${id}`),
}
