from fastapi import APIRouter, HTTPException, Query

from ..core.logger import logger
from ..storage.repositories import AgentRepository, RunEventRepository, RunRepository, SubAgentRepository, TaskRepository

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

_AGENT_TYPE_TO_ZONE = {
    "advisor": "advisor_office",
    "researcher": "research_office",
    "engineer": "engineer_office",
    "experimenter": "experiment_office",
    "analyst": "analyst_office",
    "writer": "writer_office",
    "subagent": "temp_desk",
}

_TASK_TYPE_TO_ACTIVITY = {
    "literature_survey": "researching",
    "system_design": "coding",
    "experiment_design": "experimenting",
    "result_analysis": "analyzing",
    "report_writing": "writing",
}

_STATUS_TO_ACTIVITY = {
    "idle": "idle",
    "working": "working",
    "waiting": "waiting",
    "reviewing": "reviewing",
    "blocked": "blocked",
    "finished": "done",
}

_ACTIVITY_SPEECH = {
    "idle": "正在休息区待命",
    "decomposing": "正在把研究目标拆成任务",
    "scheduling": "正在看公共任务板",
    "researching": "正在整理文献脉络",
    "coding": "正在敲代码",
    "experimenting": "正在设计实验流程",
    "analyzing": "正在分析数据和图表",
    "writing": "正在写报告",
    "reviewing": "正在审核任务产出",
    "waiting": "等待协作或 SubAgent 结果",
    "blocked": "遇到了问题需要关注",
    "done": "任务已完成，回到办公室",
    "working": "正在处理任务",
}

_ADVISOR_AGENT = {
    "id": "advisor_agent",
    "name": "导师 Agent",
    "type": "advisor",
    "status": "idle",
    "current_load": 0,
    "current_tasks": [],
}


@router.get("/office-state")
async def get_office_state(run_id: str = Query(...)):
    logger.debug("[API] get_office_state | run_id=%s", run_id)
    run = RunRepository.get_by_id(run_id)
    if not run:
        logger.warning("[API] get_office_state | run_id=%s not found", run_id)
        raise HTTPException(status_code=404, detail="运行不存在")

    tasks = TaskRepository.get_all(run_id=run_id)
    agents = AgentRepository.get_all()
    if not any(agent.get("type") == "advisor" for agent in agents):
        agents = [_ADVISOR_AGENT, *agents]
    subagents = SubAgentRepository.get_by_run(run_id)
    events = RunEventRepository.get_by_run(run_id, limit=20)

    agent_states = []
    for agent in agents:
        agent_type = agent.get("type", "")
        status = agent.get("status", "idle")
        current_tasks = agent.get("current_tasks", []) or []
        current_task = None

        if current_tasks:
            current_task_ids = set(current_tasks)
            current_task = next((t for t in tasks if t.get("id") in current_task_ids and t.get("status") in ("running", "waiting_subagent", "waiting_review")), None)
            if current_task is None:
                current_task = next((t for t in tasks if t.get("id") in current_task_ids), None)

        if not current_task:
            for t in tasks:
                if t.get("owner_agent") == agent.get("id") and t.get("status") in ("running", "waiting_subagent"):
                    current_task = t
                    break

        activity = _STATUS_TO_ACTIVITY.get(status, "idle")
        if current_task and status == "working":
            activity = _TASK_TYPE_TO_ACTIVITY.get(current_task.get("task_type", ""), "working")

        if run.get("status") in ("decomposing", "scheduling") and agent_type == "advisor":
            activity = "decomposing" if run.get("status") == "decomposing" else "scheduling"
        elif run.get("status") == "reviewing" and agent_type == "advisor":
            activity = "reviewing"
        elif run.get("status") == "reporting" and agent_type == "advisor":
            activity = "decomposing"

        office_zone = _AGENT_TYPE_TO_ZONE.get(agent_type, "unknown")
        if agent_type != "advisor" and not current_task and activity in ("idle", "done", "waiting"):
            office_zone = "rest_area"

        agent_states.append({
            "id": agent.get("id"),
            "name": agent.get("name"),
            "role": agent_type,
            "status": status,
            "activity_state": activity,
            "current_task_id": current_task.get("id") if current_task else None,
            "current_task_title": current_task.get("title") if current_task else None,
            "office_zone": office_zone,
            "speech": _ACTIVITY_SPEECH.get(activity, "正在处理中"),
            "last_event_at": events[-1]["created_at"] if events else None,
            "current_load": agent.get("current_load", 0),
        })

    task_states = []
    for task in tasks:
        task_events = [e for e in events if e.get("task_id") == task.get("id")]
        latest_event = task_events[-1] if task_events else None
        task_states.append({
            "id": task.get("id"),
            "title": task.get("title"),
            "status": task.get("status"),
            "owner_agent": task.get("owner_agent"),
            "priority": task.get("priority"),
            "latest_event": latest_event.get("title") if latest_event else "暂无事件",
        })

    subagent_states = []
    for sub in subagents:
        subagent_states.append({
            "id": sub.get("id"),
            "parent_agent": sub.get("parent_agent"),
            "task_id": sub.get("task_id"),
            "status": sub.get("status"),
            "speech": "正在处理临时子任务",
        })

    return {
        "run": {
            "id": run.get("id"),
            "status": run.get("status"),
            "current_step": run.get("current_step"),
            "total_cost_usd": run.get("total_cost_usd", 0),
            "total_tokens": run.get("total_tokens", 0),
            "started_at": run.get("started_at"),
            "updated_at": run.get("updated_at"),
        },
        "agents": agent_states,
        "tasks": task_states,
        "subagents": subagent_states,
        "events": events[-5:] if events else [],
    }
