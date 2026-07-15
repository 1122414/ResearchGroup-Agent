from __future__ import annotations

import json

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
                "maxItems": 6,
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
                    "passages": [
                        {
                            "passage_id": passage_id,
                            "locator": excerpts.get(passage_id, {}).get("locator"),
                            "text": excerpts.get(passage_id, {}).get("excerpt"),
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
            payload = {
                "task": payload["task"], "deliverable": deliverable,
                "allowed_support": [
                    {
                        "id": claim["id"], "statement": claim.get("statement"),
                        "evidence_ids": claim.get("evidence_ids") or [],
                    }
                    for claim in ResearchClaimRepository.get_by_run(task.get("run_id"))
                    if claim.get("status") == "supported" and claim["id"] in support_ids
                ],
                "allowed_contract_support": [
                    {"id": "brief:research_question", "value": brief.get("research_question")},
                    {"id": "brief:objective", "value": brief.get("objective")},
                    {
                        "id": "brief:scope",
                        "value": {"scope_in": brief.get("scope_in"), "scope_out": brief.get("scope_out")},
                    },
                    {"id": "brief:methodology", "value": brief.get("methodology_profile")},
                ],
                "allowed_artifact_support": thesis_chapter_service.artifact_support(task.get("run_id")),
            }
            review_scope = self._thesis_chapter_review_scope()
        elif not claims and not experiment:
            payload["deliverable"] = deliverable
            review_scope = (
                "该任务不以文献 passage 或实验 artifact 为直接交付，依据 task 与 deliverable 审查。"
                "检查任务约束覆盖、内部一致性、可执行性、接口、风险控制与过度声明；"
                "不得仅因没有 passage 或 experiment artifact 判为不通过。"
            )
        elif task.get("task_type") == "literature_survey":
            review_scope = self._literature_review_scope()
        elif task.get("task_type") == "result_analysis":
            # The reviewer must see the analyst's actual interpretation.  The
            # experiment artifact is immutable upstream evidence, so requiring
            # an analyst revision to rewrite it creates an impossible loop.
            payload["deliverable"] = deliverable
            review_scope = self._result_analysis_review_scope()
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
        base_prompt = (
            "你是独立反方审稿人，未参与生成。" + review_scope
            + "只返回紧凑 JSON：approved、issues、summary。"
            "issues 最多 6 条，每条 target 不超过 60 字、reason 和 required_change 各不超过 180 字，"
            "summary 不超过 240 字；不要复述 passage、任务或实验数据。\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:24000]
        )
        try:
            llm = create_llm_provider()
            attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 1) + 1
            prompt = base_prompt
            last_error = "invalid independent review schema"
            for attempt in range(attempts):
                raw = await llm.generate(
                    prompt=prompt, schema=self.SCHEMA, role="independent_reviewer",
                    run_id=task.get("run_id"), task_id=task.get("id"),
                )
                try:
                    value = self._parse_json(raw)
                    value = self._compact_review(value)
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
            # Last transport-only fallback: preserve independent judgment while
            # removing the verbose issue schema. This retries only the review,
            # never the research or experiment task.
            raw = await llm.generate(
                prompt=(
                    f"{base_prompt}\n前两次详细审稿结构均不可解析（{last_error[:160]}）。"
                    "现在只返回 {\"approved\": true/false, \"summary\": \"不超过240字的结论\"}。"
                ),
                schema=self.MINIMAL_SCHEMA,
                role="independent_reviewer",
                run_id=task.get("run_id"),
                task_id=task.get("id"),
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
                "reviewer": "independent_reviewer_schema_guard",
                "simulation": False,
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
    def _result_analysis_review_scope() -> str:
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
        for issue in raw_issues[:6]:
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
