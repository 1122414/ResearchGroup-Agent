from __future__ import annotations

import uuid
from datetime import datetime

from ..core.logger import logger
from ..storage.repositories import (
    EvidenceRepository,
    ResearchClaimRepository,
    ResearchHypothesisRepository,
    ResearchUncertaintyRepository,
)
from .claim_evaluation_service import claim_evaluation_service


class KnowledgeGraphService:
    """Persist the structured research outputs of a task into the knowledge graph.

    Without this, task_executor only writes opaque JSON blobs, leaving the
    research loop, grounding checks, evidence section and final report with no
    structured claims/hypotheses/evidence links to operate on. This service
    turns a task result into ResearchClaim / EvidenceLink / Hypothesis /
    Uncertainty rows, then re-evaluates each claim against its evidence so the
    rest of the system has real research state to reason over.
    """

    def ingest_task_result(self, task: dict, result: dict) -> dict:
        run_id = task.get("run_id")
        if not run_id or not isinstance(result, dict):
            return {"claims": [], "hypotheses": [], "uncertainties": [], "evidence_links": 0}

        evidence = EvidenceRepository.get_by_run(run_id)
        valid_source_ids = {
            item["id"]
            for item in evidence["sources"]
            if (item.get("metadata") or {}).get("citation_eligible")
        }
        excerpt_by_id = {
            item["id"]: item
            for item in evidence["excerpts"]
            if item.get("excerpt_type") not in {"metadata_only", "summary"}
            and str(item.get("excerpt") or "").strip()
        }

        created_hypotheses = self._ingest_hypotheses(run_id, result)
        created_claims, link_count = self._ingest_claims(
            run_id, task, result, valid_source_ids, excerpt_by_id, created_hypotheses
        )
        created_uncertainties = self._ingest_uncertainties(run_id, result)

        logger.info(
            "[KnowledgeGraph] ingested | task_id=%s | claims=%d | links=%d | hypotheses=%d | uncertainties=%d",
            task.get("id"),
            len(created_claims),
            link_count,
            len(created_hypotheses),
            len(created_uncertainties),
        )
        return {
            "claims": created_claims,
            "hypotheses": created_hypotheses,
            "uncertainties": created_uncertainties,
            "evidence_links": link_count,
        }

    def _ingest_hypotheses(self, run_id: str, result: dict) -> list[dict]:
        now = datetime.now().isoformat()
        created: list[dict] = []
        for item in self._as_dicts(result.get("hypotheses")):
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            hypothesis = {
                "id": f"hypothesis_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "statement": statement[:600],
                "rationale": str(item.get("rationale") or "")[:600],
                "status": "proposed",
                "confidence": 0.0,
                "created_at": now,
                "updated_at": now,
            }
            ResearchHypothesisRepository.insert(hypothesis)
            created.append(hypothesis)
        return created

    def _ingest_claims(
        self,
        run_id: str,
        task: dict,
        result: dict,
        valid_source_ids: set[str],
        excerpt_by_id: dict[str, dict],
        created_hypotheses: list[dict],
    ) -> tuple[list[dict], int]:
        now = datetime.now().isoformat()
        default_hypothesis_id = created_hypotheses[0]["id"] if created_hypotheses else None
        created: list[dict] = []
        link_count = 0
        for item in self._as_dicts(result.get("claims")):
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            claim_id = f"claim_{uuid.uuid4().hex[:10]}"
            ResearchClaimRepository.insert(
                {
                    "id": claim_id,
                    "run_id": run_id,
                    "hypothesis_id": item.get("hypothesis_id") or default_hypothesis_id,
                    "statement": statement[:800],
                    "status": "draft",
                    "evidence_ids": [],
                    "confidence": 0.0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            relation = str(item.get("relation") or "supports").lower()
            if relation not in {"supports", "opposes", "context"}:
                relation = "supports"
            confidence = self._as_float(item.get("confidence"), 0.7)
            claimed_source_ids = set(self._source_ids(item))
            for passage_id in self._passage_ids(item):
                excerpt = excerpt_by_id.get(passage_id)
                if not excerpt:
                    continue
                source_id = excerpt["source_id"]
                if source_id not in valid_source_ids or source_id not in claimed_source_ids:
                    continue
                EvidenceRepository.insert_link(
                    {
                        "id": f"link_{uuid.uuid4().hex[:10]}",
                        "run_id": run_id,
                        "claim_id": claim_id,
                        "source_id": source_id,
                        "excerpt_id": passage_id,
                        "relation_type": relation,
                        "confidence": confidence,
                        "rationale": str(item.get("rationale") or "")[:500],
                        "created_at": now,
                    }
                )
                link_count += 1
            evaluated = claim_evaluation_service.evaluate(claim_id) or ResearchClaimRepository.get_by_id(claim_id)
            created.append(evaluated)
        return created, link_count

    def _ingest_uncertainties(self, run_id: str, result: dict) -> list[dict]:
        now = datetime.now().isoformat()
        created: list[dict] = []
        for item in self._as_dicts(result.get("uncertainties")):
            description = str(item.get("description") or item.get("statement") or "").strip()
            if not description:
                continue
            severity = str(item.get("severity") or "medium").lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            uncertainty = {
                "id": f"uncertainty_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "description": description[:600],
                "category": str(item.get("category") or "research_question"),
                "severity": severity,
                "status": "open",
                "created_at": now,
                "resolved_at": None,
            }
            ResearchUncertaintyRepository.insert(uncertainty)
            created.append(uncertainty)
        return created

    @staticmethod
    def _source_ids(item: dict) -> list[str]:
        raw = item.get("evidence_source_ids") or item.get("references_used") or item.get("source_ids") or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(value).strip() for value in raw if str(value).strip()]

    @staticmethod
    def _passage_ids(item: dict) -> list[str]:
        raw = item.get("evidence_passage_ids") or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(value).strip() for value in raw if str(value).strip()]

    @staticmethod
    def _as_dicts(value) -> list[dict]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _as_float(value, default: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, result))


knowledge_graph_service = KnowledgeGraphService()
