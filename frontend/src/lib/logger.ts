const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"

interface LogEntry {
  timestamp: string
  level: string
  file: string
  func: string
  line: number
  message: string
  run_id?: string
}

class FrontendLogger {
  private buffer: LogEntry[] = []
  private runId: string | null = null
  private timer: ReturnType<typeof setInterval> | null = null

  constructor() {
    this.timer = setInterval(() => this.flush(), 5000)
  }

  setRunId(runId: string | null) {
    this.runId = runId
  }

  private caller(): { file: string; func: string; line: number } {
    const stack = new Error().stack?.split("\n") || []
    const line = stack[3] || ""
    const m = line.match(/at\s+(?:.*?\s+\()?([^()]+)\)?/)?.[1] || "anonymous"
    const parts = m.split(":")
    const fm = line.match(/at\s+([^.]+)\.([^(]+)/)
    return {
      file: parts[0]?.replace(/.*\//, "") || "unknown",
      func: fm?.[2] || "anonymous",
      line: parseInt(parts[1] || "0", 10) || 0,
    }
  }

  private log(level: string, message: string) {
    const c = this.caller()
    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      file: c.file,
      func: c.func,
      line: c.line,
      message,
      run_id: this.runId || undefined,
    }
    console.log(`[${level}] ${c.file}:${c.func}:${c.line} | ${message}`)
    this.buffer.push(entry)
    if (this.buffer.length >= 30) this.flush()
  }

  debug(message: string) { this.log("DEBUG", message) }
  info(message: string) { this.log("INFO", message) }
  warn(message: string) { this.log("WARN", message) }
  error(message: string) { this.log("ERROR", message) }

  async flush() {
    if (this.buffer.length === 0) return
    const batch = this.buffer.splice(0, this.buffer.length)
    try {
      await fetch(`${API_BASE}/logs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: batch }),
      })
    } catch {}
  }

  destroy() {
    if (this.timer) clearInterval(this.timer)
    this.flush()
  }
}

export const frontendLogger = new FrontendLogger()
