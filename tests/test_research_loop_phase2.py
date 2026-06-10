import pytest

from backend.app.core.config import settings
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.query_rewriter import query_rewriter


@pytest.mark.asyncio
async def test_query_rewriter_heuristic_expands_and_uses_feedback(monkeypatch):
    monkeypatch.setattr(settings, "research_agent_loop_enabled", False)
    monkeypatch.setattr(settings, "research_agent_max_queries_per_iteration", 4)
    queries = await query_rewriter.rewrite(
        "retrieval augmented generation chunking",
        {"title": "literature survey"},
        feedback="missing recall comparison",
    )
    assert queries
    assert len(queries) <= 4
    # Feedback keywords influence at least one query variant.
    assert any("recall" in q or "comparison" in q for q in queries)


def test_rank_by_relevance_orders_by_overlap():
    sources = [
        {"id": "a", "title": "Unrelated cooking recipes", "metadata": {}},
        {"id": "b", "title": "retrieval augmented generation for QA", "metadata": {"summary": "chunking and recall"}},
    ]
    ranked = evidence_pipeline_service._rank_by_relevance(sources, "retrieval augmented generation chunking recall")
    assert ranked[0]["id"] == "b"


def test_apply_feedback_appends_keywords():
    out = evidence_pipeline_service._apply_feedback("rag chunking", "需要补充 recall 对比实验")
    assert "rag chunking" in out
    assert "recall" in out


def test_curated_fallback_disabled_by_default():
    assert settings.literature_curated_fallback_enabled is False
