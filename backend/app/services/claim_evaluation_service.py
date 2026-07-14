from __future__ import annotations

from datetime import datetime

from ..core.config import settings
from ..storage.repositories import EvidenceRepository, ExperimentFindingRepository, ResearchClaimRepository


class ClaimEvaluationService:
    def evaluate(self, claim_id: str) -> dict | None:
        claim = ResearchClaimRepository.get_by_id(claim_id)
        if not claim:
            return None
        evidence = EvidenceRepository.get_by_run(claim["run_id"])
        excerpts = {item["id"]: item for item in evidence["excerpts"]}
        sources = {item["id"]: item for item in evidence["sources"]}
        links = [
            item
            for item in evidence["links"]
            if item["claim_id"] == claim_id
            and item.get("excerpt_id") in excerpts
            and excerpts[item["excerpt_id"]].get("excerpt_type") not in {"metadata_only", "summary"}
            and (sources.get(item["source_id"], {}).get("metadata") or {}).get("citation_eligible")
        ]
        supporting = [item for item in links if item["relation_type"] == "supports"]
        opposing = [item for item in links if item["relation_type"] == "opposes"]
        findings = ExperimentFindingRepository.get_by_claim(claim_id)

        support_score = sum(item["confidence"] * settings.evidence_link_support_weight for item in supporting)
        oppose_score = sum(item["confidence"] * settings.evidence_link_oppose_weight for item in opposing)
        support_score += sum(item["confidence"] for item in findings if item["relation_type"] == "supports")
        oppose_score += sum(item["confidence"] for item in findings if item["relation_type"] in {"weakens", "rejects"})
        total = support_score + oppose_score
        confidence = round(support_score / total, 4) if total else 0.0

        if support_score >= settings.claim_support_threshold and oppose_score >= settings.claim_conflict_threshold:
            status = "contested"
        elif support_score >= settings.claim_support_threshold:
            status = "supported"
        elif oppose_score >= settings.claim_conflict_threshold:
            status = "contested"
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
