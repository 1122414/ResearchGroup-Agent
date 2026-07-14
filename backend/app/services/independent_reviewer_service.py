from __future__ import annotations

import json

from ..core.config import settings
from ..core.llm_provider import create_llm_provider


class IndependentReviewerService:
    SCHEMA = {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                        "target": {"type": "string"},
                        "reason": {"type": "string"},
                        "required_change": {"type": "string"},
                    },
                    "required": ["severity", "target", "reason", "required_change"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["approved", "issues", "summary"],
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
            }

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
            "experiment": latest.get("reproducible_experiment"),
        }
        prompt = (
            "你是独立反方审稿人，未参与生成。只能依据给出的原始 passage 和 experiment artifact 摘要审查。"
            "检查错误归因、过度外推、矛盾证据、数据泄漏、基线公平性、统计与复现。"
            "缺少原始依据即不通过；只返回 JSON。\n" + json.dumps(payload, ensure_ascii=False, indent=2)[:24000]
        )
        try:
            raw = await create_llm_provider().generate(
                prompt=prompt, schema=self.SCHEMA, role="independent_reviewer",
                run_id=task.get("run_id"), task_id=task.get("id"),
            )
            value = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            if not isinstance(value, dict) or not isinstance(value.get("approved"), bool) or not isinstance(value.get("issues"), list):
                raise ValueError("invalid independent review schema")
            return {**value, "reviewer": "independent_reviewer_model"}
        except Exception as exc:  # noqa: BLE001 - reviewer failure must become a bounded fail-closed verdict
            return {
                "approved": False,
                "issues": [{
                    "severity": "critical", "target": "review_schema", "reason": str(exc),
                    "required_change": "rerun independent review or request human review",
                }],
                "summary": "independent reviewer returned invalid structure; fail closed",
                "reviewer": "independent_reviewer_schema_guard",
            }


independent_reviewer_service = IndependentReviewerService()
