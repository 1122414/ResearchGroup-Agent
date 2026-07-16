import pytest

from backend.app.core.config import settings
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.evidence_provider import evidence_provider
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


@pytest.mark.asyncio
async def test_loop_query_omits_action_contract_title(monkeypatch):
    monkeypatch.setattr(settings, "research_agent_loop_enabled", False)
    queries = await query_rewriter.rewrite(
        "public education expenditure GDP cross-country",
        {"title": "[循环R2] 一段很长的补证动作描述"},
    )
    assert queries
    assert all("循环R2" not in query and "补证动作" not in query for query in queries)


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


def test_crossref_query_removes_boolean_noise_and_is_bounded():
    query = evidence_provider._scholarly_query(
        '("public education expenditure" AND GDP) OR (income groups AND cross-country comparison) '
        "with methods evidence review additional irrelevant terms for an oversized query",
        max_terms=8,
    )
    assert "AND" not in query and " OR " not in query
    assert len(query.split()) <= 8
    assert "education" in query and "expenditure" in query


def test_crossref_query_keeps_topic_and_drops_comparison_scaffolding():
    query = evidence_provider._scholarly_query(
        "government education expenditure percentage of GDP high-income vs "
        "lower-middle-income countries descriptive statistics"
    )
    assert query == "government education expenditure GDP"


def test_all_scholarly_providers_reuse_the_same_core_query():
    import inspect

    for method in (
        evidence_provider._search_crossref,
        evidence_provider._search_openalex,
        evidence_provider._search_arxiv,
        evidence_provider._search_semantic_scholar,
    ):
        assert "_scholarly_query(query)" in inspect.getsource(method)
