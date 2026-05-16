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
            blocked_reason TEXT,
            parallelizable INTEGER DEFAULT 1,
            is_critical_path INTEGER DEFAULT 0,
            attempt_count INTEGER DEFAULT 0,
            last_checkpoint TEXT,
            revision_of_task_id TEXT,
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
            display_name TEXT,
            artifact_dir TEXT,
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

        CREATE TABLE IF NOT EXISTS agent_skills (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            source_run_id TEXT,
            source_task_id TEXT,
            tags TEXT DEFAULT '[]',
            file_path TEXT NOT NULL,
            usage_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS experiment_plans (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            task_id TEXT,
            agent_id TEXT NOT NULL,
            title TEXT NOT NULL,
            objective TEXT DEFAULT '',
            workspace_dir TEXT NOT NULL,
            files TEXT DEFAULT '[]',
            commands TEXT DEFAULT '[]',
            env_vars TEXT DEFAULT '{}',
            risk_level TEXT DEFAULT 'needs_review',
            risk_reasons TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            result TEXT,
            artifacts TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            approved_at TEXT,
            approved_by TEXT
        );

        CREATE TABLE IF NOT EXISTS task_dependencies (
            task_id TEXT NOT NULL,
            depends_on_task_id TEXT NOT NULL,
            dependency_type TEXT DEFAULT 'hard',
            PRIMARY KEY (task_id, depends_on_task_id)
        );

        CREATE TABLE IF NOT EXISTS task_attempts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt_number INTEGER DEFAULT 1,
            status TEXT DEFAULT 'running',
            failure_type TEXT,
            failure_message TEXT,
            checkpoint TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS recovery_actions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            status TEXT DEFAULT 'requested',
            reason TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_records (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            agent_id TEXT,
            scope TEXT NOT NULL,
            category TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT DEFAULT '{}',
            source_task_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence_sources (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT,
            title TEXT NOT NULL,
            authors TEXT DEFAULT '',
            year INTEGER,
            venue TEXT DEFAULT '',
            doi TEXT,
            url TEXT,
            source_type TEXT DEFAULT 'paper',
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence_claims (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT,
            source_id TEXT NOT NULL,
            claim TEXT NOT NULL,
            method TEXT DEFAULT '',
            relation_type TEXT DEFAULT 'supports',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence_excerpts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            locator TEXT DEFAULT '',
            excerpt_type TEXT DEFAULT 'summary',
            captured_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence_assessments (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            excerpt_id TEXT,
            relevance_score REAL DEFAULT 0,
            credibility_score REAL DEFAULT 0,
            freshness_score REAL DEFAULT 0,
            conflict_score REAL DEFAULT 0,
            overall_score REAL DEFAULT 0,
            is_primary INTEGER DEFAULT 0,
            is_peer_reviewed INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence_links (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            excerpt_id TEXT,
            relation_type TEXT DEFAULT 'supports',
            confidence REAL DEFAULT 0,
            rationale TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS review_decisions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            rubric TEXT DEFAULT '{}',
            scores TEXT DEFAULT '{}',
            approved INTEGER DEFAULT 1,
            feedback TEXT DEFAULT '',
            requires_revision INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS approval_requests (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT,
            request_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            title TEXT NOT NULL,
            message TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        );

        CREATE TABLE IF NOT EXISTS research_briefs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            research_question TEXT NOT NULL,
            objective TEXT NOT NULL,
            scope TEXT DEFAULT '',
            success_criteria TEXT DEFAULT '[]',
            constraints TEXT DEFAULT '[]',
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_hypotheses (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            statement TEXT NOT NULL,
            rationale TEXT DEFAULT '',
            status TEXT DEFAULT 'proposed',
            confidence REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_claims (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            hypothesis_id TEXT,
            statement TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            evidence_ids TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_decisions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            rationale TEXT DEFAULT '',
            impact TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_uncertainties (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT DEFAULT 'research_question',
            severity TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_run_events_run_created ON run_events(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_llm_usage_run_created ON llm_usage(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_skills_agent_status ON agent_skills(agent_id, status);
        CREATE INDEX IF NOT EXISTS idx_experiment_plans_run_task ON experiment_plans(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_task ON task_dependencies(task_id);
        CREATE INDEX IF NOT EXISTS idx_task_attempts_run_task ON task_attempts(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_memory_records_run_scope ON memory_records(run_id, scope);
        CREATE INDEX IF NOT EXISTS idx_evidence_sources_run_task ON evidence_sources(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_claims_run_task ON evidence_claims(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_excerpts_run_source ON evidence_excerpts(run_id, source_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_assessments_run_source ON evidence_assessments(run_id, source_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_links_run_claim ON evidence_links(run_id, claim_id);
        CREATE INDEX IF NOT EXISTS idx_review_decisions_run_task ON review_decisions(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_approval_requests_run_status ON approval_requests(run_id, status);
        CREATE INDEX IF NOT EXISTS idx_research_hypotheses_run_status ON research_hypotheses(run_id, status);
        CREATE INDEX IF NOT EXISTS idx_research_claims_run_status ON research_claims(run_id, status);
        CREATE INDEX IF NOT EXISTS idx_research_decisions_run_created ON research_decisions(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_research_uncertainties_run_status ON research_uncertainties(run_id, status);
        """
    )

    _ensure_columns(conn, "tasks", {
        "assignment_info": "TEXT DEFAULT '{}'",
        "subagent_triggered": "INTEGER DEFAULT 0",
        "blocked_reason": "TEXT",
        "parallelizable": "INTEGER DEFAULT 1",
        "is_critical_path": "INTEGER DEFAULT 0",
        "attempt_count": "INTEGER DEFAULT 0",
        "last_checkpoint": "TEXT",
        "revision_of_task_id": "TEXT",
    })

    _ensure_columns(conn, "runs", {
        "display_name": "TEXT",
        "artifact_dir": "TEXT",
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
