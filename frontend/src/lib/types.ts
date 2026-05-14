export interface SkillSet {
  literature_review: number
  coding: number
  experiment: number
  data_analysis: number
  academic_writing: number
  mentoring: number
}

export interface GraduateAgent {
  id: string
  name: string
  type: string
  description: string
  skills: SkillSet
  status: "idle" | "working" | "waiting" | "reviewing" | "blocked" | "finished"
  current_load: number
  max_load: number
  current_tasks: string[]
  preferred_task_types: string[]
  tools: string[]
  can_create_subagents: boolean
  max_subagents: number
}

export interface AgentSkill {
  id: string
  agent_id: string
  title: string
  description: string
  content: string
  status: "draft" | "active" | "disabled" | "archived"
  confidence: number
  source_run_id: string | null
  source_task_id: string | null
  tags: string[]
  file_path: string
  usage_count: number
  failure_count: number
  created_at: string
  updated_at: string
  last_used_at: string | null
}

export interface ExperimentFile {
  path: string
  content: string
}

export interface ExperimentCommand {
  command: string
  description?: string
}

export interface ExperimentPlan {
  id: string
  run_id: string | null
  task_id: string | null
  agent_id: string
  title: string
  objective: string
  workspace_dir: string
  files: ExperimentFile[]
  commands: ExperimentCommand[]
  env_vars: Record<string, string>
  risk_level: "safe" | "needs_review" | "dangerous"
  risk_reasons: string[]
  status: "draft" | "needs_review" | "approved" | "rejected" | "running" | "completed" | "failed"
  result: {
    exit_code: number | null
    stdout: string
    stderr: string
    elapsed_ms: number
    command_results: Record<string, unknown>[]
  } | null
  artifacts: string[]
  created_at: string
  updated_at: string
  approved_at: string | null
  approved_by: string | null
}

export interface Task {
  id: string
  title: string
  description: string
  task_type: string
  required_skills: SkillSet
  priority: number
  complexity: number
  decomposability: number
  status: string
  owner_agent: string | null
  collaborator_agents: string[]
  subtasks: string[]
  outputs: unknown[]
  review_result: { approved: boolean; feedback: string } | null
  review_feedback: string | null
  run_id: string | null
  assignment_info: {
    score?: number
    skill_match?: number
    idle_factor?: number
    primary_skill?: string
    primary_skill_score?: number
  }
  subagent_triggered: boolean
  created_at: string
  updated_at: string
}

export interface Run {
  id: string
  research_goal: string
  status: string
  current_step: string
  task_ids: string[]
  agent_assignments: Record<string, { owner: string; collaborators: string[] }>
  created_at: string
  updated_at: string
  started_at?: string | null
  completed_at: string | null
  cancel_requested_at?: string | null
  cancel_reason?: string | null
  total_cost_usd?: number
  total_tokens?: number
  total_llm_calls?: number
  last_event_id?: string | null
}

export interface Output {
  id: string
  output_type: string
  title: string
  content: string
  run_id: string | null
  task_id: string | null
  agent_id: string | null
  format: string
  created_at: string
}

export interface RunEvent {
  id: string
  run_id: string
  task_id: string | null
  agent_id: string | null
  subagent_id: string | null
  event_type: string
  phase: string
  title: string
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export interface LLMUsage {
  id: string
  run_id: string | null
  task_id: string | null
  agent_id: string | null
  role: string
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  latency_ms: number
  success: boolean
  error: string | null
  created_at: string
}

export interface RunSummary {
  run: Run
  counts: Record<string, number>
  usage: {
    total_cost_usd: number
    total_tokens: number
    total_llm_calls: number
    failed_llm_calls?: number
  }
  latest_event: RunEvent | null
  tasks: Task[]
  agents: GraduateAgent[]
}

export interface SubAgent {
  id: string
  parent_agent: string
  task_id: string
  task: string
  context: string
  status: string
  result: unknown
}

export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: "待分配",
  assigned: "已分配",
  running: "执行中",
  waiting_collab: "等待协作",
  waiting_subagent: "等待 SubAgent",
  waiting_review: "等待导师审核",
  need_revision: "需要修改",
  completed: "已完成",
  archived: "已归档",
  failed: "失败",
}

export const AGENT_STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  working: "工作中",
  waiting: "等待中",
  reviewing: "审核中",
  blocked: "阻塞",
  finished: "已完成",
}

export const RUN_STATUS_LABELS: Record<string, string> = {
  created: "已创建",
  queued: "等待执行",
  decomposing: "正在拆解任务",
  scheduling: "正在调度分配",
  executing: "正在执行任务",
  reviewing: "导师审核中",
  reporting: "正在生成报告",
  cancelling: "正在停止",
  cancelled: "已停止",
  completed: "已完成",
  failed: "失败",
}

export const SKILL_NAMES: Record<string, string> = {
  literature_review: "文献综述",
  coding: "工程实现",
  experiment: "实验设计",
  data_analysis: "数据分析",
  academic_writing: "学术写作",
  mentoring: "指导拆解",
}

export const TASK_TYPE_LABELS: Record<string, string> = {
  literature_survey: "文献调研",
  system_design: "系统设计",
  experiment_design: "实验设计",
  result_analysis: "结果分析",
  report_writing: "报告写作",
}

export const OUTPUT_TYPE_LABELS: Record<string, string> = {
  task_result: "任务产出",
  subagent_result: "SubAgent 产出",
  review: "导师审核",
  review_summary: "导师审核汇总",
  final_report: "最终报告",
  run_log: "运行日志",
}

OUTPUT_TYPE_LABELS.final_report_draft = "写作研究生初稿"

export interface OfficeState {
  run: {
    id: string
    status: string
    current_step: string
    total_cost_usd: number
    total_tokens: number
    started_at: string | null
    updated_at: string | null
  }
  agents: OfficeAgentState[]
  tasks: OfficeTaskState[]
  subagents: OfficeSubAgentState[]
  events: RunEvent[]
}

export interface OfficeAgentState {
  id: string
  name: string
  role: string
  status: string
  activity_state: string
  current_task_id: string | null
  current_task_title: string | null
  office_zone: string
  speech: string
  last_event_at: string | null
  current_load: number
}

export interface OfficeTaskState {
  id: string
  title: string
  status: string
  owner_agent: string | null
  priority: number
  latest_event: string
}

export interface OfficeSubAgentState {
  id: string
  parent_agent: string
  task_id: string
  status: string
  speech: string
}
