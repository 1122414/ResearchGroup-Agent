from __future__ import annotations

import json
import math
import re
import uuid
from copy import deepcopy
from datetime import datetime

from ..storage.repositories import (
    EvidenceRepository, ExperimentProtocolRepository, ExperimentResultRepository, ResearchBriefRepository, ResearchClaimRepository,
    ResearchMilestoneRepository, TaskDependencyRepository, TaskRepository,
)
from .thesis_quality_service import thesis_quality_service
from .citation_style_service import citation_style_service


class ThesisChapterService:
    WRITING_TYPES = {"thesis_chapter", "report_writing"}

    def ensure_tasks(self, run_id: str) -> list[dict]:
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        requirements = brief.get("thesis_requirements") or {}
        if requirements.get("status") != "confirmed":
            return []
        existing = [item for item in TaskRepository.get_all(run_id=run_id) if item.get("task_type") == "thesis_chapter"]
        research_tasks = [
            item for item in TaskRepository.get_all(run_id=run_id)
            if item.get("task_type") not in self.WRITING_TYPES and item.get("status") == "completed"
        ]
        if existing:
            for task in existing:
                TaskDependencyRepository.replace_for_task(task["id"], [row["id"] for row in research_tasks])
            return existing
        plan = self.chapter_plan(requirements)
        now = datetime.now().isoformat()
        milestone = next(
            (item for item in ResearchMilestoneRepository.get_by_run(run_id) if item["milestone_key"] == "report_verified"),
            None,
        )
        created = []
        for item in plan:
            task = {
                "id": f"task_chapter_{uuid.uuid4().hex[:8]}",
                "title": f"撰写论文章节：{item['chapter_name']}",
                "description": (
                    f"【thesis_chapter_spec】{json.dumps(item, ensure_ascii=False)}\n"
                    "输出 chapter 对象；每个事实、解释或综合段落必须绑定 allowed_support 中的 claim ID。"
                    "transition/limitation 段可不绑定，但不得引入新事实。不得自行生成参考文献。"
                ),
                "task_type": "thesis_chapter",
                "required_skills": {
                    "literature_review": 6, "coding": 1, "experiment": 2,
                    "data_analysis": 5, "academic_writing": 10, "mentoring": 4,
                },
                "priority": 7, "complexity": 8, "decomposability": 4,
                "status": "pending", "owner_agent": None, "collaborator_agents": [],
                "subtasks": [], "outputs": [], "review_result": None, "review_feedback": None,
                "run_id": run_id, "blocked_reason": None, "parallelizable": True,
                "is_critical_path": False, "attempt_count": 0, "last_checkpoint": None,
                "subquestion_id": None, "hypothesis_id": None,
                "milestone_id": milestone.get("id") if milestone else None,
                "created_at": now, "updated_at": now,
            }
            TaskRepository.insert(task)
            TaskDependencyRepository.replace_for_task(task["id"], [row["id"] for row in research_tasks])
            created.append(task)
        chapter_ids = [item["id"] for item in created]
        for report_task in [item for item in TaskRepository.get_all(run_id=run_id) if item.get("task_type") == "report_writing"]:
            dependencies = TaskDependencyRepository.get_for_task(report_task["id"])
            TaskDependencyRepository.replace_for_task(report_task["id"], list(dict.fromkeys([*dependencies, *chapter_ids])))
        return created

    @staticmethod
    def chapter_plan(requirements: dict) -> list[dict]:
        chapters = [str(item).strip() for item in requirements.get("required_chapters") or [] if str(item).strip()]
        target = int(requirements.get("target_word_count") or 0)
        weights = []
        for chapter in chapters:
            lower = chapter.lower()
            weight = 1.0
            if any(marker in lower for marker in ("文献", "related", "literature")):
                weight = 1.4
            elif any(marker in lower for marker in ("结果", "分析", "result", "analysis", "讨论", "discussion")):
                weight = 1.35
            elif any(marker in lower for marker in ("方法", "method")):
                weight = 1.2
            elif any(marker in lower for marker in ("结论", "conclusion")):
                weight = 0.6
            weights.append(weight)
        total = sum(weights) or 1
        chapter_budget = target
        return [
            {
                "chapter_name": chapter, "chapter_index": index + 1,
                "word_budget": max(500, round(chapter_budget * weights[index] / total)),
            }
            for index, chapter in enumerate(chapters)
        ]

    def context_for_task(self, task: dict) -> str:
        brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
        claims = [item for item in ResearchClaimRepository.get_by_run(task.get("run_id")) if item.get("status") == "supported"]
        spec = self.spec_from_task(task)
        word_budget = int(spec.get("word_budget") or 0)
        minimum_words = self.minimum_word_count(task)
        allowed = [
            {"id": item["id"], "statement": item["statement"], "evidence_ids": item.get("evidence_ids") or []}
            for item in claims
        ]
        artifact_support = self.artifact_support(task.get("run_id"))
        return "【论文章节写作契约】\n" + json.dumps(
            {
                "chapter_spec": spec,
                "minimum_required_words": minimum_words,
                "research_question": brief.get("research_question"),
                "objective": brief.get("objective"),
                "scope_in": brief.get("scope_in"), "scope_out": brief.get("scope_out"),
                "methodology_profile": brief.get("methodology_profile"),
                "writing_requirements": {
                    "language": (brief.get("thesis_requirements") or {}).get("language"),
                    "citation_style": (brief.get("thesis_requirements") or {}).get("citation_style"),
                    "minimum_word_count": (brief.get("thesis_requirements") or {}).get("minimum_word_count"),
                    "target_word_count": (brief.get("thesis_requirements") or {}).get("target_word_count"),
                    "maximum_word_count": (brief.get("thesis_requirements") or {}).get("maximum_word_count"),
                },
                "allowed_support": allowed,
                "allowed_artifact_support": artifact_support,
                "allowed_contract_support": [
                    "brief:research_question", "brief:objective", "brief:scope", "brief:methodology",
                ],
                "output_contract": {
                    "chapter": {
                        "name": spec.get("chapter_name"), "word_budget": spec.get("word_budget"),
                        "sections": [{
                            "heading": "小节标题",
                            "paragraphs": [{
                                "id": "稳定段落ID", "text": "段落正文",
                                "paragraph_type": "claim|interpretation|method|transition|limitation",
                                "support_ids": ["claim ID、experiment:* ID 或 brief:* ID"],
                            }],
                        }],
                    }
                },
                "hard_constraints": [
                    f"chapter 正文必须至少达到 {minimum_words} 词",
                    "扩展分析深度、方法解释和边界讨论，不得用重复句填充篇幅",
                ],
            }, ensure_ascii=False, indent=2,
        )

    def validate_output(self, task: dict, latest: dict) -> list[str]:
        chapter = latest.get("chapter")
        if not isinstance(chapter, dict):
            return ["chapter_object_missing"]
        spec = self.spec_from_task(task)
        issues = []
        if chapter.get("name") != spec.get("chapter_name"):
            issues.append("chapter_name_mismatch")
        sections = chapter.get("sections")
        if not isinstance(sections, list) or not sections:
            return [*issues, "chapter_sections_empty"]
        brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
        claims = ResearchClaimRepository.get_by_run(task.get("run_id"))
        allowed = {item["id"] for item in claims if item.get("status") == "supported"}
        allowed.update(item["id"] for item in self.artifact_support(task.get("run_id")))
        allowed.update({"brief:research_question", "brief:objective", "brief:scope", "brief:methodology"})
        text_parts = []
        paragraph_count = 0
        for section_index, section in enumerate(sections):
            if not str(section.get("heading") or "").strip():
                issues.append(f"section_{section_index}:heading_missing")
            paragraphs = section.get("paragraphs") or []
            for paragraph_index, paragraph in enumerate(paragraphs if isinstance(paragraphs, list) else []):
                paragraph_count += 1
                text = str(paragraph.get("text") or "").strip()
                text_parts.append(text)
                prefix = f"section_{section_index}.paragraph_{paragraph_index}"
                if len(text) < 40:
                    issues.append(f"{prefix}:text_too_short")
                paragraph_type = paragraph.get("paragraph_type")
                support_ids = paragraph.get("support_ids") or []
                if paragraph_type not in {"transition", "limitation"}:
                    if not support_ids:
                        issues.append(f"{prefix}:support_missing")
                    unknown = [item for item in support_ids if item not in allowed]
                    if unknown:
                        issues.append(f"{prefix}:unknown_support:{','.join(unknown)}")
        measured = thesis_quality_service._word_count("\n".join(text_parts), str((brief.get("thesis_requirements") or {}).get("language") or ""))
        budget = int(spec.get("word_budget") or 0)
        minimum = self.minimum_word_count(task)
        if measured < minimum:
            issues.append(f"chapter_word_count_below_contract_minimum:{measured}/{minimum}/{budget}")
        if paragraph_count < 3:
            issues.append("chapter_paragraph_count_insufficient")
        return issues

    def surgical_repair(self, task: dict, latest: dict, review: dict) -> dict:
        """Apply only monotonic deletions and verified support bindings from paragraph audit issues."""
        repaired = deepcopy(latest)
        chapter = repaired.get("chapter") or {}
        sections = chapter.get("sections") or []
        paragraph_locations = {
            str(paragraph.get("id") or ""): (section, paragraph)
            for section in sections if isinstance(section, dict)
            for paragraph in section.get("paragraphs") or [] if isinstance(paragraph, dict)
        }
        allowed_ids = {
            item["id"] for item in ResearchClaimRepository.get_by_run(task.get("run_id"))
            if item.get("status") == "supported"
        }
        allowed_ids.update(item["id"] for item in self.artifact_support(task.get("run_id")))
        allowed_ids.update({"brief:research_question", "brief:objective", "brief:scope", "brief:methodology"})
        issues = (
            ((review.get("quality_gates") or {}).get("layers") or {})
            .get("independent_review", {}).get("issues") or []
        )
        changes: list[dict] = []
        unresolved: list[dict] = []
        for issue in issues:
            target = str(issue.get("target") or "")
            location = paragraph_locations.get(target)
            if not location:
                unresolved.append(issue)
                continue
            section, paragraph = location
            instruction = " ".join(
                str(issue.get(key) or "") for key in ("reason", "required_change")
            )
            requested_ids = set(re.findall(
                r"(?:claim_[A-Za-z0-9_]+|experiment:[A-Za-z0-9_]+|brief:[A-Za-z0-9_]+)",
                instruction,
            )) & allowed_ids
            bind_requested = any(marker in instruction.casefold() for marker in (
                "bind", "补绑", "绑定", "support_id",
            ))
            added_ids = sorted(requested_ids - set(paragraph.get("support_ids") or [])) if bind_requested else []
            if added_ids:
                paragraph["support_ids"] = [*(paragraph.get("support_ids") or []), *added_ids]
                changes.append({"target": target, "operation": "bind", "support_ids": added_ids})
                continue
            delete_requested = any(marker in instruction.casefold() for marker in (
                "delete", "remove", "删除", "移除", "无直接证据", "not directly", "not supported",
            ))
            if not delete_requested:
                unresolved.append(issue)
                continue
            original = str(paragraph.get("text") or "")
            fragments = self._exact_deletion_fragments(original, instruction)
            if fragments:
                revised = original
                for fragment in fragments:
                    revised = revised.replace(fragment, "", 1)
                revised = self._clean_deletion_spacing(revised)
                deleted = " | ".join(fragments)
            else:
                sentence = self._deletion_sentence(original, instruction)
                if not sentence:
                    unresolved.append(issue)
                    continue
                revised = self._remove_exact_sentence(original, sentence)
                deleted = sentence
            if revised == original:
                unresolved.append(issue)
                continue
            if revised:
                paragraph["text"] = revised
            else:
                section["paragraphs"] = [item for item in section.get("paragraphs") or [] if item is not paragraph]
                paragraph_locations.pop(target, None)
            changes.append({"target": target, "operation": "delete", "text": deleted[:240]})
        repaired["summary"] = "按独立分段审计执行单调外科修复；正文只删除原句或补绑已冻结支持。"
        repaired["claims"] = []
        return {"result": repaired, "changes": changes, "unresolved": unresolved}

    @classmethod
    def _deletion_sentence(cls, paragraph: str, instruction: str) -> str | None:
        sentences = [item for item in re.split(r"(?<=[.!?。！？])\s+", paragraph.strip()) if item]
        if not sentences:
            return None
        quoted = re.findall(r"['‘“]([^'’”]{8,})(?:['’”]|$)", instruction)
        terms = cls._repair_terms(instruction)
        scored = []
        for index, sentence in enumerate(sentences):
            lowered = sentence.casefold()
            quote_score = max(
                (100 + min(len(value), 100) for value in quoted if value.casefold() in lowered),
                default=0,
            )
            if not quote_score:
                quote_score = max(
                    (60 for value in quoted if value[:32].casefold() in lowered),
                    default=0,
                )
            overlap = len(terms & cls._repair_terms(sentence))
            scored.append((quote_score + overlap * 4, overlap, -index, sentence))
        score, overlap, _index, sentence = max(scored)
        return sentence if score >= 60 or overlap >= 3 else None

    @staticmethod
    def _exact_deletion_fragments(paragraph: str, instruction: str) -> list[str]:
        fragments = []
        for pattern in (r"'([^']{8,})'", r"‘([^’]{8,})’", r'“([^”]{8,})”'):
            for value in re.findall(pattern, instruction):
                if value in paragraph and value not in fragments:
                    fragments.append(value)
        return fragments

    @staticmethod
    def _clean_deletion_spacing(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r",\s*,", ",", text)
        text = re.sub(r",\s*\.", ".", text)
        return text

    @staticmethod
    def _remove_exact_sentence(paragraph: str, sentence: str) -> str:
        revised = paragraph.replace(sentence, "", 1)
        return re.sub(r"\s+", " ", revised).strip()

    @staticmethod
    def _repair_terms(text: str) -> set[str]:
        stop = {
            "claim", "statement", "support", "supported", "directly", "bound", "available",
            "delete", "remove", "phrase", "sentence", "evidence", "required", "change",
            "该句", "该段", "删除", "支持", "证据", "表述", "直接", "短语",
        }
        lowered = text.casefold()
        terms = {
            token for token in re.findall(r"[a-z][a-z0-9_-]{4,}", lowered) if token not in stop
        }
        for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
            terms.update(
                sequence[index:index + 2]
                for index in range(len(sequence) - 1)
                if sequence[index:index + 2] not in stop
            )
        return terms

    def minimum_word_count(self, task: dict) -> int:
        budget = int(self.spec_from_task(task).get("word_budget") or 0)
        # Institutions constrain the dissertation as a whole, not every chapter
        # by the same ratio. Keep a substantive structural floor here and enforce
        # the exact institutional range after deterministic full-thesis assembly.
        return max(500, math.ceil(budget * 0.5)) if budget else 500

    @staticmethod
    def word_count(task: dict, latest: dict) -> int:
        chapter = latest.get("chapter") if isinstance(latest, dict) else None
        if not isinstance(chapter, dict):
            return 0
        text = "\n".join(
            str(paragraph.get("text") or "")
            for section in chapter.get("sections") or []
            if isinstance(section, dict)
            for paragraph in section.get("paragraphs") or []
            if isinstance(paragraph, dict)
        )
        brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
        language = str((brief.get("thesis_requirements") or {}).get("language") or "")
        return thesis_quality_service._word_count(text, language)

    @staticmethod
    def artifact_support(run_id: str | None) -> list[dict]:
        support = []
        for result in ExperimentResultRepository.get_by_run(run_id) if run_id else []:
            if result.get("status") != "completed":
                continue
            metrics = result.get("metrics") or {}
            protocol = ExperimentProtocolRepository.get_by_id(result.get("protocol_id")) or {}
            support.append({
                "id": f"experiment:{result['id']}",
                "protocol_id": result.get("protocol_id"),
                "protocol": {
                    key: protocol.get(key)
                    for key in (
                        "research_question", "independent_variables", "dependent_variables",
                        "datasets", "metrics", "baselines", "method_details",
                        "stopping_conditions", "expected_risks",
                    )
                },
                "summary": result.get("summary"),
                "retrieval_configuration": metrics.get("retrieval_configuration"),
                "benchmark_design": metrics.get("benchmark_design"),
                "rows": metrics.get("rows"),
                "statistical_analysis": metrics.get("statistical_analysis"),
                "preregistration_trace": metrics.get("preregistration_trace"),
                "reproduction": metrics.get("reproduction"),
                "publishable": metrics.get("publishable"),
            })
        return support

    def can_assemble(self, run_id: str) -> bool:
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        chapters = self.resolved_chapters(run_id)
        return (
            (brief.get("thesis_requirements") or {}).get("status") == "confirmed"
            and bool(chapters)
            and all(item.get("status") == "completed" and not self.validate_output(item, (item.get("outputs") or [{}])[-1]) for item in chapters)
        )

    def total_word_adjustment(self, run_id: str) -> dict | None:
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        requirements = brief.get("thesis_requirements") or {}
        minimum = int(requirements.get("minimum_word_count") or 0)
        maximum = int(requirements.get("maximum_word_count") or 0)
        chapters = self.resolved_chapters(run_id)
        if not chapters or not all(item.get("status") == "completed" for item in chapters):
            return None
        counts = {item["id"]: self.word_count(item, (item.get("outputs") or [{}])[-1]) for item in chapters}
        total = sum(counts.values())
        if minimum and total < minimum:
            task = max(
                chapters,
                key=lambda item: int(self.spec_from_task(item).get("word_budget") or 0) - counts[item["id"]],
            )
            target = counts[task["id"]] + (minimum - total) + 60
            return {"task": task, "direction": "expand", "target": target, "total": total, "minimum": minimum, "maximum": maximum}
        if maximum and total > maximum:
            task = max(
                chapters,
                key=lambda item: counts[item["id"]] - int(self.spec_from_task(item).get("word_budget") or 0),
            )
            target = max(self.minimum_word_count(task), counts[task["id"]] - (total - maximum) - 60)
            return {"task": task, "direction": "condense", "target": target, "total": total, "minimum": minimum, "maximum": maximum}
        return None

    @staticmethod
    def resolved_chapters(run_id: str) -> list[dict]:
        tasks = [
            item for item in TaskRepository.get_all(run_id=run_id)
            if item.get("task_type") == "thesis_chapter"
        ]
        roots = [item for item in tasks if not item.get("revision_of_task_id")]
        resolved = []
        for root in roots:
            approved = [
                item for item in tasks
                if item.get("revision_of_task_id") == root["id"]
                and item.get("status") == "completed"
            ]
            resolved.append(max(approved, key=lambda item: str(item.get("created_at") or ""), default=root))
        return resolved

    def assemble(self, run: dict, title: str) -> str:
        run_id = run["id"]
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        tasks = self.resolved_chapters(run_id)
        tasks.sort(key=lambda item: self.spec_from_task(item).get("chapter_index", 999))
        claims = {item["id"]: item for item in ResearchClaimRepository.get_by_run(run_id) if item.get("status") == "supported"}
        evidence = EvidenceRepository.get_by_run(run_id)
        sources = {item["id"]: item for item in evidence.get("sources") or []}
        links_by_claim: dict[str, list[dict]] = {}
        for link in evidence.get("links") or []:
            if link.get("relation_type") == "supports" and link.get("source_id") in sources:
                links_by_claim.setdefault(link["claim_id"], []).append(link)
        used_source_ids: list[str] = []
        for task in tasks:
            chapter = (task.get("outputs") or [{}])[-1].get("chapter") or {}
            for section in chapter.get("sections") or []:
                for paragraph in section.get("paragraphs") or []:
                    for support_id in paragraph.get("support_ids") or []:
                        for link in links_by_claim.get(support_id, []):
                            if link["source_id"] not in used_source_ids:
                                used_source_ids.append(link["source_id"])
        citation_index = {source_id: index + 1 for index, source_id in enumerate(used_source_ids)}
        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        discipline = brief.get("discipline") or {}
        profile = brief.get("methodology_profile") or {}
        requirements = brief.get("thesis_requirements") or {}
        citation_style = str(requirements.get("citation_style") or "")
        language = str(requirements.get("language") or "").lower()
        chinese = any(marker in language for marker in ("zh", "中文", "chinese"))
        institution = str(requirements.get("institution") or "")
        programme = str(requirements.get("programme") or "")
        degree = "硕士学位论文" if chinese else "Master's Dissertation"
        contents_heading = "目录" if chinese else "Table of Contents"
        provenance_heading = "研究与人工智能来源声明" if chinese else "Research and AI Provenance Statement"
        provenance = (
            "本文档由 ResearchGroup-Agent 基于所列真实材料、方法工件和审计记录自动生成；"
            "不得将其表述为未经人工智能协助的学生原创提交，正式提交前须由责任作者和院校按规则复核。"
            if chinese else
            "This document was generated by ResearchGroup-Agent from the listed real sources, method artifacts, "
            "and audit records. It must not be represented as unaided student authorship and requires responsible "
            "author and institutional review before any formal submission."
        )
        top_claims = list(claims.values())[:3]
        abstract = "；".join(item["statement"] for item in top_claims) or "当前没有通过完整质量门的核心结论。"
        lines = [
            f"# {title}", "",
            f"**{institution}**", "", f"**{programme} — {degree}**", "",
            "**类型:** Master Thesis　**交付等级:** `master_thesis_candidate`　"
            f"**装配时间:** {now}", "",
            f"## {provenance_heading}", "", provenance, "",
            "## 摘要", "", abstract, "",
            "关键词：" + "；".join(filter(None, [
                str(discipline.get("field") or ""), str(discipline.get("subfield") or ""),
                str(profile.get("family") or ""), str(profile.get("epistemic_mode") or ""),
            ])), "", f"## {contents_heading}", "",
            *[f"- {self.spec_from_task(task).get('chapter_name')}" for task in tasks], "",
        ]
        trace_rows = []
        for task in tasks:
            chapter = (task.get("outputs") or [{}])[-1].get("chapter") or {}
            lines.extend([f"## {chapter.get('name')}", ""])
            for section in chapter.get("sections") or []:
                lines.extend([f"### {section.get('heading')}", ""])
                for paragraph in section.get("paragraphs") or []:
                    support_ids = paragraph.get("support_ids") or []
                    cited_sources = [
                        sources[link["source_id"]]
                        for support_id in support_ids for link in links_by_claim.get(support_id, [])
                        if link["source_id"] in citation_index
                    ]
                    artifact_support = [
                        support_id for support_id in support_ids
                        if support_id in claims and claims[support_id].get("evidence_ids") and not links_by_claim.get(support_id)
                    ]
                    rendered_citation = citation_style_service.in_text(
                        cited_sources, citation_index, citation_style,
                    )
                    suffix = f" {rendered_citation}" if rendered_citation else ""
                    if artifact_support:
                        suffix += " " + " ".join(f"〔工件结论:{item}〕" for item in artifact_support)
                    lines.extend([str(paragraph.get("text") or "").strip() + suffix, ""])
                    trace_rows.append((paragraph.get("id"), task["id"], support_ids))
        ethics = brief.get("ethics_plan") or {}
        lines.extend([
            "## 研究贡献与局限", "",
            str(brief.get("expected_contribution") or "研究贡献以各章节通过审核的结论为准。"), "",
            "本论文结论仅适用于冻结的研究范围、材料、方法和质量控制；未观察总体与其他语境不得直接外推。", "",
            "## 伦理声明与数据可用性", "",
            f"伦理状态：{ethics.get('status', '未声明')}；审批编号：{ethics.get('approval_reference') or '不适用/未提供'}。", "",
            f"数据可用性与材料范围：{brief.get('data_availability') or '未提供'}。", "",
            "## 参考文献", "",
        ])
        for source_id in used_source_ids:
            source = sources[source_id]
            lines.append(citation_style_service.bibliography_entry(
                source, citation_index[source_id], citation_style,
            ))
        lines.extend(["", "## 可追溯附录", "", "| Paragraph | Task | Support IDs |", "| --- | --- | --- |"]) 
        for paragraph_id, task_id, support_ids in trace_rows:
            lines.append(f"| `{paragraph_id}` | `{task_id}` | {', '.join(f'`{item}`' for item in support_ids)} |")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def spec_from_task(task: dict) -> dict:
        match = re.search(r"【thesis_chapter_spec】(\{[^\n]+\})", str(task.get("description") or ""))
        if not match:
            return {}
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def is_writing_task(task: dict) -> bool:
        return task.get("task_type") in ThesisChapterService.WRITING_TYPES


thesis_chapter_service = ThesisChapterService()
