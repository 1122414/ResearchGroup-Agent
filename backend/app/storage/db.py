import sqlite3
from pathlib import Path

from ..core.config import settings


DB_PATH = Path(settings.database_url.replace("sqlite:///", ""))
if not DB_PATH.is_absolute():
    DB_PATH = Path(__file__).parent.parent.parent.parent / DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT DEFAULT '',
            skills TEXT NOT NULL,
            status TEXT DEFAULT 'idle',
            current_load REAL DEFAULT 0.0,
            max_load REAL DEFAULT 1.0,
            current_tasks TEXT DEFAULT '[]',
            preferred_task_types TEXT DEFAULT '[]',
            tools TEXT DEFAULT '[]',
            can_create_subagents INTEGER DEFAULT 1,
            max_subagents INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            task_type TEXT NOT NULL,
            required_skills TEXT NOT NULL,
            priority INTEGER DEFAULT 5,
            complexity INTEGER DEFAULT 5,
            decomposability INTEGER DEFAULT 5,
            status TEXT DEFAULT 'pending',
            owner_agent TEXT,
            collaborator_agents TEXT DEFAULT '[]',
            subtasks TEXT DEFAULT '[]',
            outputs TEXT DEFAULT '[]',
            review_result TEXT,
            review_feedback TEXT,
            run_id TEXT,
            assignment_info TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subagents (
            id TEXT PRIMARY KEY,
            parent_agent TEXT NOT NULL,
            task_id TEXT NOT NULL,
            task TEXT NOT NULL,
            context TEXT DEFAULT '',
            expected_output_schema TEXT DEFAULT '{}',
            status TEXT DEFAULT 'running',
            lifecycle TEXT DEFAULT 'destroy_after_return',
            result TEXT
        );

        CREATE TABLE IF NOT EXISTS outputs (
            id TEXT PRIMARY KEY,
            output_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            run_id TEXT,
            task_id TEXT,
            agent_id TEXT,
            format TEXT DEFAULT 'markdown',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            research_goal TEXT NOT NULL,
            status TEXT DEFAULT 'created',
            current_step TEXT DEFAULT '',
            task_ids TEXT DEFAULT '[]',
            agent_assignments TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            cancel_requested_at TEXT,
            cancel_reason TEXT,
            total_cost_usd REAL DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            total_llm_calls INTEGER DEFAULT 0,
            last_event_id TEXT
        );

        CREATE TABLE IF NOT EXISTS run_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT,
            agent_id TEXT,
            subagent_id TEXT,
            event_type TEXT NOT NULL,
            phase TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS llm_usage (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            task_id TEXT,
            agent_id TEXT,
            role TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            success INTEGER DEFAULT 1,
            error TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_run_events_run_created ON run_events(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_llm_usage_run_created ON llm_usage(run_id, created_at);
        """
    )

    _ensure_columns(conn, "tasks", {
        "assignment_info": "TEXT DEFAULT '{}'",
        "subagent_triggered": "INTEGER DEFAULT 0",
    })

    _ensure_columns(conn, "runs", {
        "started_at": "TEXT",
        "cancel_requested_at": "TEXT",
        "cancel_reason": "TEXT",
        "total_cost_usd": "REAL DEFAULT 0",
        "total_tokens": "INTEGER DEFAULT 0",
        "total_llm_calls": "INTEGER DEFAULT 0",
        "last_event_id": "TEXT",
    })

    conn.commit()
    conn.close()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
