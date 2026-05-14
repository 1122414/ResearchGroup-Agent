# backend/app/storage/ — Data Persistence

## OVERVIEW
SQLite data layer: raw SQL table management, repository pattern with static methods, and JSON-as-text serialization. No ORM, no migrations.

## STRUCTURE
```
storage/
├── db.py              # SQLite connection (WAL mode, foreign keys), init_db(), schema evolution
├── repositories.py    # 7 Repository classes — all @staticmethod, no shared state
└── __init__.py        # Re-exports init_db, get_connection, 5 repositories
```

## WHERE TO LOOK
| Component | File | Key Lines |
|-----------|------|-----------|
| Connection factory | `db.py:12` | `get_connection()` — WAL + foreign_keys, row_factory=sqlite3.Row |
| Table creation | `db.py:20` | `init_db()` — CREATE TABLE IF NOT EXISTS ×7 |
| Schema evolution | `db.py:120` | `_ensure_columns()` — ALTER TABLE ADD COLUMN for backward compat |
| Agent repo | `repositories.py:25` | `AgentRepository` — get_all, get_by_id, upsert, update_status |
| Task repo | `repositories.py:85` | `TaskRepository` — get_all(run_id), insert, update_status |
| Run repo | `repositories.py:200` | `RunRepository` — insert, get_by_id, increment_usage, delete cascade |
| JSON helpers | `repositories.py:15` | `_json_loads()` — safe JSON deserialization with fallback |

## CONVENTIONS
- **Raw SQL only**: No SQLAlchemy ORM, no Alembic migrations
- **Repository pattern**: Static methods, no instances, no base class
- **Connection per request**: Each Repository method opens/closes its own connection
- **JSON-as-text**: Complex fields stored as JSON text, deserialized via `_json_loads()`
- **WAL mode**: `PRAGMA journal_mode=WAL` for better concurrency
- **Schema evolution**: `_ensure_columns()` adds missing columns on startup (ALTER TABLE)

## ANTI-PATTERNS
- Don't use SQLAlchemy ORM — this project uses raw SQL + Repository pattern
- Don't instantiate Repository classes — all methods are @staticmethod
- Don't bypass `_json_loads()` for JSON fields — handles None, pre-parsed, malformed
- Don't forget to call `init_db()` in lifespan (already in `main.py`)

## NOTES
- 7 tables: agents, tasks, subagents, outputs, runs, run_events, llm_usage
- DB path from `.env` DATABASE_URL (default: sqlite:///./researchgroup.db)
- `__init__.py` re-exports 5 repositories + init_db/get_connection (unusual: backend/AGENTS.md says all __init__.py are empty, but storage has exports)
- `RunRepository.delete()` cascades: deletes run + tasks + subagents + outputs + events + usage
- `LLMUsageRepository.get_summary()` aggregates tokens/cost per run
