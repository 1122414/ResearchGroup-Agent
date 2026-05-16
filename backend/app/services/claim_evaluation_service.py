from __future__ import annotations

from datetime import datetime

from ..core.config import settings
from ..storage.repositories import EvidenceRepository, ResearchClaimRepository


class ClaimEvaluationService:
    def evaluate(self, claim_id: str) -> dict | None:
        claim = ResearchClaimRepository.get_by_id(claim_id)
        if not claim:
            return None
        evidence = EvidenceRepository.get_by_run(claim["run_id"])
        links = [item for item in evidence["links"] if item["claim_id"] == claim_id]
        supporting = [item for item in links if item["relation_type"] == "supports"]
        opposing = [item for item in links if item["relation_type"] == "opposes"]

        support_score = sum(item["confidence"] * settings.evidence_link_support_weight for item in supporting)
        oppose_score = sum(item["confidence"] * settings.evidence_link_oppose_weight for item in opposing)
        total = support_score + oppose_score
        confidence = round(support_score / total, 4) if total else 0.0

        if support_score >= settings.claim_support_threshold and oppose_score >= settings.claim_conflict_threshold:
            status = "contested"
        elif support_score >= settings.claim_support_threshold:
            status = "supported"
        else:
            status = "draft"

        evidence_ids = sorted({item["source_id"] for item in links})
        ResearchClaimRepository.update(
            claim_id,
            status=status,
            confidence=confidence,
            evidence_ids=evidence_ids,
            updated_at=datetime.now().isoformat(),
        )
        return ResearchClaimRepository.get_by_id(claim_id)


claim_evaluation_service = ClaimEvaluationService()
