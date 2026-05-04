import sqlite3
import json
from pathlib import Path
from typing import Optional
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

    cursor.executescript("""
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
            completed_at TEXT
        );
    """)

    conn.commit()
    conn.close()
