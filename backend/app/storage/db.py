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

        CREATE TABLE IF NOT EXISTS experiment_protocols (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            hypothesis_id TEXT NOT NULL,
            task_id TEXT,
            title TEXT NOT NULL,
            research_question TEXT NOT NULL,
            independent_variables TEXT DEFAULT '[]',
            dependent_variables TEXT DEFAULT '[]',
            datasets TEXT DEFAULT '[]',
            metrics TEXT DEFAULT '[]',
            baselines TEXT DEFAULT '[]',
            method_details TEXT DEFAULT '{}',
            stopping_conditions TEXT DEFAULT '[]',
            expected_risks TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS experiment_runs (
            id TEXT PRIMARY KEY,
            protocol_id TEXT NOT NULL,
            plan_id TEXT,
            run_id TEXT NOT NULL,
            task_id TEXT,
            status TEXT DEFAULT 'pending',
            command TEXT DEFAULT '',
            dataset_snapshot TEXT DEFAULT '{}',
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS experiment_results (
            id TEXT PRIMARY KEY,
            experiment_run_id TEXT NOT NULL,
            protocol_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT DEFAULT '',
            metrics TEXT DEFAULT '{}',
            exit_code INTEGER,
            stdout TEXT DEFAULT '',
            stderr TEXT DEFAULT '',
            artifacts TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS experiment_findings (
            id TEXT PRIMARY KEY,
            protocol_id TEXT NOT NULL,
            experiment_run_id TEXT NOT NULL,
            result_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            hypothesis_id TEXT NOT NULL,
            claim_id TEXT,
            relation_type TEXT NOT NULL,
            statement TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            created_at TEXT NOT NULL
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

        CREATE TABLE IF NOT EXISTS research_milestones (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            milestone_key TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            criteria TEXT DEFAULT '[]',
            evidence_ids TEXT DEFAULT '[]',
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, milestone_key)
        );

        CREATE TABLE IF NOT EXISTS literature_search_protocols (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT,
            version INTEGER DEFAULT 1,
            providers TEXT DEFAULT '[]',
            queries TEXT DEFAULT '[]',
            languages TEXT DEFAULT '[]',
            date_range TEXT DEFAULT '{}',
            inclusion_criteria TEXT DEFAULT '[]',
            exclusion_criteria TEXT DEFAULT '[]',
            status TEXT DEFAULT 'frozen',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS literature_search_runs (
            id TEXT PRIMARY KEY,
            protocol_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            task_id TEXT,
            query TEXT NOT NULL,
            provider TEXT NOT NULL,
            result_count INTEGER DEFAULT 0,
            error TEXT,
            response_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS screening_decisions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_id TEXT,
            source_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fulltext_documents (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            url TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            parser TEXT NOT NULL,
            status TEXT NOT NULL,
            char_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, source_id, content_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_run_events_run_created ON run_events(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_llm_usage_run_created ON llm_usage(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_skills_agent_status ON agent_skills(agent_id, status);
        CREATE INDEX IF NOT EXISTS idx_experiment_plans_run_task ON experiment_plans(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_experiment_protocols_run_hypothesis ON experiment_protocols(run_id, hypothesis_id);
        CREATE INDEX IF NOT EXISTS idx_experiment_runs_run_protocol ON experiment_runs(run_id, protocol_id);
        CREATE INDEX IF NOT EXISTS idx_experiment_results_run_protocol ON experiment_results(run_id, protocol_id);
        CREATE INDEX IF NOT EXISTS idx_experiment_findings_run_hypothesis ON experiment_findings(run_id, hypothesis_id);
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
        CREATE INDEX IF NOT EXISTS idx_research_milestones_run_status ON research_milestones(run_id, status);
        CREATE INDEX IF NOT EXISTS idx_literature_search_protocols_run ON literature_search_protocols(run_id, task_id);
        CREATE INDEX IF NOT EXISTS idx_literature_search_runs_protocol ON literature_search_runs(protocol_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_screening_decisions_run_source ON screening_decisions(run_id, source_id);
        CREATE INDEX IF NOT EXISTS idx_fulltext_documents_run_source ON fulltext_documents(run_id, source_id);
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
        "subquestion_id": "TEXT",
        "hypothesis_id": "TEXT",
        "milestone_id": "TEXT",
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

    _ensure_columns(conn, "research_briefs", {
        "research_type": "TEXT DEFAULT 'empirical'",
        "subquestions": "TEXT DEFAULT '[]'",
        "scope_in": "TEXT DEFAULT '[]'",
        "scope_out": "TEXT DEFAULT '[]'",
        "target_domain": "TEXT DEFAULT ''",
        "expected_contribution": "TEXT DEFAULT ''",
        "novelty_criteria": "TEXT DEFAULT '[]'",
        "data_availability": "TEXT DEFAULT ''",
        "ethics_risks": "TEXT DEFAULT '[]'",
        "failure_criteria": "TEXT DEFAULT '[]'",
        "approval_status": "TEXT DEFAULT 'draft'",
        "validation_errors": "TEXT DEFAULT '[]'",
        "discipline": "TEXT DEFAULT '{}'",
        "methodology_family": "TEXT DEFAULT ''",
        "epistemic_mode": "TEXT DEFAULT ''",
        "methodology_profile": "TEXT DEFAULT '{}'",
        "resource_plan": "TEXT DEFAULT '[]'",
        "ethics_plan": "TEXT DEFAULT '{}'",
        "thesis_requirements": "TEXT DEFAULT '{}'",
        "feasibility_assessment": "TEXT DEFAULT '{}'",
    })

    _ensure_columns(conn, "research_hypotheses", {
        "treatment": "TEXT DEFAULT ''",
        "baseline": "TEXT DEFAULT ''",
        "conditions": "TEXT DEFAULT '[]'",
        "predicted_direction": "TEXT DEFAULT ''",
        "primary_metric": "TEXT DEFAULT ''",
        "minimum_effect": "TEXT DEFAULT ''",
        "falsification_criterion": "TEXT DEFAULT ''",
        "originating_evidence_ids": "TEXT DEFAULT '[]'",
        "competing_hypothesis_ids": "TEXT DEFAULT '[]'",
    })

    _ensure_columns(conn, "evidence_excerpts", {
        "document_id": "TEXT",
        "section": "TEXT DEFAULT ''",
        "page_number": "INTEGER",
        "paragraph_index": "INTEGER",
        "content_hash": "TEXT DEFAULT ''",
    })
    _ensure_columns(conn, "experiment_protocols", {
        "method_details": "TEXT DEFAULT '{}'",
    })

    conn.commit()
    conn.close()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
