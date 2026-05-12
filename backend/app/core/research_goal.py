"""Helpers for keeping the user research goal separate from attachment context."""

ATTACHMENT_CONTEXT_HEADING = "## 用户上传的多模态附件上下文"


def primary_goal(research_goal: str) -> str:
    """Return the user-facing research goal without extracted attachment text."""
    return str(research_goal or "").split(ATTACHMENT_CONTEXT_HEADING, 1)[0].strip()


def attachment_context(research_goal: str) -> str:
    parts = str(research_goal or "").split(ATTACHMENT_CONTEXT_HEADING, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def merge_goal_with_attachments(research_goal: str, attachments: list[dict], max_chars: int) -> str:
    if not attachments:
        return research_goal.strip()

    lines = [research_goal.strip(), "", ATTACHMENT_CONTEXT_HEADING, ""]
    for item in attachments:
        name = item.get("name", "附件")
        extracted = str(item.get("extracted_markdown") or "").strip()
        lines.append(f"### {name}")
        if extracted:
            lines.append(extracted[:max_chars])
        else:
            lines.append(f"附件已保存，但未提取出可读文本：{item.get('path', '')}")
        lines.append("")
    return "\n".join(lines).strip()
