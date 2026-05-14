import type { Run } from "./types"

const ATTACHMENT_HEADING = "## 鐢ㄦ埛涓婁紶鐨勫妯℃€侀檮浠朵笂涓嬫枃"

export function primaryGoal(goal: string) {
  return goal.split(ATTACHMENT_HEADING, 1)[0].trim()
}

export function runDisplayName(run: Run, index?: number) {
  if (run.display_name) return run.display_name
  const date = run.created_at ? new Date(run.created_at) : null
  const dateLabel = date ? `${date.getMonth() + 1}.${date.getDate()}` : "未日期"
  const order = typeof index === "number" ? index + 1 : 1
  const goal = primaryGoal(run.research_goal || "") || "未命名课题"
  return `${dateLabel}-${order}-${goal.slice(0, 28)}${goal.length > 28 ? "..." : ""}`
}

export function runArtifactDir(run: Run) {
  return run.artifact_dir || ""
}
