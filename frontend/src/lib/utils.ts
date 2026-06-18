import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Replace raw task IDs (e.g. "task_9a5744bf") inside a human-facing string
 * with the corresponding task title, so users see readable names instead of
 * opaque IDs. Falls back to the original ID when no title is found.
 */
export function humanizeTaskIds(
  text: string | null | undefined,
  tasks: Array<{ id: string; title?: string | null }>
): string {
  if (!text) return text ?? ""
  const titleById = new Map<string, string>()
  for (const task of tasks) {
    if (task?.id && task.title) titleById.set(task.id, task.title)
  }
  if (titleById.size === 0) return text
  // Match task ids like task_xxx and task_revision_xxx (word boundary aware).
  return text.replace(/task_[A-Za-z0-9_]+/g, (match) => {
    const title = titleById.get(match)
    return title ? `「${title}」` : match
  })
}
