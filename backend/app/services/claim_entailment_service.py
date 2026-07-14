from __future__ import annotations

import json

from ..core.config import settings
from ..core.llm_provider import create_llm_provider


class ClaimEntailmentService:
    VERDICTS = {"entailed", "partially_entailed", "contradicted", "not_found"}
    SCHEMA = {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_index": {"type": "integer"},
                        "verdict": {"type": "string", "enum": sorted(VERDICTS)},
                        "passage_ids": {"type": "array", "items": {"type": "string"}},
                        "rationale": {"type": "string"},
                    },
                    "required": ["claim_index", "verdict", "passage_ids", "rationale"],
                },
            }
        },
        "required": ["verdicts"],
    }

    async def verify(self, result: dict, excerpts: list[dict], run_id: str | None, task_id: str | None) -> dict:
        claims = [item for item in result.get("claims") or [] if isinstance(item, dict)]
        if not claims:
            return {**result, "entailment_audit": {"checked": True, "kept": 0, "rejected": 0}}
        passage_map = {item["id"]: item for item in excerpts}
        if settings.mock_mode:
            verdicts = [
                {
                    "claim_index": index,
                    "verdict": "entailed" if all(pid in passage_map for pid in claim.get("evidence_passage_ids") or []) else "not_found",
                    "passage_ids": claim.get("evidence_passage_ids") or [],
                    "rationale": "mock structural entailment check",
                }
                for index, claim in enumerate(claims)
            ]
        else:
            verdicts = await self._ask_model(claims, passage_map, run_id, task_id)

        by_index = {item.get("claim_index"): item for item in verdicts if isinstance(item, dict)}
        kept: list[dict] = []
        rejected: list[dict] = []
        for index, claim in enumerate(claims):
            verdict = by_index.get(index) or {"verdict": "not_found", "passage_ids": [], "rationale": "missing verifier verdict"}
            allowed_passages = set(claim.get("evidence_passage_ids") or [])
            used_passages = set(verdict.get("passage_ids") or [])
            label = verdict.get("verdict") if used_passages.issubset(allowed_passages) else "not_found"
            audited = {**claim, "entailment_verdict": label, "entailment_rationale": str(verdict.get("rationale") or "")[:500]}
            if label in {"entailed", "partially_entailed"}:
                if label == "partially_entailed":
                    audited["confidence"] = min(float(audited.get("confidence") or 0), 0.5)
                kept.append(audited)
            else:
                rejected.append({"statement": claim.get("statement", ""), "verdict": label})
        return {
            **result,
            "claims": kept,
            "entailment_audit": {"checked": True, "kept": len(kept), "rejected": len(rejected), "rejected_claims": rejected},
        }

    async def _ask_model(self, claims: list[dict], passage_map: dict[str, dict], run_id: str | None, task_id: str | None) -> list[dict]:
        payload = []
        for index, claim in enumerate(claims):
            payload.append(
                {
                    "claim_index": index,
                    "statement": claim.get("statement", ""),
                    "passages": [
                        {"passage_id": pid, "text": passage_map.get(pid, {}).get("excerpt", "")}
                        for pid in claim.get("evidence_passage_ids") or []
                    ],
                }
            )
        base_prompt = (
            "你是独立证据核验员。逐条判断给定 passage 是否蕴含 claim，只返回 JSON。"
            "不得使用模型记忆或外部常识；证据不完整时用 partially_entailed，找不到时用 not_found。\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
        llm = create_llm_provider()
        attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 1) + 1
        prompt = base_prompt
        for attempt in range(attempts):
            raw = await llm.generate(
                prompt=prompt, schema=self.SCHEMA, role="advisor_evidence", run_id=run_id, task_id=task_id
            )
            try:
                parsed = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
                verdicts = parsed.get("verdicts") if isinstance(parsed, dict) else None
                if isinstance(verdicts, list):
                    return verdicts
            except json.JSONDecodeError:
                pass
            if attempt + 1 < attempts:
                prompt = f"{base_prompt}\n上次结构非法，只修复 JSON，不改变判定：\n{raw[:4000]}"
        return []


claim_entailment_service = ClaimEntailmentService()
