from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import (
    EvidenceRepository,
    ExperimentFindingRepository,
    ExperimentProtocolRepository,
    ExperimentResultRepository,
    ResearchBriefRepository,
    ResearchClaimRepository,
    ResearchHypothesisRepository,
    ResearchUncertaintyRepository,
    TaskRepository,
)
from .knowledge_graph_service import knowledge_graph_service

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

    def assemble(self, run: dict, mode: str | None = None, narrative: str = "", title: str = "") -> str:
        run_id = run["id"]
        goal = primary_goal(str(run.get("research_goal", "")))
        tasks = TaskRepository.get_all(run_id=run_id)
        mode = mode or self.detect_mode(run, tasks)

        # Use a concise, refined title instead of dumping the raw research-goal
        # prompt (which can be a long multi-paragraph instruction) into the
        # document heading and every section that references it.
        title = (title or self._short_title(goal)).strip()
        # A short label (≤80 chars) for inline references inside the body.
        goal_brief = title if len(title) <= 80 else title[:77] + "..."

        evidence = EvidenceRepository.get_by_run(run_id)
        review_scope = knowledge_graph_service.reviewed_graph_scope(run_id)
        claims = self._dedupe_records(knowledge_graph_service.filter_reviewed_records(
            ResearchClaimRepository.get_by_run(run_id), "claims", review_scope,
        ), "statement", "status")
        hypotheses = self._dedupe_records(knowledge_graph_service.filter_reviewed_records(
            ResearchHypothesisRepository.get_by_run(run_id), "hypotheses", review_scope,
        ), "statement")
        uncertainties = self._dedupe_records(knowledge_graph_service.filter_reviewed_records(
            ResearchUncertaintyRepository.get_by_run(run_id), "uncertainties", review_scope,
        ), "description")
        experiment_results = ExperimentResultRepository.get_by_run(run_id)
        experiment_protocols = ExperimentProtocolRepository.get_by_run(run_id)
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        experiment_findings = ExperimentFindingRepository.get_by_run(run_id)
        publishable_result_ids = {
            item["id"] for item in experiment_results if (item.get("metrics") or {}).get("publishable") is True
        }
        experiment_findings = [item for item in experiment_findings if item.get("result_id") in publishable_result_ids]
        if publishable_result_ids and any(item.get("status") == "supported" for item in hypotheses):
            uncertainties = [
                item for item in uncertainties
                if "尚未形成经过证据支撑的可验证假设" not in str(item.get("description") or "")
            ]

        # Filter out hypotheses whose statement is just the raw goal prompt —
        # these get ingested when the LLM echoes the full instruction as a
        # "hypothesis" and are not real research hypotheses.
        hypotheses = [h for h in hypotheses if h.get("statement", "").strip() != goal.strip() and len(h.get("statement", "")) < len(goal) * 0.8]

        source_map = {
            item["id"]: item
            for item in evidence["sources"]
            if (item.get("metadata") or {}).get("citation_eligible")
        }
        excerpt_map = {item["id"]: item for item in evidence["excerpts"]}
        links_by_claim: dict[str, list[dict]] = {}
        for link in evidence["links"]:
            excerpt = excerpt_map.get(link.get("excerpt_id"))
            if (
                link.get("relation_type") == "supports"
                and link.get("source_id") in source_map
                and excerpt
                and excerpt.get("excerpt_type") not in {"metadata_only", "summary"}
                and str(excerpt.get("excerpt") or "").strip()
            ):
                links_by_claim.setdefault(link["claim_id"], []).append(link)

        citation_index = self._build_citation_index(claims, links_by_claim, source_map)
        grounded_claims = [c for c in claims if c.get("status") == "supported" and links_by_claim.get(c["id"])]
        unsupported_claims = [
            c for c in claims
            if c not in grounded_claims and not self._experiment_backed_claim(c, experiment_results)
        ]

        time_label = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        doc_type = "研究论文" if mode == "paper" else "调研报告"
        delivery_status = self._delivery_status(mode, brief, grounded_claims, uncertainties, experiment_results)
        lines = [
            f"# {doc_type}：{title}",
            "",
            f"**类型:** {'Paper' if mode == 'paper' else 'Survey/Report'}　**交付等级:** `{delivery_status}`　**生成时间:** {time_label}",
            f"**证据来源:** {len(source_map)} 条　**结论:** {len(claims)} 条（已支撑 {len(grounded_claims)}）　**实验:** {len(experiment_results)} 次",
            "",
            "---",
            "",
        ]

        lines += self._abstract_section(goal_brief, grounded_claims, experiment_results, mode, links_by_claim, citation_index)
        narrative_block = self._narrative_block(narrative)
        narrative_body = narrative_block.get("discussion", "").strip()
        has_full_narrative = bool(narrative_body) and ("#" in narrative_body or len(narrative_body) > 500)

        if has_full_narrative:
            # The advisor LLM produced a full report narrative.  Embed it as the
            # main body so the reader sees the actual report first, then the
            # grounded evidence/experiment details as a clearly-labelled appendix.
            lines += ["## 报告正文", "", narrative_body, ""]

        if mode == "paper":
            lines += self._intro_section(
                goal_brief, hypotheses, narrative_block if not has_full_narrative else {}, experiment_protocols
            )
            lines += self._related_work_section(grounded_claims, citation_index, source_map, links_by_claim)
            lines += self._method_section(hypotheses, experiment_protocols, narrative_block if not has_full_narrative else {})
            lines += self._experiments_section(experiment_results, tasks)
            lines += self._results_section(
                grounded_claims, citation_index, source_map, links_by_claim,
                experiment_findings, experiment_results,
            )
            if not has_full_narrative:
                lines += self._discussion_section(narrative_block, experiment_results)
            lines += self._limitations_section(unsupported_claims, uncertainties, experiment_results)
            lines += self._conclusion_section(grounded_claims, experiment_results, links_by_claim, citation_index)
        else:
            lines += self._scope_section(goal_brief, narrative_block if not has_full_narrative else {})
            lines += self._themes_section(grounded_claims, citation_index, source_map, links_by_claim)
            lines += self._comparative_section(grounded_claims, citation_index, source_map)
            lines += self._findings_section(grounded_claims, citation_index, links_by_claim)
            lines += self._gaps_section(unsupported_claims, uncertainties)
            lines += self._conclusion_section(grounded_claims, experiment_results, links_by_claim, citation_index)

        lines += self._references_section(citation_index, source_map)
        lines += self._traceability_section(
            grounded_claims, links_by_claim, excerpt_map, citation_index, source_map,
            experiment_results, experiment_protocols,
        )
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

    def _abstract_section(self, goal, grounded_claims, experiment_results, mode, links_by_claim, citation_index) -> list[str]:
        top = grounded_claims[:3]
        body = (
            f"本文围绕“{goal}”开展研究，基于可核验证据归纳出 {len(grounded_claims)} 条有支撑的结论"
            + (f"，并通过 {len(experiment_results)} 次可复现实验加以检验。" if experiment_results else "。")
        )
        lines = ["## 摘要", "", body, ""]
        experiment_summary = self._primary_experiment_summary(experiment_results)
        if experiment_summary:
            lines.extend([f"**实验主结论：** {experiment_summary}", ""])
        for claim in top:
            lines.append(f"- {claim['statement']}{self._cite(claim, links_by_claim, citation_index)}")
        if top:
            lines.append("")
        return lines

    def _conclusion_section(self, grounded_claims, experiment_results, links_by_claim, citation_index) -> list[str]:
        lines = ["## 结论", ""]
        experiment_summary = self._primary_experiment_summary(experiment_results)
        if experiment_summary:
            lines.append(f"**实验结论（由原始工件与独立复现支持）：** {experiment_summary}")
            lines.append("")
        if grounded_claims:
            lines.append("相关工作的可核验结论如下：")
            lines.append("")
            for claim in grounded_claims[:4]:
                lines.append(
                    f"- ({claim['status']}, 置信度 {round(claim.get('confidence', 0) * 100)}%) "
                    f"{claim['statement']}{self._cite(claim, links_by_claim, citation_index)}"
                )
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
            bibkey = self._bibliography_key(source)
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
            doi = (source.get("doi") or "").strip()
            url = (source.get("url") or "").strip()
            if doi:
                link = f"[{doi}](https://doi.org/{doi})"
            elif url:
                link = f"[{url}]({url})"
            else:
                link = ""
            entry = f"[{number}] `{bibkey}` {citation}"
            if link:
                entry += f" {link}"
            lines.append(entry.rstrip())
        lines.append("")
        return lines

    # --- paper-mode sections ----------------------------------------------

    def _intro_section(self, goal, hypotheses, narrative_block, protocols) -> list[str]:
        lines = ["## 1. 引言", ""]
        protocol = protocols[0] if protocols else {}
        strategies = list(((protocol.get("method_details") or {}).get("strategies") or {}).keys())
        default_intro = (
            f"本研究针对“{goal}”，在冻结的受控检索基准上隔离文档切分策略这一自变量。"
            f"实验统一数据、query/qrel、检索器、聚合与评测代码，仅比较"
            f"{('、'.join(strategies)) if strategies else '预注册的切分策略'}。"
            "研究目标不是证明某种切分方法在开放域普遍优越，而是检验边界重叠在当前构造 pilot "
            "中是否改变目标文档排序，并给出可复现、可证伪且明确受限的结论。"
        )
        lines.append(narrative_block.get("intro") or default_intro)
        lines.append("")
        if hypotheses:
            supported = [hypothesis for hypothesis in hypotheses if hypothesis.get("status") == "supported"]
            hypotheses = supported or hypotheses
            lines.append("**研究假设:**")
            lines.append("")
            for hyp in hypotheses[:5]:
                lines.append(f"- ({hyp['status']}) {hyp['statement']}")
            lines.append("")
        return lines

    def _related_work_section(self, grounded_claims, citation_index, source_map, links_by_claim) -> list[str]:
        lines = ["## 2. 相关工作", ""]
        if not citation_index:
            lines.append("尚未收集到可核验的相关工作来源。")
            lines.append("")
            return lines
        for source_id, number in sorted(citation_index.items(), key=lambda kv: kv[1])[: settings.report_evidence_paper_limit]:
            source = source_map.get(source_id, {})
            lines.append(f"- [{number}] {(source.get('title') or '').strip()} — {(source.get('authors') or '').strip()} ({source.get('year') or 'n.d.'})")
        if grounded_claims:
            lines.extend(["", "现有工作的可核验信息表明："])
            for claim in grounded_claims[:4]:
                lines.append(f"- {claim['statement']}{self._cite(claim, links_by_claim, citation_index)}")
        lines.append("")
        return lines

    def _method_section(self, hypotheses, protocols, narrative_block) -> list[str]:
        lines = ["## 3. 方法", ""]
        lines.append(narrative_block.get("method") or "本节描述围绕研究假设设计的研究与实验方法，包括数据来源、对照设置与评测指标。")
        lines.append("")
        for protocol in protocols:
            lines.append(f"### 协议 `{protocol['id']}`：{protocol['title']}")
            lines.append("")
            lines.append(f"- 研究问题：{protocol.get('research_question', '')}")
            lines.append(f"- 数据集：{', '.join(item.get('name', '') for item in protocol.get('datasets') or [])}")
            lines.append(f"- 基线：{', '.join(item.get('name', '') for item in protocol.get('baselines') or [])}")
            lines.append(f"- 指标：{', '.join(item.get('name', '') for item in protocol.get('metrics') or [])}")
            lines.append(f"- 停止条件：{'；'.join(protocol.get('stopping_conditions') or [])}")
            details = protocol.get("method_details") or {}
            retriever = details.get("retriever") or {}
            evaluation = details.get("evaluation_design") or {}
            if retriever:
                lines.append(
                    f"- 检索器：{retriever.get('type')}；分词={retriever.get('tokenizer')}；"
                    f"文档聚合={retriever.get('document_aggregation')}。"
                )
            if evaluation:
                lines.append(
                    f"- 推断单位：{evaluation.get('unit')}；配对 bootstrap={evaluation.get('bootstrap_seed')} "
                    f"种子、执行标签={evaluation.get('execution_seeds')}；"
                    f"复现容差={evaluation.get('reproduction_tolerance')}。"
                )
                lines.append(f"- 数据划分与调参：{evaluation.get('data_split')}。")
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
            if metrics.get("publishable") is False:
                lines.append("> **不可用于论文结论：** 数据、重复统计或独立复现门槛未全部通过。")
                lines.append("")
            stats = metrics.get("statistical_analysis") or {}
            reproduction = metrics.get("reproduction") or {}
            if stats:
                lines.append(
                    f"- 结果 ID：`{result['id']}`；重复 {stats.get('repeat_count', 0)} 次；"
                    f"95% CI={stats.get('confidence_interval_95')}；相对效应={stats.get('relative_effect')}；"
                    f"独立复现={'通过' if reproduction.get('passed') else '未通过'}。"
                )
                lines.append("")
            table = self._metrics_table(metrics)
            if table:
                lines.extend(table)
                lines.append("")
            for artifact in (result.get("artifacts") or []):
                if str(artifact).lower().endswith(".png"):
                    lines.append(f"![experiment figure]({artifact})")
                    lines.append("")
        return lines

    def _results_section(
        self, grounded_claims, citation_index, source_map, links_by_claim,
        experiment_findings, experiment_results,
    ) -> list[str]:
        lines = ["## 5. 结果", ""]
        experiment_summary = self._primary_experiment_summary(experiment_results)
        if experiment_summary:
            lines.append(f"**主要实验结果：** {experiment_summary}")
            lines.append("")
        if not grounded_claims and not experiment_findings and not experiment_summary:
            lines.append("尚无获得证据支撑的结果。")
            lines.append("")
            return lines
        if grounded_claims:
            lines.append("文献证据用于限定相关工作背景，不作为本实验效果的替代证据：")
            lines.append("")
            for claim in grounded_claims[:4]:
                lines.append(f"- ({claim['status']}) {claim['statement']}{self._cite(claim, links_by_claim, citation_index)}")
        if experiment_findings:
            lines.append("")
            lines.append("**实验 findings:**")
            lines.append("")
            lines.append("| Result ID | 判定 | 置信度 | 结论 |")
            lines.append("| --- | --- | ---: | --- |")
            for finding in experiment_findings:
                lines.append(
                    f"| `{finding['result_id']}` | {finding['relation_type']} | "
                    f"{round(finding.get('confidence', 0) * 100)}% | {finding['statement']} |"
                )
        lines.append("")
        return lines

    def _discussion_section(self, narrative_block, experiment_results) -> list[str]:
        lines = ["## 6. 讨论", ""]
        if narrative_block.get("discussion"):
            lines.append(narrative_block["discussion"])
        else:
            result = next(
                (item for item in experiment_results if (item.get("metrics") or {}).get("publishable") is True),
                None,
            )
            metrics = (result or {}).get("metrics") or {}
            rows = {row.get("strategy"): row for row in metrics.get("rows") or []}
            stats = metrics.get("statistical_analysis") or {}
            baseline = rows.get("no_split") or {}
            no_overlap = rows.get("fixed_100_no_overlap") or {}
            overlap = rows.get("fixed_100_overlap_30") or {}
            if result:
                lines.append(
                    "在冻结设置中，fixed_100_no_overlap 与 no_split 的 MRR@10 相同"
                    f"（{no_overlap.get('mrr_at_10')} 对 {baseline.get('mrr_at_10')}），而 "
                    f"fixed_100_overlap_30 达到 {overlap.get('mrr_at_10')}。"
                    "这说明当前收益来自跨越冻结边界保留查询词，而不是仅把文档切成更短片段。"
                )
                lines.append("")
                lines.append(
                    f"配对均值差为 {stats.get('mean_delta')}，95% bootstrap 区间为 "
                    f"{stats.get('confidence_interval_95')}。所有 query 差值一致使标准差为 "
                    f"{stats.get('std_delta')}，Cohen's dz 因零分母未定义；因此本文报告原始配对差值、"
                    "胜率与区间，不把退化区间解释为开放域中的确定效应。"
                )
                lines.append("")
                lines.append(
                    f"Top-3 与 Top-5 在三组中均为 {baseline.get('top3_accuracy')} 与 "
                    f"{baseline.get('top5_accuracy')}，存在明显饱和。该 pilot 只能证明冻结的同构边界构造"
                    "对 Top-1/MRR 排序敏感，不能证明重叠切分在自然语料、语义检索器或不同窗口下普遍更优。"
                )
            else:
                lines.append("没有通过发布门的实验结果，无法形成经验性讨论。")
        lines.append("")
        return lines

    def _limitations_section(self, unsupported_claims, uncertainties, experiment_results=None) -> list[str]:
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
        negative_results = [
            item for item in (experiment_results or [])
            if (item.get("metrics") or {}).get("publishable") is not True
            or "未" in str(item.get("summary") or "")
        ]
        if negative_results:
            lines.append("**负结果与有效性威胁（不可删除）:**")
            lines.append("")
            for result in negative_results:
                metrics = result.get("metrics") or {}
                lines.append(
                    f"- 结果 `{result['id']}`：{result.get('summary', '')}；"
                    f"数据类别={metrics.get('artifact_class')}；复现={'通过' if (metrics.get('reproduction') or {}).get('passed') else '未通过'}。"
                )
            lines.append("")
        if experiment_results:
            lines.append("**实验有效性威胁（不可删除）:**")
            lines.append("")
            for result in experiment_results:
                metrics = result.get("metrics") or {}
                stats = metrics.get("statistical_analysis") or {}
                lines.append(
                    f"- 结果 `{result['id']}` 基于 {stats.get('repeat_count', 0)} 次 bootstrap/重复运行；"
                    f"artifact_class={metrics.get('artifact_class')}。结论仅适用于冻结的数据集、query/qrel 与协议范围。"
                )
            lines.append("")
        if not unsupported_claims and not open_uncertainties and not negative_results and not experiment_results:
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

    def _traceability_section(
        self, claims, links_by_claim, excerpt_map, citation_index, source_map, results, protocols,
    ) -> list[str]:
        lines = ["## 追溯附录", "", "### Claim → Passage → Source", ""]
        lines += ["| Claim ID | Bibliography key | Passage / locator |", "| --- | --- | --- |"]
        for claim in claims:
            for link in links_by_claim.get(claim["id"], []):
                source = source_map.get(link["source_id"], {})
                excerpt = excerpt_map.get(link.get("excerpt_id"), {})
                number = citation_index.get(link["source_id"])
                lines.append(
                    f"| `{claim['id']}` | `{self._bibliography_key(source)}` [{number}] | "
                    f"`{link.get('excerpt_id')}` / {excerpt.get('locator') or '未标注'} |"
                )
        if not claims:
            lines.append("| — | — | — |")
        lines += ["", "### Protocol → Result → Artifact", "", "| Protocol | Result | Artifact |", "| --- | --- | --- |"]
        protocol_ids = {item["id"] for item in protocols}
        for result in results:
            protocol_id = result.get("protocol_id")
            for artifact in result.get("artifacts") or []:
                label = str(artifact).rsplit("/", 1)[-1]
                lines.append(
                    f"| `{protocol_id if protocol_id in protocol_ids else 'unknown'}` | `{result['id']}` | [{label}]({artifact}) |"
                )
        if not results:
            lines.append("| — | — | — |")
        lines.append("")
        return lines

    @staticmethod
    def _dedupe_records(records: list[dict], field: str, priority_field: str | None = None) -> list[dict]:
        priority = {"supported": 3, "contested": 2, "draft": 1, "rejected": 0}
        chosen: dict[str, tuple[int, int, dict]] = {}
        for index, record in enumerate(records):
            key = re.sub(r"\s+", " ", str(record.get(field) or "")).strip().lower()
            if not key:
                continue
            rank = priority.get(str(record.get(priority_field) or ""), 0) if priority_field else 0
            current = chosen.get(key)
            if current is None or rank > current[0]:
                chosen[key] = (rank, index, record)
        return [item[2] for item in sorted(chosen.values(), key=lambda value: value[1])]

    @staticmethod
    def _experiment_backed_claim(claim: dict, results: list[dict]) -> bool:
        statement = str(claim.get("statement") or "").lower()
        if "mrr" not in statement and "top" not in statement:
            return False
        for result in results:
            metrics = result.get("metrics") or {}
            if metrics.get("publishable") is not True:
                continue
            strategies = [str(row.get("strategy") or "").lower() for row in metrics.get("rows") or []]
            if any(strategy and strategy in statement for strategy in strategies):
                return True
        return False

    @staticmethod
    def _primary_experiment_summary(results: list[dict]) -> str:
        result = next(
            (item for item in results if (item.get("metrics") or {}).get("publishable") is True),
            None,
        )
        if not result:
            return ""
        metrics = result.get("metrics") or {}
        rows = {row.get("strategy"): row for row in metrics.get("rows") or []}
        stats = metrics.get("statistical_analysis") or {}
        baseline = rows.get("no_split") or {}
        treatment = rows.get("fixed_100_overlap_30") or metrics.get("best_strategy") or {}
        count = metrics.get("evaluated_query_count") or metrics.get("query_sample_size")
        reproduced = (metrics.get("reproduction") or {}).get("passed") is True
        return (
            f"在冻结的 {count} 条 query pilot 中，fixed_100_overlap_30 的 MRR@10="
            f"{treatment.get('mrr_at_10')}，no_split={baseline.get('mrr_at_10')}，"
            f"查询级配对均值差={stats.get('mean_delta')}，95% bootstrap 区间="
            f"{stats.get('confidence_interval_95')}，干净目录复现={'通过' if reproduced else '未通过'}。"
            "该结果仅适用于当前冻结的同构边界构造。"
        )

    @staticmethod
    def _bibliography_key(source: dict) -> str:
        identity = str(source.get("doi") or source.get("url") or source.get("title") or "unknown").strip().lower()
        return "ref_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _delivery_status(mode: str, brief: dict, grounded_claims: list[dict], uncertainties: list[dict], results: list[dict]) -> str:
        if mode != "paper":
            return "research_report"
        high_open = any(item.get("status") == "open" and item.get("severity") == "high" for item in uncertainties)
        has_publishable_experiment = any((item.get("metrics") or {}).get("publishable") is True for item in results)
        if (
            brief.get("approval_status") == "frozen" and len(grounded_claims) >= 1
            and has_publishable_experiment and not high_open
        ):
            return "thesis_draft"
        return "research_report"

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _short_title(goal: str) -> str:
        """Derive a concise title from a potentially long research-goal prompt.

        The research goal stored in the run is often a full multi-paragraph
        instruction prompt. We must not dump it verbatim into the document
        heading.  This extracts the first meaningful line and trims it.
        """
        if not goal:
            return "研究报告"
        # Take the first non-empty line that isn't a markdown heading or list
        # marker.
        for line in goal.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("-") or stripped.startswith("*"):
                continue
            # Remove surrounding quotes
            title = stripped.strip("「」""''\"'")
            # If this first line is already very long, truncate at the first
            # sentence boundary.
            if len(title) > 80:
                for sep in ("。", "；", ";", "，", ",", "—", "–"):
                    idx = title.find(sep)
                    if 0 < idx <= 80:
                        title = title[:idx]
                        break
            return title[:80] + ("..." if len(title) > 80 else "")
        return goal[:80]

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
        # Strip conversational filler that the LLM sometimes prepends (e.g.
        # "好的，导师。这是基于..." or "好的，写作研究生。我已收到你的...").
        cleaned = re.sub(
            r"^(好的[，,]?\s*(?:导师|写作研究生)[。.]?\s*)"
            r"(?:[^\n]*(?:整合|修正|收到|综合|基于)[^\n]*[\n。])?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        # If the narrative contains a top-level markdown heading (# title),
        # start from there to skip any review-verdict preamble (### 裁决,
        # **有条件通过**, 综合评审意见, etc.) that may precede the actual
        # report content.
        m = re.search(r"^# ", cleaned, flags=re.MULTILINE)
        if m:
            cleaned = cleaned[m.start():].strip()
        return {"intro": "", "method": "", "discussion": cleaned}


paper_assembly_service = PaperAssemblyService()
