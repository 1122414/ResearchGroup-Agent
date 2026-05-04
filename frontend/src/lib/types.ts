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
  status: 'idle' | 'working' | 'waiting' | 'reviewing' | 'blocked' | 'finished'
  current_load: number
  max_load: number
  current_tasks: string[]
  preferred_task_types: string[]
  tools: string[]
  can_create_subagents: boolean
  max_subagents: number
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
  outputs: any[]
  review_result: { approved: boolean; feedback: string } | null
  review_feedback: string | null
  run_id: string | null
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
  completed_at: string | null
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

export interface SubAgent {
  id: string
  parent_agent: string
  task_id: string
  task: string
  context: string
  status: string
  result: any
}

export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: '待分配',
  assigned: '已分配',
  running: '执行中',
  waiting_collab: '等待协作',
  waiting_subagent: '等待SubAgent',
  waiting_review: '等待审核',
  need_revision: '需返工',
  completed: '已完成',
  archived: '已归档',
  failed: '失败',
}

export const AGENT_STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  working: '工作中',
  waiting: '等待中',
  reviewing: '审核中',
  blocked: '阻塞',
  finished: '已完成',
}

export const RUN_STATUS_LABELS: Record<string, string> = {
  created: '已创建',
  decomposing: '任务拆解中',
  scheduling: '任务分配中',
  executing: '任务执行中',
  reviewing: '导师审核中',
  reporting: '报告生成中',
  completed: '已完成',
  failed: '失败',
}

export const SKILL_NAMES: Record<string, string> = {
  literature_review: '文献调研',
  coding: '编码',
  experiment: '实验',
  data_analysis: '数据分析',
  academic_writing: '学术写作',
  mentoring: '指导管理',
}
