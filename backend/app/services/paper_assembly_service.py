from __future__ import annotations

import json
import re
from datetime import datetime

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import (
    EvidenceRepository,
    ExperimentFindingRepository,
    ExperimentResultRepository,
    ResearchClaimRepository,
    ResearchHypothesisRepository,
    ResearchUncertaintyRepository,
    TaskRepository,
)

_SURVEY_MARKERS = ("综述", "调研", "survey", "review", "github", "landscape", "现状", "对比")


class PaperAssemblyService:
    """Assemble a structured, grounded document from the research knowledge graph.

    Instead of aggregating truncated task summaries, this reads claims, evidence
    links, verified sources, experiment results/findings, hypotheses and open
    uncertainties, and emits a paper (with experiments) or a survey/report (no
    experiments). Every grounded claim carries inline [n] citations resolved to a
    verified source in the References list; claims without evidence are moved to a
    clearly labelled "insufficiently supported" subsection rather than presented
    as conclusions. An optional narrative (LLM prose) is embedded for readability,
    but the grounded skeleton — claims, tables, figures, references — is built
    deterministically so citations cannot be fabricated.
    """

    def detect_mode(self, run: dict, tasks: list[dict] | None = None) -> str:
        tasks = tasks if tasks is not None else TaskRepository.get_all(run_id=run["id"])
        has_experiment = ExperimentResultRepository.get_by_run(run["id"]) or any(
            task.get("task_type") == "experiment_design" for task in tasks
        )
        if has_experiment:
            return "paper"
        goal = primary_goal(str(run.get("research_goal", ""))).lower()
        if any(marker in goal for marker in _SURVEY_MARKERS):
            return "survey"
        return "paper"

    def assemble(self, run: dict, mode: str | None = None, narrative: str = "") -> str:
        run_id = run["id"]
        goal = primary_goal(str(run.get("research_goal", "")))
        tasks = TaskRepository.get_all(run_id=run_id)
        mode = mode or self.detect_mode(run, tasks)

        evidence = EvidenceRepository.get_by_run(run_id)
        claims = ResearchClaimRepository.get_by_run(run_id)
        hypotheses = ResearchHypothesisRepository.get_by_run(run_id)
        uncertainties = ResearchUncertaintyRepository.get_by_run(run_id)
        experiment_results = ExperimentResultRepository.get_by_run(run_id)
        experiment_findings = ExperimentFindingRepository.get_by_run(run_id)

        source_map = {item["id"]: item for item in evidence["sources"]}
        links_by_claim: dict[str, list[dict]] = {}
        for link in evidence["links"]:
            links_by_claim.setdefault(link["claim_id"], []).append(link)

        citation_index = self._build_citation_index(claims, links_by_claim, source_map)
        grounded_claims = [c for c in claims if links_by_claim.get(c["id"])]
        unsupported_claims = [c for c in claims if not links_by_claim.get(c["id"])]

        time_label = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        doc_type = "研究论文" if mode == "paper" else "调研报告"
        lines = [
            f"# {doc_type}：{goal}",
            "",
            f"**类型:** {'Paper' if mode == 'paper' else 'Survey/Report'}　**生成时间:** {time_label}",
            f"**证据来源:** {len(source_map)} 条　**结论:** {len(claims)} 条（已支撑 {len(grounded_claims)}）　**实验:** {len(experiment_results)} 次",
            "",
            "---",
            "",
        ]

        lines += self._abstract_section(goal, grounded_claims, experiment_results, mode)
        narrative_block = self._narrative_block(narrative)
        if mode == "paper":
            lines += self._intro_section(goal, hypotheses, narrative_block)
            lines += self._related_work_section(grounded_claims, citation_index, source_map)
            lines += self._method_section(hypotheses, narrative_block)
            lines += self._experiments_section(experiment_results, tasks)
            lines += self._results_section(grounded_claims, citation_index, source_map, links_by_claim, experiment_findings)
            lines += self._discussion_section(narrative_block, unsupported_claims, uncertainties)
            lines += self._limitations_section(unsupported_claims, uncertainties)
            lines += self._conclusion_section(grounded_claims, experiment_results)
        else:
            lines += self._scope_section(goal, narrative_block)
            lines += self._themes_section(grounded_claims, citation_index, source_map, links_by_claim)
            lines += self._comparative_section(grounded_claims, citation_index, source_map)
            lines += self._findings_section(grounded_claims, citation_index, links_by_claim)
            lines += self._gaps_section(unsupported_claims, uncertainties)
            lines += self._conclusion_section(grounded_claims, experiment_results)

        lines += self._references_section(citation_index, source_map)
        return "\n".join(lines).strip() + "\n"

    # --- citation handling -------------------------------------------------

    def _build_citation_index(self, claims, links_by_claim, source_map) -> dict[str, int]:
        index: dict[str, int] = {}
        for claim in claims:
            for link in links_by_claim.get(claim["id"], []):
                source_id = link["source_id"]
                if source_id in source_map and source_id not in index:
                    index[source_id] = len(index) + 1
        return index

    def _cite(self, claim, links_by_claim, citation_index) -> str:
        numbers = sorted(
            {citation_index[link["source_id"]] for link in links_by_claim.get(claim["id"], []) if link["source_id"] in citation_index}
        )
        return f" [{', '.join(str(n) for n in numbers)}]" if numbers else ""

    # --- shared sections ---------------------------------------------------

    def _abstract_section(self, goal, grounded_claims, experiment_results, mode) -> list[str]:
        top = grounded_claims[:3]
        body = (
            f"本文围绕“{goal}”开展研究，基于可核验证据归纳出 {len(grounded_claims)} 条有支撑的结论"
            + (f"，并通过 {len(experiment_results)} 次可复现实验加以检验。" if experiment_results else "。")
        )
        lines = ["## 摘要", "", body, ""]
        for claim in top:
            lines.append(f"- {claim['statement']}")
        if top:
            lines.append("")
        return lines

    def _conclusion_section(self, grounded_claims, experiment_results) -> list[str]:
        lines = ["## 结论", ""]
        if grounded_claims:
            lines.append("综合证据与实验，本研究得到以下有支撑的核心结论：")
            lines.append("")
            for claim in grounded_claims[:6]:
                lines.append(f"- ({claim['status']}, 置信度 {round(claim.get('confidence', 0) * 100)}%) {claim['statement']}")
        else:
            lines.append("当前尚无获得证据充分支撑的结论，需要补充检索或实验后再形成最终结论。")
        lines.append("")
        return lines

    def _references_section(self, citation_index, source_map) -> list[str]:
        if not citation_index:
            return ["## 参考文献", "", "本报告暂无可核验来源，未生成参考文献（避免编造引用）。", ""]
        lines = ["## 参考文献", ""]
        for source_id, number in sorted(citation_index.items(), key=lambda kv: kv[1]):
            source = source_map.get(source_id, {})
            citation = " ".join(
                str(item)
                for item in [
                    (source.get("authors") or "").strip(),
                    f"({source.get('year')})" if source.get("year") else "",
                    (source.get("title") or "").strip() + ".",
                    (source.get("venue") or "").strip(),
                ]
                if item
            ).strip()
            locator = source.get("doi") or source.get("url") or ""
            lines.append(f"[{number}] {citation} {locator}".rstrip())
        lines.append("")
        return lines

    # --- paper-mode sections ----------------------------------------------

    def _intro_section(self, goal, hypotheses, narrative_block) -> list[str]:
        lines = ["## 1. 引言", ""]
        lines.append(narrative_block.get("intro") or f"本研究针对“{goal}”，明确研究问题并提出可检验假设，随后通过证据与实验逐步验证。")
        lines.append("")
        if hypotheses:
            lines.append("**研究假设:**")
            lines.append("")
            for hyp in hypotheses[:5]:
                lines.append(f"- ({hyp['status']}) {hyp['statement']}")
            lines.append("")
        return lines

    def _related_work_section(self, grounded_claims, citation_index, source_map) -> list[str]:
        lines = ["## 2. 相关工作", ""]
        if not citation_index:
            lines.append("尚未收集到可核验的相关工作来源。")
            lines.append("")
            return lines
        for source_id, number in sorted(citation_index.items(), key=lambda kv: kv[1])[: settings.report_evidence_paper_limit]:
            source = source_map.get(source_id, {})
            lines.append(f"- [{number}] {(source.get('title') or '').strip()} — {(source.get('authors') or '').strip()} ({source.get('year') or 'n.d.'})")
        lines.append("")
        return lines

    def _method_section(self, hypotheses, narrative_block) -> list[str]:
        lines = ["## 3. 方法", ""]
        lines.append(narrative_block.get("method") or "本节描述围绕研究假设设计的研究与实验方法，包括数据来源、对照设置与评测指标。")
        lines.append("")
        return lines

    def _experiments_section(self, experiment_results, tasks) -> list[str]:
        lines = ["## 4. 实验", ""]
        if not experiment_results:
            lines.append("本研究未执行可复现实验（或实验任务未通过审批）。")
            lines.append("")
            return lines
        for result in experiment_results:
            lines.append(f"### 实验 `{result['status']}`：{result['summary']}")
            lines.append("")
            metrics = result.get("metrics") or {}
            table = self._metrics_table(metrics)
            if table:
                lines.extend(table)
                lines.append("")
            for artifact in (result.get("artifacts") or []):
                if str(artifact).lower().endswith(".png"):
                    lines.append(f"![experiment figure]({artifact})")
                    lines.append("")
        return lines

    def _results_section(self, grounded_claims, citation_index, source_map, links_by_claim, experiment_findings) -> list[str]:
        lines = ["## 5. 结果", ""]
        if not grounded_claims and not experiment_findings:
            lines.append("尚无获得证据支撑的结果。")
            lines.append("")
            return lines
        for claim in grounded_claims:
            lines.append(f"- ({claim['status']}) {claim['statement']}{self._cite(claim, links_by_claim, citation_index)}")
        findings_by_claim: dict[str, list[dict]] = {}
        for finding in experiment_findings:
            findings_by_claim.setdefault(finding.get("claim_id"), []).append(finding)
        if experiment_findings:
            lines.append("")
            lines.append("**实验 findings:**")
            lines.append("")
            for finding in experiment_findings:
                lines.append(f"- {finding['relation_type']}（置信度 {round(finding.get('confidence', 0) * 100)}%）：{finding['statement']}")
        lines.append("")
        return lines

    def _discussion_section(self, narrative_block, unsupported_claims, uncertainties) -> list[str]:
        lines = ["## 6. 讨论", ""]
        lines.append(narrative_block.get("discussion") or "本节讨论结果的意义、与相关工作的关系以及对研究假设的影响。")
        lines.append("")
        return lines

    def _limitations_section(self, unsupported_claims, uncertainties) -> list[str]:
        lines = ["## 7. 局限性与未决问题", ""]
        if unsupported_claims:
            lines.append("**证据不足、需谨慎对待的陈述:**")
            lines.append("")
            for claim in unsupported_claims[:6]:
                lines.append(f"- {claim['statement']}")
            lines.append("")
        open_uncertainties = [u for u in uncertainties if u.get("status") == "open"]
        if open_uncertainties:
            lines.append("**未解决的问题:**")
            lines.append("")
            for item in open_uncertainties[:6]:
                lines.append(f"- ({item.get('severity', 'medium')}) {item['description']}")
            lines.append("")
        if not unsupported_claims and not open_uncertainties:
            lines.append("未发现显著的证据缺口或未决问题。")
            lines.append("")
        return lines

    # --- survey-mode sections ---------------------------------------------

    def _scope_section(self, goal, narrative_block) -> list[str]:
        return ["## 1. 范围与方法", "", narrative_block.get("intro") or f"本报告围绕“{goal}”系统梳理相关工作、方法与现状，并标注证据来源。", ""]

    def _themes_section(self, grounded_claims, citation_index, source_map, links_by_claim) -> list[str]:
        lines = ["## 2. 主题与发现", ""]
        if not grounded_claims:
            lines.append("尚无获得证据支撑的主题性发现。")
            lines.append("")
            return lines
        for claim in grounded_claims:
            lines.append(f"- {claim['statement']}{self._cite(claim, links_by_claim, citation_index)}")
        lines.append("")
        return lines

    def _comparative_section(self, grounded_claims, citation_index, source_map) -> list[str]:
        lines = ["## 3. 对比分析", ""]
        if not citation_index:
            lines.append("暂无可核验来源用于对比。")
            lines.append("")
            return lines
        lines.append("| # | 来源 | 年份 | 主题 |")
        lines.append("| --- | --- | --- | --- |")
        for source_id, number in sorted(citation_index.items(), key=lambda kv: kv[1]):
            source = source_map.get(source_id, {})
            lines.append(f"| {number} | {(source.get('authors') or '').strip()[:40]} | {source.get('year') or 'n.d.'} | {(source.get('title') or '').strip()[:60]} |")
        lines.append("")
        return lines

    def _findings_section(self, grounded_claims, citation_index, links_by_claim) -> list[str]:
        lines = ["## 4. 关键结论", ""]
        if not grounded_claims:
            lines.append("尚无有支撑的关键结论。")
            lines.append("")
            return lines
        for claim in grounded_claims[:8]:
            lines.append(f"- ({claim['status']}) {claim['statement']}{self._cite(claim, links_by_claim, citation_index)}")
        lines.append("")
        return lines

    def _gaps_section(self, unsupported_claims, uncertainties) -> list[str]:
        return self._limitations_section(unsupported_claims, uncertainties)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _metrics_table(metrics: dict) -> list[str]:
        rows = metrics.get("rows") if isinstance(metrics, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return []
        columns = list(rows[0].keys())
        lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
        for row in rows[:12]:
            lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
        return lines

    @staticmethod
    def _narrative_block(narrative: str) -> dict[str, str]:
        if not narrative or not narrative.strip():
            return {}
        cleaned = re.sub(r"\[(source_[^\]\s]+)\]", "", narrative).strip()
        return {"intro": "", "method": "", "discussion": cleaned}


paper_assembly_service = PaperAssemblyService()
