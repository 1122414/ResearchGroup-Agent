from __future__ import annotations

import json
import re

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..storage.repositories import ResearchBriefRepository, ResearchClaimRepository
from .thesis_chapter_service import thesis_chapter_service


class IndependentReviewerService:
    SCHEMA = {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                        "target": {"type": "string", "maxLength": 60},
                        "reason": {"type": "string", "maxLength": 180},
                        "required_change": {"type": "string", "maxLength": 180},
                    },
                    "required": ["severity", "target", "reason", "required_change"],
                },
            },
            "summary": {"type": "string", "maxLength": 240},
        },
        "required": ["approved", "issues", "summary"],
    }
    MINIMAL_SCHEMA = {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "summary": {"type": "string", "maxLength": 240},
        },
        "required": ["approved", "summary"],
    }

    async def review_task(self, task: dict, latest: dict, evidence: dict) -> dict:
        claims = latest.get("claims") or []
        excerpts = {item["id"]: item for item in evidence.get("excerpts") or []}
        if settings.mock_mode:
            issues = [
                {
                    "severity": "critical", "target": str(index),
                    "reason": "claim is contradicted or not found in cited passage",
                    "required_change": "remove or replace the claim with passage-grounded wording",
                }
                for index, claim in enumerate(claims)
                if claim.get("entailment_verdict") in {"contradicted", "not_found"}
            ]
            return {
                "approved": not issues, "issues": issues,
                "summary": "mock independent review based on raw claim and passage state",
                "reviewer": "independent_reviewer_mock_deterministic",
                "simulation": True,
            }

        experiment = latest.get("reproducible_experiment")
        payload = {
            "task": {key: task.get(key) for key in ("id", "title", "description", "task_type")},
            "claims": [
                {
                    "index": index, "statement": claim.get("statement"),
                    "provenance": claim.get("provenance") or {},
                    "passages": [
                        {
                            "passage_id": passage_id,
                            "locator": excerpts.get(passage_id, {}).get("locator"),
                            "text": str(excerpts.get(passage_id, {}).get("excerpt") or "")[:5000],
                        }
                        for passage_id in claim.get("evidence_passage_ids") or []
                    ],
                }
                for index, claim in enumerate(claims)
            ],
            "experiment": self._compact_experiment(experiment),
        }
        deliverable = {
            key: latest.get(key)
            for key in (
                "summary", "findings", "deliverables", "risks", "risks_or_next_steps",
                "next_steps", "hypotheses", "uncertainties", "method_package",
                "material_manifest", "analysis_artifact",
                "chapter",
            )
            if latest.get(key) is not None
        }
        verified_support_ids: set[str] = set()
        if task.get("task_type") == "report_writing":
            payload = {
                "task": payload["task"], "deliverable": deliverable,
                "claims": payload["claims"], "experiment": payload["experiment"],
            }
            review_scope = self._report_writing_review_scope()
        elif task.get("task_type") == "thesis_chapter":
            brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
            support_ids = {
                support_id
                for section in (latest.get("chapter") or {}).get("sections") or []
                for paragraph in section.get("paragraphs") or []
                for support_id in paragraph.get("support_ids") or []
                if not str(support_id).startswith("brief:")
            }
            allowed_support = [
                    {
                        "id": claim["id"], "statement": claim.get("statement"),
                        "evidence_ids": claim.get("evidence_ids") or [],
                    }
                    for claim in ResearchClaimRepository.get_by_run(task.get("run_id"))
                    if claim.get("status") == "supported" and claim["id"] in support_ids
                ]
            contract_support = [
                    {"id": "brief:research_question", "value": brief.get("research_question")},
                    {"id": "brief:objective", "value": brief.get("objective")},
                    {
                        "id": "brief:scope",
                        "value": {"scope_in": brief.get("scope_in"), "scope_out": brief.get("scope_out")},
                    },
                    {"id": "brief:methodology", "value": brief.get("methodology_profile")},
                ]
            artifact_support = thesis_chapter_service.artifact_support(task.get("run_id"))
            verified_support_ids = {
                *(item["id"] for item in allowed_support),
                *(item["id"] for item in contract_support),
                *(item["id"] for item in artifact_support),
            }
            # Evidence precedes the long chapter so a context cap can never
            # turn present support into a false "missing support" verdict.
            payload = {
                "task": {
                    key: task.get(key) for key in ("id", "title", "task_type")
                },
                "support_ids_verified_by_schema": sorted(verified_support_ids),
                "allowed_support": allowed_support,
                "allowed_contract_support": contract_support,
                "allowed_artifact_support": artifact_support,
                "deliverable": deliverable,
            }
            support_issues = await self._review_thesis_support_batches(
                task, latest.get("chapter") or {}, allowed_support,
                contract_support, artifact_support, verified_support_ids,
            )
            if support_issues:
                return {
                    "approved": False,
                    "issues": support_issues,
                    "summary": "分段证据审计发现需一次性修复的越界表述",
                    "reviewer": "independent_reviewer_model_paragraph_audit_v2",
                    "simulation": False,
                }
            payload["paragraph_support_audit"] = {
                "passed": True, "reviewed_in_bounded_batches": True,
            }
            review_scope = self._thesis_chapter_review_scope()
        elif task.get("task_type") == "research_design":
            brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
            payload = {
                "task": {
                    key: task.get(key) for key in ("id", "title", "task_type")
                },
                "frozen_methodology": {
                    "family": brief.get("methodology_family")
                    or (brief.get("methodology_profile") or {}).get("family"),
                    "profile": brief.get("methodology_profile") or {},
                },
                "deliverable": deliverable,
            }
            review_scope = self._research_design_review_scope()
        elif task.get("task_type") == "data_acquisition":
            brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
            payload = {
                "task": {
                    key: task.get(key) for key in ("id", "title", "task_type")
                },
                "frozen_ethics_plan": brief.get("ethics_plan") or {},
                "deliverable": {
                    "material_manifest": latest.get("material_manifest") or {},
                },
            }
            review_scope = self._data_acquisition_review_scope()
        elif not claims and not experiment:
            payload["deliverable"] = deliverable
            review_scope = (
                "该任务不以文献 passage 或实验 artifact 为直接交付，依据 task 与 deliverable 审查。"
                "检查任务约束覆盖、内部一致性、可执行性、接口、风险控制与过度声明；"
                "不得仅因没有 passage 或 experiment artifact 判为不通过。"
            )
        elif task.get("task_type") == "literature_survey":
            payload["task"].pop("description", None)
            review_scope = self._literature_review_scope()
        elif task.get("task_type") == "result_analysis":
            # The reviewer must see the analyst's actual interpretation.  The
            # experiment artifact is immutable upstream evidence, so requiring
            # an analyst revision to rewrite it creates an impossible loop.
            payload["deliverable"] = deliverable
            brief = ResearchBriefRepository.get_by_run(task.get("run_id")) or {}
            family = (
                (latest.get("analysis_artifact") or {}).get("family")
                or brief.get("methodology_family")
                or (brief.get("methodology_profile") or {}).get("family")
                or ""
            )
            review_scope = self._result_analysis_review_scope(family)
        else:
            review_scope = (
                "只能依据给出的原始 passage 和 experiment artifact 摘要审查。"
                "检查错误归因、过度外推、矛盾证据、数据泄漏、基线公平性、统计与复现。"
                "对任务本应提供却缺少的原始依据判为不通过。"
                "若协议明确为无拟合、无调参的冻结 evaluation-only 基准，不得机械要求训练/测试划分；"
                "应改查是否在看结果后选参数、是否对同一 query 做配对比较、bootstrap 单位是否正确。"
                "受控 pilot 可以通过，但必须有样本量、效应区间和禁止开放域外推的限制；"
                "不得仅因样本小而要求擅自扩大用户冻结的数据边界。"
                "预注册文件路径、冻结哈希、方法参数、固定种子和预期产物均属于可核验预注册证据。"
            )
        payload_limit = 48000 if task.get("task_type") in {"thesis_chapter", "literature_survey"} else 24000
        serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized_payload) > payload_limit:
            serialized_payload = self._compact_payload_json(payload, payload_limit)
        base_prompt = (
            "你是独立反方审稿人，未参与生成。" + review_scope
            + "只返回紧凑 JSON：approved、issues、summary。"
            "issues 最多 6 条，每条 target 不超过 60 字、reason 和 required_change 各不超过 180 字，"
            "summary 不超过 240 字；不要复述 passage、任务或实验数据。\n"
            + serialized_payload
        )
        review = await self._ask_reviewer(base_prompt, task, verified_support_ids)
        if task.get("task_type") == "thesis_chapter":
            review["reviewer"] = "independent_reviewer_model_paragraph_audit_v3_global"
        return review

    @staticmethod
    def _compact_payload_json(payload: dict, limit: int) -> str:
        """Shrink review context without ever cutting a JSON object in half."""
        compact = json.loads(json.dumps(payload, ensure_ascii=False))
        task = compact.get("task")
        if isinstance(task, dict) and task.get("description"):
            task["description"] = str(task["description"])[:2000]
        passages = [
            passage
            for claim in compact.get("claims") or []
            if isinstance(claim, dict)
            for passage in claim.get("passages") or []
            if isinstance(passage, dict)
        ]
        if passages:
            allowance = max(600, (limit - 12000) // len(passages))
            for passage in passages:
                passage["text"] = str(passage.get("text") or "")[:allowance]
        serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) <= limit:
            return serialized
        for passage in passages:
            passage["text"] = str(passage.get("text") or "")[:600]
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    async def _review_thesis_support_batches(
        self,
        task: dict,
        chapter: dict,
        allowed_support: list[dict],
        contract_support: list[dict],
        artifact_support: list[dict],
        verified_support_ids: set[str],
    ) -> list[dict]:
        """Audit every thesis paragraph without truncating the chapter context."""
        support_map = {
            item["id"]: item
            for item in [*allowed_support, *contract_support, *artifact_support]
        }
        paragraphs = [
            {
                "id": paragraph.get("id") or f"paragraph_{index}",
                "text": paragraph.get("text"),
                "paragraph_type": paragraph.get("paragraph_type"),
                "support_ids": paragraph.get("support_ids") or [],
            }
            for index, paragraph in enumerate(
                paragraph
                for section in chapter.get("sections") or []
                if isinstance(section, dict)
                for paragraph in section.get("paragraphs") or []
                if isinstance(paragraph, dict)
            )
        ]
        issues: list[dict] = []
        for offset in range(0, len(paragraphs), 6):
            batch = paragraphs[offset:offset + 6]
            used_ids = {
                support_id for paragraph in batch
                for support_id in paragraph.get("support_ids") or []
            }
            payload = {
                "paragraphs": batch,
                "bound_support": [
                    self._audit_support_view(support_map[item], batch)
                    for item in used_ids if item in support_map
                ],
                "available_support": [
                    self._audit_support_view(item, batch)
                    for support_id, item in support_map.items() if support_id not in used_ids
                ],
                "support_ids_verified_by_schema": sorted(used_ids & verified_support_ids),
            }
            prompt = (
                "你是论文段落证据审计员，未参与生成。逐段穷尽检查本批次全部段落，只能使用各段"
                "support_ids 实际绑定的 bound_support，不得使用常识或其他段落的证据。来源归因、数值、"
                "外部事实、因果和机制必须被直接蕴含。由多个绑定事实透明合成、没有新增外部事实且明确限定"
                "范围的解释可以通过，不得要求来源逐字写出作者自己的综合判断。interpretation/limitation "
                "可给出与绑定事实和 brief 边界一致的审慎推论；仅在新增机制、因果、数值或无依据外推时拒绝。"
                "transition 可组织章节和论点而无需来源，但不得偷带新事实。method 的参数和执行事实须与工件"
                "一致，方法选择理由可由冻结合同直接推出。"
                "一次列出本批次全部 critical/major 越界，最多12条；不要报告文风或可选增强项。"
                "available_support 只能用于提出修复：若其中有直接蕴含该表述的冻结支持，优先要求补绑其 ID；"
                "否则删除不受支持的最小短语。required_change 和 target 必须写出段落 ID。"
                "只返回紧凑 JSON：approved、issues、summary。\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
            review = await self._ask_reviewer(
                prompt, task, verified_support_ids,
                max_tokens=settings.thesis_chapter_max_tokens,
                allow_minimal=False,
            )
            review = self._anchor_batch_issue_targets(review, batch)
            issues.extend(review.get("issues") or [])
            if any(item.get("target") == "review_transport" for item in issues):
                return [item for item in issues if item.get("target") == "review_transport"]
        deduplicated = []
        seen = set()
        for issue in issues:
            key = (issue.get("target"), issue.get("reason"), issue.get("required_change"))
            if key not in seen:
                seen.add(key)
                deduplicated.append(issue)
        return deduplicated[:36]

    @classmethod
    def _audit_support_view(cls, support: dict, batch: list[dict]) -> dict:
        """Compact a large frozen artifact to facts relevant to the current paragraph batch."""
        serialized = json.dumps(support, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) <= 6000:
            return support
        context = " ".join(str(item.get("text") or "") for item in batch)
        context_terms = cls._audit_terms(context)
        leaves: list[tuple[int, int, str, object]] = []

        def walk(value, path: str = "") -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    walk(child, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, child in enumerate(value[:200]):
                    walk(child, f"{path}[{index}]")
            elif value is not None:
                rendered = str(value)[:160]
                terms = cls._audit_terms(f"{path} {rendered}")
                overlap = len(context_terms & terms)
                numeric = set(re.findall(r"\b\d+(?:\.\d+)?\b", context)) & set(
                    re.findall(r"\b\d+(?:\.\d+)?\b", rendered)
                )
                essential = any(marker in path.casefold() for marker in (
                    "summary", "research_question", "protocol_id", "publishable",
                    "preregistration", "reproduction",
                ))
                leaves.append((overlap * 4 + len(numeric) * 8 + int(essential), len(leaves), path, rendered))

        walk(support)
        selected = sorted(leaves, key=lambda item: (-item[0], item[1]))[:32]
        selected.sort(key=lambda item: item[1])
        return {
            "id": support.get("id"),
            "frozen_method_contract": {
                "strategies": (((support.get("protocol") or {}).get("method_details") or {}).get("strategies")),
                "baselines": (support.get("protocol") or {}).get("baselines"),
                "retrieval_configuration": support.get("retrieval_configuration"),
                "benchmark_design": support.get("benchmark_design"),
            },
            "fact_view": [
                {"path": path[:160], "value": value}
                for _score, _index, path, value in selected
            ],
            "compacted_for_paragraph_audit": True,
        }

    @staticmethod
    def _audit_terms(text: str) -> set[str]:
        lowered = text.casefold()
        terms = {
            token[:7] for token in re.findall(r"[a-z][a-z0-9_-]{4,}", lowered)
        }
        for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
            terms.update(sequence[index:index + 2] for index in range(len(sequence) - 1))
        return terms

    @staticmethod
    def _anchor_batch_issue_targets(review: dict, batch: list[dict]) -> dict:
        """Recover paragraph IDs when a reviewer returns an unhelpful `overall` target."""
        paragraph_ids = [str(item.get("id") or "") for item in batch]
        anchored = []
        for issue in review.get("issues") or []:
            target = str(issue.get("target") or "")
            if target == "review_transport" or target in paragraph_ids:
                anchored.append(issue)
                continue
            combined = " ".join(str(issue.get(key) or "") for key in ("target", "reason", "required_change"))
            quoted = [
                value.strip() for pair in re.findall(r"['\"‘“]([^'\"’”]{8,})['\"’”]", combined)
                for value in ([pair] if isinstance(pair, str) else pair)
            ]
            words = set(re.findall(r"[A-Za-z][A-Za-z-]{4,}", combined.casefold()))
            scored = []
            for paragraph in batch:
                text = str(paragraph.get("text") or "")
                lowered = text.casefold()
                score = sum(len(value) for value in quoted if value.casefold() in lowered)
                score += 4 * len(words & set(re.findall(r"[A-Za-z][A-Za-z-]{4,}", lowered)))
                scored.append((score, str(paragraph.get("id") or "")))
            best_score, best_id = max(scored, default=(0, ""))
            fallback = ",".join(paragraph_ids)[:60]
            anchored.append({**issue, "target": best_id if best_score > 0 else fallback})
        return {**review, "issues": anchored}

    async def _ask_reviewer(
        self,
        base_prompt: str,
        task: dict,
        verified_support_ids: set[str] | None = None,
        max_tokens: int | None = None,
        allow_minimal: bool = True,
    ) -> dict:
        try:
            llm = create_llm_provider()
            attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 1) + 1
            prompt = base_prompt
            last_error = "invalid independent review schema"
            for attempt in range(attempts):
                raw = await llm.generate(
                    prompt=prompt, schema=self.SCHEMA, role="independent_reviewer",
                    run_id=task.get("run_id"), task_id=task.get("id"),
                    max_tokens=max_tokens,
                )
                try:
                    value = self._compact_review(self._parse_json(raw))
                    if verified_support_ids:
                        value = self._filter_verified_support_issues(value, verified_support_ids)
                    if not self._valid_review(value):
                        raise ValueError("invalid independent review schema")
                    return {**value, "reviewer": "independent_reviewer_model", "simulation": False}
                except (json.JSONDecodeError, ValueError) as exc:
                    last_error = str(exc)
                    if attempt + 1 < attempts:
                        prompt = (
                            f"{base_prompt}\n上次输出因过长或 JSON 非法（{last_error[:160]}）。"
                            "重新独立审查并严格压缩；不要复述上次输出。"
                        )
            if not allow_minimal:
                raise ValueError(last_error)
            raw = await llm.generate(
                prompt=(
                    f"{base_prompt}\n前两次详细审稿结构均不可解析（{last_error[:160]}）。"
                    "现在只返回 {\"approved\": true/false, \"summary\": \"不超过240字的结论\"}。"
                ),
                schema=self.MINIMAL_SCHEMA, role="independent_reviewer",
                run_id=task.get("run_id"), task_id=task.get("id"),
                max_tokens=max_tokens,
            )
            value = self._parse_json(raw)
            if not isinstance(value, dict) or not isinstance(value.get("approved"), bool):
                raise ValueError("invalid minimal independent review schema")
            summary = str(value.get("summary") or "independent review returned no summary")[:240]
            issues = [] if value["approved"] else [{
                "severity": "major", "target": "overall", "reason": summary,
                "required_change": "address the independent review summary and rerun review",
            }]
            return {
                "approved": value["approved"], "issues": issues, "summary": summary,
                "reviewer": "independent_reviewer_model_minimal", "simulation": False,
            }
        except Exception as exc:  # noqa: BLE001 - reviewer failure must become a bounded fail-closed verdict
            return {
                "approved": False,
                "issues": [{
                    "severity": "critical", "target": "review_transport", "reason": str(exc)[:180],
                    "required_change": "retry the independent review only or request human review",
                }],
                "summary": "independent reviewer returned invalid structure; fail closed",
                "reviewer": "independent_reviewer_schema_guard", "simulation": False,
            }

    @staticmethod
    def _literature_review_scope() -> str:
        return (
            "这是文献综合任务，不是复现被引论文的原始实验。只能依据给出的原始 passage 审查"
            "归因、蕴含、范围和研究缺口。来源报告的数值若被明确写成‘该研究在其设置下报告’，"
            "并同时注明 passage 中可见的方法或统计缺失与不可外推边界，即可作为受限的相关工作陈述。"
            "不得要求作者替被引论文补做 passage 未报告的置信区间、显著性检验、人工标注、模型版本、"
            "新基线或数据划分，也不得要求编造这些信息；正确处理是把缺失项列为来源局限。"
            "若交付物已经明确列出该局限，不得再以同一缺失拒绝。定性 passage 不机械要求效果量。"
            "只有无归因地把单篇结果推广为普遍事实、遗漏关键适用范围、与 passage 矛盾，"
            "或伪造来源中不存在的信息时才判重大问题。"
        )

    @staticmethod
    def _research_design_review_scope() -> str:
        return (
            "这是尚未执行的前瞻性研究设计审查，不是结果分析或实验复现。交付物的权威对象是 "
            "deliverable.method_package；不得要求 experiment、分析结果、实际样本量、显著性、"
            "外部 passage、执行后数据哈希或复现日志，也不得诱导模型编造这些未来信息。"
            "应检查方法族与冻结画像一致，研究单位/材料范围、纳排与缺失策略、主要估计量或解释程序、"
            "不确定性方法、稳健性检查、质量控制、停止规则、偏离记录和非因果边界是否具体且彼此一致。"
            "质量控制应是可执行规则，但不得机械要求任意缺失率或异常值阈值；完整案例研究可以要求"
            "披露实际缺失数，而不应预先编造缺失率。预期样本量可作为计划值但不是必需执行结果。"
            "若设计声称已经观察到结果、实际样本量或未经工件提供的 SHA-256，应要求删除或明确推迟到"
            "材料登记/分析阶段，而不是要求补造。外部方法学引用不是本任务硬门，不能因 passage 为空拒绝。"
        )

    @staticmethod
    def _data_acquisition_review_scope() -> str:
        return (
            "这是确定性材料登记审查，不是结果分析。权威对象是 deliverable.material_manifest，"
            "它由系统从运行目录中的真实文件计算，LLM 不得改写文件哈希、大小或路径。"
            "completeness 仅表示冻结研究所需输入材料、来源、授权/许可和伦理前置条件齐备，"
            "不表示数据文件内部每个统计字段都无缺失；字段缺失应由后续分析披露，不得据此否定材料齐备。"
            "每条记录同时提供绝对审计路径 path 与相对归档路径 relative_path：前者供本机核验，"
            "后者保证工件可移植，不得仅因存在绝对路径拒绝。许可名称与权威许可 URL 已构成登记证据，"
            "不得机械要求网页截图。若冻结伦理计划 required=false，且 manifest 给出豁免理由，"
            "不得要求审批编号；只有 required=true 时才检查批准状态。审查真实文件、哈希、来源、"
            "授权和伦理条件是否相互一致，不得索要未来分析结果、experiment 或外部 passage。"
        )

    @staticmethod
    def _result_analysis_review_scope(method_family: str = "") -> str:
        if method_family and method_family not in {"computational", "experimental"}:
            return (
                f"这是 {method_family} 方法的确定性结果分析，不是实验复现。claims 的合法依据是 "
                "analysis_artifact；只要 provenance 含 method_family、input_hashes、"
                "analysis_artifact、analysis_artifact_sha256，passages 为空是正确的。"
                "不得要求 protocol_id、raw_results、raw_results_sha256、逐 query 结果或实验 bootstrap，"
                "也不得让 LLM 编造这些实验字段。应核验输入哈希、冻结方法包、procedure、findings、"
                "method_checks 与 limitations 是否彼此一致，并按该方法族的质量标准审查。"
                "对于分组观察数据，应检查原始记录数、两组样本量/均值/差值、不属于目标组的排除数、"
                "缺失无效记录、声明的区间方法和稳健性结果；若已明确使用正态近似并报告限制，"
                "不得机械要求改做 bootstrap 或把描述比较改写成因果实验。"
                "确定性 analysis_artifact 是系统从已哈希材料计算的上游工件，分析任务不能凭语言模型"
                "改写其数值或哈希；required_change 只能指向当前交付物中真实可修改的解释或缺失字段。"
            )
        return (
            "这是已执行实验的结果分析，不是文献综合。claims 的合法依据是 experiment artifact；"
            "只要 provenance 含 protocol_id、raw_results、raw_results_sha256，passages 为空是正确的，"
            "不得要求文献 passage，也不得要求伪造 passage。应核验 experiment 中的逐 query 结果、"
            "paired_query_metric_deltas、bootstrap 抽样单位/种子/次数、预注册对应关系和复现状态。"
            "若查询级差值确实全部相同，零方差区间可以成立。benchmark_design 是不可由分析任务改写的"
            "上游冻结工件；只要它提供构造事实，且 deliverable 的 claims、findings、risks、uncertainties "
            "或 analysis_artifact 任一处已等价说明均匀效应可能源于同构构造、并把结论限制在冻结 pilot，"
            "就不得要求把同一句话写回 benchmark_design，也不得仅因区间退化而机械拒绝。"
            "required_change 只能指向分析任务可修改的 deliverable 字段，不能要求改写上游实验工件。"
        )

    @staticmethod
    def _report_writing_review_scope() -> str:
        return (
            "这是基于已冻结协议和已执行实验工件的论文写作任务。deliverable.findings 中带 Markdown "
            "章节标题的条目属于实际论文正文，不得因其存储在 findings 数组中误判为只有概要。"
            "应核验引言、相关工作、方法、实验设置、结果、讨论、限制、未来工作和追溯附录是否齐全，"
            "并以 experiment 中的原始结果、哈希、种子、预注册和复现状态校验数值。"
            "冻结的受控 pilot 不得在看过结果后擅自增加新基线、扩大样本或更换检索器；"
            "只要说明基线选择用于隔离切分变量且禁止外推，即不得以缺少开放域强基线判为不通过。"
            "若查询差值为零方差，Cohen's dz 未定义并报告原始配对差值是正确处理，不得要求伪造效应量。"
        )

    @staticmethod
    def _thesis_chapter_review_scope() -> str:
        return (
            "这是单章论文写作审查。实际完整正文位于 deliverable.chapter，allowed_support 是已由上游"
            "科学硬门核验并冻结的结论，allowed_contract_support 是可直接引用的研究合同字段，"
            "allowed_artifact_support 是已执行并冻结的实验工件；不得声称章节正文"
            "或原始依据未提供，也不得把 brief:* ID 判为无效。逐段检查其 support_ids 所支撑的表述是否超出"
            "这些允许项。实验方法和数值若与 allowed_artifact_support 精确一致即可引用；若出现工件中没有的"
            "算法、参数或数值必须拒绝。还应检查结构、论证连贯性、方法解释、结果边界和局限是否与章节职责相称。"
            "paragraph_support_audit 已由同一独立审稿角色分段穷尽完成且通过时，本轮只审结构、章节职责、"
            "内部一致性和研究边界，不得重复抽样审查证据绑定并制造下一轮零散问题。"
            "不得仅因章节组织偏好拒绝有证据且有边界的内容：引言可以简要预览关键数值、方法和局限，"
            "方法章可以解释设计理由、复现控制、诊断和方法局限；只有事实矛盾、必要结构缺失、明显破坏"
            "论证的实质重复或大段内容完全与章节目标无关时才能列为 major。可选的搬章、合并和文风优化"
            "应写入 summary 而不是 issues，不能因此判为不通过。"
            "字数、support ID 存在性和来源资格已经由确定性门校验，不得要求正文自报 word_count 或重复"
            "粘贴原始文献。引言、文献综述和结论不必重复逐 query 数据；方法与结果章节才应提供与职责相称的"
            "统计和复现细节。冻结受控 pilot 只要明确禁止开放域外推，就不得要求擅自扩大样本或增加新基线。"
        )

    @staticmethod
    def _compact_experiment(experiment: dict | None) -> dict | None:
        """Keep audit-critical experiment facts without flooding the reviewer context."""
        if not experiment:
            return None
        protocol = experiment.get("protocol") or {}
        metrics = experiment.get("metrics") or {}
        per_query = metrics.get("per_query_results") or {}
        per_query_summary = {
            strategy: {
                "count": len(rows) if isinstance(rows, list) else 0,
                "first_two": rows[:2] if isinstance(rows, list) else [],
            }
            for strategy, rows in per_query.items()
        }
        result = experiment.get("experiment_result") or {}
        run = experiment.get("experiment_run") or {}
        return {
            "summary": experiment.get("summary"),
            "generated_code": experiment.get("generated_code"),
            "experiment_ran": experiment.get("experiment_ran"),
            "artifact_class": experiment.get("artifact_class"),
            "publishable": experiment.get("publishable"),
            "protocol": {
                key: protocol.get(key)
                for key in (
                    "id", "research_question", "datasets", "metrics", "baselines",
                    "method_details", "stopping_conditions", "expected_risks",
                )
            },
            "experiment_run": {
                "id": run.get("id"), "status": run.get("status"),
                "dataset_snapshot": run.get("dataset_snapshot"),
            },
            "result_summary": result.get("summary"),
            "metrics": {
                key: metrics.get(key)
                for key in (
                    "benchmark_design", "query_sample_size", "evaluated_query_count",
                    "execution_seed_role", "retrieval_configuration", "rows", "best_strategy",
                    "paired_query_metric_deltas", "statistical_analysis", "randomness_audit",
                    "artifact_hashes", "artifact_integrity_manifest", "preregistration_trace",
                    "trusted_evaluator",
                )
            },
            "per_query_results_summary": per_query_summary,
            "execution": {
                key: (experiment.get("execution") or {}).get(key)
                for key in ("exit_code", "sandboxed", "sandbox_backend")
            },
            "reproduction": experiment.get("reproduction"),
            "artifacts": experiment.get("artifacts"),
            "artifact_hashes": experiment.get("artifact_hashes"),
            "preregistration_trace": experiment.get("preregistration_trace"),
        }

    @staticmethod
    def _compact_review(value):
        """Normalize harmless field drift without altering the model's decision."""
        if not isinstance(value, dict):
            return value
        approved = value.get("approved")
        raw_issues = value.get("issues") or []
        if isinstance(raw_issues, dict):
            raw_issues = [raw_issues]
        if not isinstance(raw_issues, list):
            raw_issues = []
        compacted = []
        for issue in raw_issues[:12]:
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity") or "major").lower()
            if severity not in {"critical", "major", "minor"}:
                severity = "major"
            reason = str(issue.get("reason") or issue.get("description") or issue.get("issue") or "")
            compacted.append({
                "severity": severity,
                "target": str(issue.get("target") or issue.get("area") or "overall")[:60],
                "reason": reason[:180],
                "required_change": str(
                    issue.get("required_change") or issue.get("recommendation")
                    or issue.get("action") or reason or "request human review"
                )[:180],
            })
        summary = str(
            value.get("summary") or value.get("overall_assessment")
            or value.get("conclusion") or ""
        )[:240]
        if approved is False and not compacted:
            compacted.append({
                "severity": "major", "target": "overall",
                "reason": summary or "independent reviewer rejected the output",
                "required_change": summary or "request the reviewer to specify required changes",
            })
        return {"approved": approved, "issues": compacted, "summary": summary}

    @staticmethod
    def _filter_verified_support_issues(value: dict, verified_ids: set[str]) -> dict:
        """Drop only claims that a schema-verified support ID does not exist."""
        invalid_markers = (
            "无效", "未在 allowed", "不在 allowed", "未出现在 allowed",
            "unknown support", "invalid support", "not in allowed",
        )
        kept = []
        for issue in value.get("issues") or []:
            text = " ".join(str(issue.get(key) or "") for key in ("target", "reason", "required_change"))
            mentioned = set(re.findall(
                r"(?:claim_[A-Za-z0-9]+|experiment:[A-Za-z0-9_]+|brief:[A-Za-z0-9_]+)", text,
            ))
            if mentioned and mentioned.issubset(verified_ids) and any(
                marker in text.lower() for marker in invalid_markers
            ):
                continue
            kept.append(issue)
        return {**value, "approved": not kept, "issues": kept}

    @staticmethod
    def _parse_json(raw: str):
        text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)

    @staticmethod
    def _valid_review(value) -> bool:
        if not isinstance(value, dict) or not isinstance(value.get("approved"), bool):
            return False
        if not isinstance(value.get("issues"), list) or not isinstance(value.get("summary"), str):
            return False
        required = {"severity", "target", "reason", "required_change"}
        return all(
            isinstance(issue, dict)
            and required.issubset(issue)
            and issue.get("severity") in {"critical", "major", "minor"}
            for issue in value["issues"]
        )


independent_reviewer_service = IndependentReviewerService()
