# backend/app/models/ — Data Models

## OVERVIEW
Pydantic v2 data models defining the domain entities: agents, tasks, runs, subagents, outputs. Shared across API, services, and storage layers.

## STRUCTURE
```
models/
├── agent.py         # GraduateAgent, SkillSet, AgentStatus enum
├── task.py          # Task, TaskStatus, TaskType enums
├── run.py           # Run, RunStatus enum
├── subagent.py      # SubAgent, SubAgentLifecycle enum
└── output.py        # Output, OutputType enum
```

## WHERE TO LOOK
| Model | File | Key Fields |
|-------|------|-----------|
| Agent + skills | `agent.py:15` | `SkillSet`: 6-dim matrix (1-10), `GraduateAgent`: load, subagent caps |
| Task states | `task.py` | `TaskStatus`: 10 states, `TaskType`: 5 types |
| Run lifecycle | `run.py` | `RunStatus`: 11 states (created→queued→...→completed/failed/cancelled) |
| SubAgent rules | `subagent.py` | `SubAgentLifecycle.destroy_after_return` |
| Output types | `output.py` | `OutputType`: task_result, subagent_result, review, final_report, run_log |

## CONVENTIONS
- **Pydantic v2**: `BaseModel` with `Field(default=..., ge=, le=)` validators
- **Enums as str**: All status/type enums inherit `str, Enum` for JSON serialization
- **Skill matrix**: 6 dimensions (literature_review, coding, experiment, data_analysis, academic_writing, mentoring)
- **Task state machine**: pending → assigned → running → waiting_review → completed/need_revision
- **Run state machine**: created → decomposing → scheduling → executing → reviewing → reporting → completed

## ANTI-PATTERNS
- Don't use Pydantic v1 syntax (this project uses v2: `model_validate`, `model_dump`)
- Don't add ORM relationships — models are pure Pydantic, no SQLAlchemy
- Don't bypass Field validators (skill values must be 1-10)

## NOTES
- All models use `default_factory=list` for array fields
- `AgentStatus.idle` is the default state for new agents
- `RunStatus.cancelling` triggers cancel checkpoints at every phase boundary
- `OutputType.run_log` stores structured event data for UI timeline
