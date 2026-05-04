from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OutputType(str, Enum):
    task_result = "task_result"
    subagent_result = "subagent_result"
    review = "review"
    final_report = "final_report"
    run_log = "run_log"


class Output(BaseModel):
    id: str
    output_type: OutputType
    title: str
    content: str
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    format: str = "markdown"
    created_at: str = Field(default_factory=lambda: __import__("datetime").datetime.now().isoformat())
