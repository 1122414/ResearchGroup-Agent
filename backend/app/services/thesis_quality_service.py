from __future__ import annotations

import re


class ThesisQualityService:
    """Fail-closed checks for labeling an artifact as a complete master's thesis."""

    def evaluate(
        self,
        report: str,
        brief: dict,
        claims: list[dict],
        tasks: list[dict],
        evidence: dict,
        experiment_results: list[dict],
    ) -> dict:
        requirements = brief.get("thesis_requirements") or {}
        checks: dict[str, dict] = {}
        checks["institutional_requirements"] = self._check(
            requirements.get("status") == "confirmed",
            "目标院校与专业论文规范尚未确认",
        )
        measured_words = self._word_count(report, str(requirements.get("language") or ""))
        target_words = int(requirements.get("target_word_count") or 0)
        checks["length"] = self._check(
            target_words > 0 and measured_words >= target_words,
            f"有效篇幅 {measured_words}，要求至少 {target_words}",
        )

        headings = self._headings(report)
        required_chapters = [str(item).strip() for item in requirements.get("required_chapters") or [] if str(item).strip()]
        missing_chapters = [chapter for chapter in required_chapters if not self._chapter_present(chapter, headings)]
        checks["required_chapters"] = self._check(
            bool(required_chapters) and not missing_chapters,
            "缺少章节：" + "、".join(missing_chapters) if missing_chapters else f"已覆盖 {len(required_chapters)} 个必需章节",
        )
        thin_chapters = self._thin_chapters(report, required_chapters, max(300, target_words // max(len(required_chapters) * 4, 1)))
        checks["chapter_substance"] = self._check(
            not thin_chapters, "内容过薄章节：" + "、".join(thin_chapters) if thin_chapters else "章节内容达到最低实质阈值",
        )

        lowered = report.lower()
        checks["front_matter"] = self._check(
            any(marker in lowered for marker in ("## 摘要", "## abstract"))
            and any(marker in lowered for marker in ("关键词", "keywords")),
            "摘要或关键词缺失",
        )
        checks["contribution_and_limitations"] = self._check(
            any(marker in lowered for marker in ("贡献", "contribution"))
            and any(marker in lowered for marker in ("局限", "limitation")),
            "贡献或局限章节缺失",
        )
        checks["ethics_and_data_statement"] = self._check(
            any(marker in lowered for marker in ("伦理", "ethics"))
            and any(marker in lowered for marker in ("数据可用", "data availability", "材料可用")),
            "伦理声明或数据/材料可用性声明缺失",
        )

        reference_count, cited_numbers, reference_numbers = self._reference_stats(report)
        minimum_references = max(1, int(requirements.get("minimum_references") or 20))
        checks["references"] = self._check(
            reference_count >= minimum_references,
            f"参考文献 {reference_count}，要求至少 {minimum_references}",
        )
        checks["citation_consistency"] = self._check(
            bool(cited_numbers) and cited_numbers <= reference_numbers,
            f"正文引用={sorted(cited_numbers)}，参考文献编号={sorted(reference_numbers)}",
        )

        supported = [item for item in claims if item.get("status") == "supported"]
        minimum_claims = max(1, int(requirements.get("minimum_supported_claims") or 5))
        checks["supported_claims"] = self._check(
            len(supported) >= minimum_claims,
            f"受支持结论 {len(supported)}，要求至少 {minimum_claims}",
        )
        family = brief.get("methodology_family") or (brief.get("methodology_profile") or {}).get("family")
        method_artifacts = [
            task for task in tasks
            if task.get("status") == "completed" and task.get("task_type") in {"result_analysis", "experiment_design"}
        ]
        publishable_experiments = [
            item for item in experiment_results if (item.get("metrics") or {}).get("publishable") is True
        ]
        checks["method_artifact"] = self._check(
            bool(method_artifacts) and (family != "computational" or bool(publishable_experiments) or self._has_analysis_artifact(method_artifacts)),
            f"方法族={family}；完成分析/实验任务={len(method_artifacts)}；可发布实验={len(publishable_experiments)}",
        )
        checks["evidence_inventory"] = self._check(
            bool((evidence or {}).get("sources")) or any(item.get("evidence_ids") for item in supported),
            "没有文献来源或方法工件证据清单",
        )

        issues = [f"{name}:{item['detail']}" for name, item in checks.items() if not item["passed"]]
        return {
            "passed": not issues,
            "checks": checks,
            "issues": issues,
            "measured_word_count": measured_words,
            "target_word_count": target_words,
            "reference_count": reference_count,
            "required_chapter_count": len(required_chapters),
            "policy": "all_thesis_checks_required",
        }

    @staticmethod
    def _check(passed: bool, detail: str) -> dict:
        return {"passed": bool(passed), "detail": detail}

    @staticmethod
    def _word_count(text: str, language: str) -> int:
        cjk = len(re.findall(r"[\u3400-\u9fff]", text))
        latin_words = len(re.findall(r"\b[A-Za-z][A-Za-z0-9'-]*\b", text))
        return cjk + latin_words if any(marker in language.lower() for marker in ("zh", "中文", "chinese")) else latin_words + cjk

    @staticmethod
    def _headings(report: str) -> list[str]:
        return [re.sub(r"^#+\s*", "", line).strip().lower() for line in report.splitlines() if re.match(r"^#{1,4}\s+", line)]

    @staticmethod
    def _chapter_present(chapter: str, headings: list[str]) -> bool:
        normalized = re.sub(r"[\s\d.、:_-]+", "", chapter).lower()
        return any(normalized in re.sub(r"[\s\d.、:_-]+", "", heading) for heading in headings)

    def _thin_chapters(self, report: str, required: list[str], minimum: int) -> list[str]:
        lines = report.splitlines()
        positions = [(index, line) for index, line in enumerate(lines) if re.match(r"^#{1,3}\s+", line)]
        thin = []
        for chapter in required:
            match = next(((index, line) for index, line in positions if self._chapter_present(chapter, [line])), None)
            if not match:
                continue
            start = match[0] + 1
            end = next((index for index, _ in positions if index > match[0]), len(lines))
            if self._word_count("\n".join(lines[start:end]), "zh") < minimum:
                thin.append(chapter)
        return thin

    @staticmethod
    def _reference_stats(report: str) -> tuple[int, set[int], set[int]]:
        reference_match = re.search(r"(?im)^##+\s*(?:参考文献|references)\s*$", report)
        body = report[: reference_match.start()] if reference_match else report
        references = report[reference_match.end():] if reference_match else ""
        cited = {int(value) for value in re.findall(r"\[(\d+)\]", body)}
        numbered = {int(value) for value in re.findall(r"(?m)^\s*\[(\d+)\]", references)}
        return len(numbered), cited, numbered

    @staticmethod
    def _has_analysis_artifact(tasks: list[dict]) -> bool:
        for task in tasks:
            outputs = task.get("outputs") or []
            if outputs and isinstance(outputs[-1], dict) and outputs[-1].get("analysis_artifact"):
                return True
        return False


thesis_quality_service = ThesisQualityService()
