from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from ..core.logger import logger
from ..storage.repositories import (
    EvidenceRepository,
    ReviewDecisionRepository,
    ResearchClaimRepository,
    ResearchHypothesisRepository,
    ResearchUncertaintyRepository,
    TaskRepository,
)
from .claim_evaluation_service import claim_evaluation_service


class KnowledgeGraphService:
    """Persist the structured research outputs of a task into the knowledge graph.

    Without this, task_executor only writes opaque JSON blobs, leaving the
    research loop, grounding checks, evidence section and final report with no
    structured claims/hypotheses/evidence links to operate on. This service
    turns a task result into staged ResearchClaim / EvidenceLink / Hypothesis /
    Uncertainty rows. ReviewService promotes them only after all quality gates pass.
    """

    def ingest_task_result(self, task: dict, result: dict) -> dict:
        run_id = task.get("run_id")
        if not run_id or not isinstance(result, dict):
            return {"claims": [], "hypotheses": [], "uncertainties": [], "evidence_links": 0}
        if task.get("task_type") in {"thesis_chapter", "report_writing"}:
            # Writing consumes the frozen graph. Letting prose flow back into
            # research state can downgrade verified claims and reopen the loop.
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

        created_hypotheses = self._ingest_hypotheses(run_id, task, result)
        created_claims, link_count = self._ingest_claims(
            run_id, task, result, valid_source_ids, excerpt_by_id,
            created_hypotheses, evidence["links"],
        )
        created_uncertainties = self._ingest_uncertainties(run_id, task, result)

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

    def _ingest_hypotheses(self, run_id: str, task: dict, result: dict) -> list[dict]:
        now = datetime.now().isoformat()
        created: list[dict] = []
        for item in self._as_dicts(result.get("hypotheses")):
            statement = str(item.get("statement") or "").strip()
            key = self._normalize(statement)
            if not key:
                continue
            hypothesis_id = self._task_object_id("hypothesis", task.get("id"), key)
            existing = ResearchHypothesisRepository.get_by_id(hypothesis_id)
            if existing:
                ResearchHypothesisRepository.update(
                    hypothesis_id, status="staged", confidence=0.0, updated_at=now,
                )
                created.append(ResearchHypothesisRepository.get_by_id(hypothesis_id))
                continue
            hypothesis = {
                "id": hypothesis_id,
                "run_id": run_id,
                "statement": statement[:600],
                "rationale": str(item.get("rationale") or "")[:600],
                "status": "staged",
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
        existing_links: list[dict],
    ) -> tuple[list[dict], int]:
        now = datetime.now().isoformat()
        default_hypothesis_id = created_hypotheses[0]["id"] if created_hypotheses else None
        created: list[dict] = []
        link_count = 0
        link_keys = {
            (link.get("claim_id"), link.get("source_id"), link.get("excerpt_id"), link.get("relation_type"))
            for link in existing_links
        }
        for item in self._as_dicts(result.get("claims")):
            # Keep partially entailed statements in the task audit, but do not
            # promote them into the reportable knowledge graph as research claims.
            if item.get("entailment_verdict") == "partially_entailed":
                continue
            statement = str(item.get("statement") or "").strip()
            key = self._normalize(statement)
            if not key:
                continue
            claim_id = self._task_object_id("claim", task.get("id"), key)
            existing_claim = ResearchClaimRepository.get_by_id(claim_id)
            if existing_claim:
                if existing_claim.get("status") != "draft":
                    ResearchClaimRepository.update(
                        claim_id, status="draft", confidence=0.0,
                        evidence_ids=[], updated_at=now,
                    )
            else:
                claim = {
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
                ResearchClaimRepository.insert(claim)
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
                link_key = (claim_id, source_id, passage_id, relation)
                if link_key in link_keys:
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
                        "rationale": str(item.get("entailment_rationale") or item.get("rationale") or "")[:500],
                        "created_at": now,
                    }
                )
                link_count += 1
                link_keys.add(link_key)
            created.append(ResearchClaimRepository.get_by_id(claim_id))
        return created, link_count

    def _ingest_uncertainties(self, run_id: str, task: dict, result: dict) -> list[dict]:
        now = datetime.now().isoformat()
        created: list[dict] = []
        for item in self._as_dicts(result.get("uncertainties")):
            description = str(item.get("description") or item.get("statement") or "").strip()
            key = self._normalize(description)
            if not key:
                continue
            uncertainty_id = self._task_object_id("uncertainty", task.get("id"), key)
            existing = next(
                (row for row in ResearchUncertaintyRepository.get_by_run(run_id) if row["id"] == uncertainty_id),
                None,
            )
            if existing:
                ResearchUncertaintyRepository.update_status(uncertainty_id, "staged")
                created.append(next(
                    row for row in ResearchUncertaintyRepository.get_by_run(run_id)
                    if row["id"] == uncertainty_id
                ))
                continue
            severity = str(item.get("severity") or "medium").lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            uncertainty = {
                "id": uncertainty_id,
                "run_id": run_id,
                "description": description[:600],
                "category": str(item.get("category") or "research_question"),
                "severity": severity,
                "status": "staged",
                "created_at": now,
                "resolved_at": None,
            }
            ResearchUncertaintyRepository.insert(uncertainty)
            created.append(uncertainty)
        return created

    def synchronize_review_status(self, run_id: str) -> None:
        """Demote legacy graph objects whose producing task has not passed review."""
        staged = {"claims": set(), "hypotheses": set(), "uncertainties": set()}
        approved = {key: set() for key in staged}
        latest_reviews = {
            item["task_id"]: item for item in ReviewDecisionRepository.get_by_run(run_id)
        }
        for task in TaskRepository.get_all(run_id=run_id):
            reviewed = latest_reviews.get(task["id"]) or {}
            target = (
                approved
                if task.get("status") == "completed" and reviewed.get("approved") is True
                else staged
            )
            for output in task.get("outputs") or []:
                graph = output.get("knowledge_graph") or {}
                target["claims"].update(graph.get("claim_ids") or [])
                target["hypotheses"].update(graph.get("hypothesis_ids") or [])
                target["uncertainties"].update(graph.get("uncertainty_ids") or [])
                staged["claims"].update(graph.get("claim_ids") or [])
                staged["hypotheses"].update(graph.get("hypothesis_ids") or [])
                staged["uncertainties"].update(graph.get("uncertainty_ids") or [])
        now = datetime.now().isoformat()
        for claim_id in staged["claims"] - approved["claims"]:
            ResearchClaimRepository.update(
                claim_id, status="draft", confidence=0.0, evidence_ids=[], updated_at=now,
            )
        for hypothesis_id in staged["hypotheses"] - approved["hypotheses"]:
            ResearchHypothesisRepository.update(
                hypothesis_id, status="staged", confidence=0.0, updated_at=now,
            )
        for uncertainty_id in staged["uncertainties"] - approved["uncertainties"]:
            ResearchUncertaintyRepository.update_status(uncertainty_id, "staged")
        for claim_id in approved["claims"]:
            claim_evaluation_service.evaluate(claim_id)
        for hypothesis_id in approved["hypotheses"]:
            ResearchHypothesisRepository.update(
                hypothesis_id, status="proposed", updated_at=now,
            )
        for uncertainty_id in approved["uncertainties"]:
            ResearchUncertaintyRepository.update_status(uncertainty_id, "open")

    @staticmethod
    def _task_object_id(prefix: str, task_id: str | None, normalized_text: str) -> str:
        digest = hashlib.sha256(f"{task_id or 'unscoped'}|{normalized_text}".encode()).hexdigest()[:10]
        return f"{prefix}_{digest}"

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

    @staticmethod
    def _normalize(value) -> str:
        return " ".join(str(value or "").split()).strip().lower()


knowledge_graph_service = KnowledgeGraphService()
