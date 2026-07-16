from pathlib import Path
import asyncio
import json
import time

from backend.app.core.config import settings
import pytest

from backend.app.services.browser_research_service import browser_research_service
from backend.app.services.browser_research_service import BrowserResearchService
from backend.app.services.browser_research_service import BrowserVerificationResult
from backend.app.services.claim_entailment_service import claim_entailment_service
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.evidence_provider import evidence_provider
from backend.app.services.research_benchmark_service import research_benchmark_service
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.services.task_graph_service import task_graph_service
from backend.app.services.task_recovery_service import task_recovery_service
from backend.app.storage.repositories import (
    EvidenceRepository,
    ExperimentResultRepository,
    ResearchBriefRepository,
    ResearchClaimRepository,
    TaskRepository,
    TaskDependencyRepository,
)
from benchmarks.run_live_e2e import DATASET, validate_dataset


def test_offline_quality_benchmark_meets_frozen_targets():
    root = Path(__file__).resolve().parents[1]
    result = research_benchmark_service.run(root / "benchmarks" / "research_quality_cases.json")
    assert result["passed"] is True
    assert result["metrics"]["false_accept_rate"] == 0.0
    assert result["metrics"]["citation_precision"] == 1.0


def test_live_acceptance_dataset_is_non_degenerate():
    validate_dataset(DATASET)
    documents = {item["id"]: item for item in DATASET["documents"]}
    assert len(documents) == 40
    assert len(DATASET["queries"]) == 20
    assert all(len(documents[item["target_doc"]]["text"]) >= 300 for item in DATASET["queries"])
    assert len({item["query"] for item in DATASET["queries"]}) == 20


def test_remote_evidence_search_uses_its_own_bounded_timeout(monkeypatch):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"message":{"items":[]}}'

    def fake_urlopen(_request, timeout):
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("backend.app.services.evidence_provider.urllib.request.urlopen", fake_urlopen)
    results, error = evidence_provider._search_crossref("bounded retrieval")
    assert results == []
    assert error is None
    assert observed["timeout"] == settings.evidence_search_timeout_seconds
    assert observed["timeout"] < settings.llm_timeout


def test_scholarly_providers_prefer_declared_open_fulltext_urls(monkeypatch):
    payloads = [
        {
            "message": {"items": [{
                "DOI": "10.1000/open", "title": ["Open article"],
                "URL": "https://doi.org/10.1000/open",
                "link": [{"URL": "https://publisher.test/open.pdf", "content-type": "application/pdf"}],
            }]},
        },
        {
            "results": [{
                "id": "https://openalex.org/W1", "display_name": "OpenAlex article",
                "authorships": [], "primary_location": {"landing_page_url": "https://doi.org/10.1000/oa"},
                "best_oa_location": {"pdf_url": "https://repository.test/oa.pdf", "source": {"display_name": "Repository"}},
            }],
        },
    ]

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    monkeypatch.setattr(
        "backend.app.services.evidence_provider.urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(payloads.pop(0)),
    )

    crossref, _ = evidence_provider._search_crossref("open article")
    openalex, _ = evidence_provider._search_openalex("open article")

    assert crossref[0]["url"] == "https://publisher.test/open.pdf"
    assert crossref[0]["metadata"]["landing_page_url"].startswith("https://doi.org/")
    assert openalex[0]["url"] == "https://repository.test/oa.pdf"
    assert openalex[0]["venue"] == "Repository"


@pytest.mark.asyncio
async def test_browser_discovery_is_only_a_zero_result_fallback(monkeypatch):
    monkeypatch.setattr(
        evidence_provider,
        "search_with_trace",
        lambda _query: {
            "results": [{"id": "s1", "title": "verified metadata"}],
            "attempts": [{"provider": "crossref", "result_count": 1}],
        },
    )

    async def unexpected_browser_call(_query):
        raise AssertionError("browser fallback must not run when structured search has candidates")

    monkeypatch.setattr(browser_research_service, "discover", unexpected_browser_call)
    sources, attempts, browser_count = await evidence_pipeline_service._gather(["query"])
    assert sources == [{"id": "s1", "title": "verified metadata"}]
    assert attempts[0]["provider"] == "crossref"
    assert browser_count == 0


@pytest.mark.asyncio
async def test_browser_fallback_is_attempted_at_most_once_per_search_round(monkeypatch):
    monkeypatch.setattr(
        evidence_provider,
        "search_with_trace",
        lambda _query: {"results": [], "attempts": []},
    )
    calls = []

    async def empty_browser_call(query):
        calls.append(query)
        return []

    monkeypatch.setattr(browser_research_service, "discover", empty_browser_call)
    await evidence_pipeline_service._gather(["first", "second", "third"])
    assert calls == ["first"]


@pytest.mark.asyncio
async def test_trusted_scholarly_metadata_skips_autonomous_browser(monkeypatch):
    async def unexpected_agent_call(*_args, **_kwargs):
        raise AssertionError("trusted scholarly metadata must not launch browser verification")

    monkeypatch.setattr(settings, "browser_research_enabled", True)
    monkeypatch.setattr(settings, "browser_research_provider_mode", "browser_use")
    monkeypatch.setattr(settings, "browser_verification_enabled", True)
    monkeypatch.setattr(BrowserResearchService, "_run_agent", unexpected_agent_call)
    sources = [{
        "id": "paper", "title": "RAG chunking", "url": "https://arxiv.org/abs/2501.00001",
        "source_type": "paper", "metadata": {"provider": "arxiv"},
    }]
    verified = await BrowserResearchService().verify_candidates("RAG chunking", sources)
    assert [source["id"] for source in verified] == ["paper"]


@pytest.mark.asyncio
async def test_hashed_attachment_snapshot_skips_redundant_browser_identity_check(monkeypatch):
    async def unexpected_agent_call(*_args, **_kwargs):
        raise AssertionError("a frozen user snapshot must not be discarded by browser availability")

    monkeypatch.setattr(settings, "browser_research_enabled", True)
    monkeypatch.setattr(settings, "browser_research_provider_mode", "browser_use")
    monkeypatch.setattr(settings, "browser_verification_enabled", True)
    monkeypatch.setattr(BrowserResearchService, "_run_agent", unexpected_agent_call)
    sources = [{
        "id": "attachment", "title": "Official data snapshot", "url": "https://example.test/api",
        "source_type": "dataset", "metadata": {
            "provider": "local_attachment", "origin": "user_attachment",
            "attachment_integrity_verified": True, "content_hash": "a" * 64,
        },
    }]

    verified = await BrowserResearchService().verify_candidates("official data", sources)

    assert [source["id"] for source in verified] == ["attachment"]


@pytest.mark.asyncio
async def test_direct_arxiv_result_skips_browser_even_when_discovered_by_web_search(monkeypatch):
    async def unexpected_agent_call(*_args, **_kwargs):
        raise AssertionError("a direct arXiv identity must not launch browser verification")

    monkeypatch.setattr(settings, "browser_research_enabled", True)
    monkeypatch.setattr(settings, "browser_research_provider_mode", "browser_use")
    monkeypatch.setattr(settings, "browser_verification_enabled", True)
    monkeypatch.setattr(BrowserResearchService, "_run_agent", unexpected_agent_call)
    sources = [{
        "id": "web-paper", "title": "RAG chunking", "url": "https://arxiv.org/html/2603.06976v1",
        "source_type": "web", "metadata": {"provider": "tavily"},
    }]
    verified = await BrowserResearchService().verify_candidates("RAG chunking", sources)
    assert [source["id"] for source in verified] == ["web-paper"]


def test_deduplication_prefers_scholarly_record_over_web_copy():
    sources = [
        {
            "id": "web-copy", "title": "Paper", "url": "https://arxiv.org/html/2501.00001v2",
            "source_type": "web", "metadata": {"provider": "tavily", "content": "snippet"},
        },
        {
            "id": "scholarly", "title": "Paper", "url": "https://arxiv.org/abs/2501.00001",
            "source_type": "paper", "metadata": {"provider": "arxiv"},
        },
    ]
    deduped = evidence_pipeline_service._deduplicate_sources(sources)
    assert [source["id"] for source in deduped] == ["scholarly"]


def test_deduplication_merges_exact_title_across_doi_and_arxiv():
    sources = [
        {
            "id": "doi", "title": "Document-Aware Passage Retrieval",
            "doi": "10.18653/v1/example", "url": "https://doi.org/10.18653/v1/example",
            "source_type": "paper", "metadata": {"provider": "crossref"},
        },
        {
            "id": "preprint", "title": "Document-Aware Passage Retrieval",
            "url": "https://arxiv.org/abs/2305.13915",
            "source_type": "paper", "metadata": {"provider": "arxiv"},
        },
    ]
    deduped = evidence_pipeline_service._deduplicate_sources(sources)
    assert [source["id"] for source in deduped] == ["doi"]


@pytest.mark.asyncio
async def test_browser_agent_receives_native_output_schema(monkeypatch):
    observed = {}

    class FakeBrowser:
        def __init__(self, **_kwargs):
            pass

        async def close(self):
            pass

    class FakeAgent:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        async def run(self, max_steps):
            observed["max_steps"] = max_steps
            return object()

    monkeypatch.setattr(
        BrowserResearchService,
        "_load_runtime",
        staticmethod(lambda: (FakeAgent, FakeBrowser, object())),
    )
    await BrowserResearchService()._run_agent("verify", BrowserVerificationResult)
    assert observed["output_model_schema"] is BrowserVerificationResult


@pytest.mark.asyncio
async def test_entailment_verifies_each_claim_in_a_bounded_call(monkeypatch):
    calls = []

    class FakeLLM:
        async def generate(self, prompt, **_kwargs):
            calls.append(prompt)
            return (
                '{"verdict":"entailed","passage_ids":["p%d"],"rationale":"direct"}'
                % (0 if '"claim_index": 0' in prompt else 1)
            )

    monkeypatch.setattr(
        "backend.app.services.claim_entailment_service.create_llm_provider",
        lambda: FakeLLM(),
    )
    verdicts = await claim_entailment_service._ask_model(
        [
            {"statement": "first", "evidence_passage_ids": ["p0"]},
            {"statement": "second", "evidence_passage_ids": ["p1"]},
        ],
        {"p0": {"excerpt": "first"}, "p1": {"excerpt": "second"}},
        "run",
        "task",
    )
    assert [item["claim_index"] for item in verdicts] == [0, 1]
    assert len(calls) == 2


def test_relevance_ranking_drops_metric_only_domain_mismatch():
    sources = [
        {"id": "rag", "title": "Document chunking for retrieval augmented generation", "metadata": {}},
        {"id": "outbreak", "title": "Outbreak reconstruction", "metadata": {"summary": "MRR and Top-1 accuracy"}},
    ]
    ranked = evidence_pipeline_service._rank_by_relevance(
        sources, "document chunking retrieval augmented generation MRR Top-1 accuracy",
    )
    assert [source["id"] for source in ranked] == ["rag"]


def test_relevance_ranking_prefers_scholarly_source_after_domain_filter():
    sources = [
        {
            "id": "blog",
            "title": "Document chunking retrieval benchmark MRR top-k accuracy",
            "metadata": {"provider": "tavily"},
        },
        {
            "id": "paper",
            "title": "Document chunking for passage retrieval",
            "metadata": {"provider": "arxiv"},
        },
    ]
    ranked = evidence_pipeline_service._rank_by_relevance(
        sources, "document chunking passage retrieval benchmark MRR top-k accuracy",
    )
    assert [source["id"] for source in ranked] == ["paper", "blog"]


def test_relevance_ranking_does_not_reward_accidental_long_fulltext_overlap():
    sources = [
        {
            "id": "physics", "title": "QCD working group report",
            "metadata": {
                "provider": "arxiv",
                "content": "government education expenditure income GDP comparison " * 20,
            },
        },
        {
            "id": "education", "title": "Government education expenditure by income group",
            "metadata": {"provider": "crossref"},
        },
    ]

    ranked = evidence_pipeline_service._rank_by_relevance(
        sources, "government education expenditure GDP high income lower middle income group comparison",
    )

    assert [source["id"] for source in ranked] == ["education"]


def test_relevance_ranking_rejects_malformed_page_sized_title():
    sources = [
        {
            "id": "issue-page", "title": "education expenditure income GDP " * 200,
            "metadata": {"provider": "crossref"},
        },
        {
            "id": "article", "title": "Government education expenditure by country income group",
            "metadata": {"provider": "crossref"},
        },
    ]

    ranked = evidence_pipeline_service._rank_by_relevance(
        sources, "government education expenditure GDP high income lower middle income group",
    )

    assert [source["id"] for source in ranked] == ["article"]


def test_browser_supplement_depends_on_relevant_grounded_titles(monkeypatch):
    monkeypatch.setattr(settings, "browser_research_enabled", True)
    monkeypatch.setattr(settings, "browser_research_provider_mode", "browser_use")
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 3)
    query = "government education expenditure GDP high income lower middle income group"
    relevant = [
        {"id": "a", "title": "Government education expenditure by income group", "metadata": {}},
        {"id": "b", "title": "Education spending GDP share across income economies", "metadata": {}},
        {"id": "c", "title": "Public education expenditure in high income countries", "metadata": {}},
    ]

    assert evidence_pipeline_service._needs_browser_supplement(relevant[:2], query) is True
    assert evidence_pipeline_service._needs_browser_supplement(relevant, query) is False


@pytest.mark.asyncio
async def test_slow_structured_search_does_not_block_control_event_loop(monkeypatch):
    observed = {"tick": False, "responsive_during_call": False}

    def slow_search(_query):
        time.sleep(0.05)
        observed["responsive_during_call"] = observed["tick"]
        return {"results": [{"id": "s1"}], "attempts": []}

    async def control_tick():
        await asyncio.sleep(0.01)
        observed["tick"] = True

    monkeypatch.setattr(evidence_provider, "search_with_trace", slow_search)
    tick = asyncio.create_task(control_tick())
    await evidence_pipeline_service._gather(["query"])
    await tick
    assert observed["responsive_during_call"] is True


def test_revision_reuses_prior_grounded_passages_but_not_metadata_only(monkeypatch):
    eligible = {"citation_eligible": True}
    monkeypatch.setattr(
        EvidenceRepository,
        "get_by_run",
        lambda _run_id: {
            "sources": [
                {"id": "prior", "metadata": eligible},
                {"id": "current", "metadata": eligible},
                {"id": "metadata_only", "metadata": eligible},
            ],
            "excerpts": [
                {"id": "p1", "source_id": "prior", "excerpt_type": "fulltext", "excerpt": "prior passage"},
                {"id": "p2", "source_id": "current", "excerpt_type": "fulltext", "excerpt": "new passage"},
                {"id": "p3", "source_id": "metadata_only", "excerpt_type": "metadata_only", "excerpt": "title"},
            ],
        },
    )
    sources, passages = evidence_pipeline_service._cumulative_grounded_evidence(
        "run_1", [{"id": "current"}],
    )
    assert [source["id"] for source in sources] == ["current", "prior"]
    assert {passage["id"] for passage in passages} == {"p1", "p2"}


def test_cumulative_evidence_counts_arxiv_url_variants_once(monkeypatch):
    eligible = {"citation_eligible": True}
    sources = [
        {"id": "abs", "url": "https://arxiv.org/abs/2603.06976v1", "metadata": eligible},
        {"id": "html", "url": "https://arxiv.org/html/2603.06976", "metadata": eligible},
        {"id": "other", "url": "https://arxiv.org/abs/2507.18910v1", "metadata": eligible},
    ]
    monkeypatch.setattr(
        EvidenceRepository,
        "get_by_run",
        lambda _run_id: {
            "sources": sources,
            "excerpts": [
                {"id": f"p-{source['id']}", "source_id": source["id"], "excerpt_type": "fulltext", "excerpt": "text"}
                for source in sources
            ],
        },
    )
    grounded, _ = evidence_pipeline_service._cumulative_grounded_evidence("run", [sources[1]])
    assert [source["id"] for source in grounded] == ["html", "other"]


def test_rejected_revision_is_not_runnable_again(monkeypatch):
    monkeypatch.setattr(TaskDependencyRepository, "get_for_task", lambda _task_id: [])
    tasks = [
        {"id": "root", "status": "blocked", "revision_of_task_id": None},
        {"id": "old", "status": "need_revision", "revision_of_task_id": "root"},
        {"id": "latest", "status": "pending", "revision_of_task_id": "root"},
    ]
    assert [task["id"] for task in task_graph_service.ready_tasks(tasks)] == ["latest"]


def test_revision_limit_does_not_reuse_older_rejected_sibling(monkeypatch):
    monkeypatch.setattr(settings, "task_max_revision_rounds", 2)
    root = {"id": "root", "run_id": "run", "created_at": "2026-01-01", "revision_of_task_id": None}
    old = {"id": "old", "run_id": "run", "created_at": "2026-01-02", "revision_of_task_id": "root", "status": "need_revision"}
    latest = {"id": "latest", "run_id": "run", "created_at": "2026-01-03", "revision_of_task_id": "root", "status": "need_revision"}
    monkeypatch.setattr(task_recovery_service, "_root_task", lambda _task: root)
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [root, old, latest])
    assert task_recovery_service.create_revision_task(latest, "still insufficient") is None


def test_ready_tasks_archives_revision_after_root_completed(monkeypatch):
    root = {"id": "root", "status": "completed"}
    stale = {"id": "stale", "status": "pending", "revision_of_task_id": "root"}
    updates = []
    monkeypatch.setattr(TaskDependencyRepository, "get_for_task", lambda _task_id: [])
    monkeypatch.setattr(TaskRepository, "update_status", lambda task_id, status, **kwargs: updates.append((task_id, status, kwargs)))

    assert task_graph_service.ready_tasks([root, stale]) == []
    assert updates == [("stale", "archived", {"blocked_reason": "根任务已终态，该返工分支已失效。"})]


def test_failed_critical_dependency_propagates_to_descendants(monkeypatch):
    tasks = {
        "child": {"id": "child", "status": "blocked"},
        "grandchild": {"id": "grandchild", "status": "pending"},
    }
    updates = []
    monkeypatch.setattr(task_graph_service, "descendants", lambda _run_id, _task_id: list(tasks))
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda task_id: tasks.get(task_id))
    monkeypatch.setattr(
        TaskRepository,
        "update_status",
        lambda task_id, status, **kwargs: updates.append((task_id, status, kwargs)),
    )
    run_execution_service._fail_dependency_descendants("run", "root", "revision exhausted")
    assert [(item[0], item[1]) for item in updates] == [
        ("child", "failed"),
        ("grandchild", "failed"),
    ]


def test_backend_restart_recovers_active_run_from_persisted_checkpoint(monkeypatch, tmp_path):
    updates = []
    artifact_root = tmp_path / "artifacts"
    artifact = artifact_root / "run_active"
    artifact.mkdir(parents=True)
    (artifact / ".run_id").write_text("run_active", encoding="utf-8")
    monkeypatch.setattr(type(settings), "artifacts_dir", property(lambda _self: artifact_root))
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.RunRepository.get_all",
        lambda: [
            {"id": "run_active", "status": "executing", "artifact_dir": str(artifact)},
            {"id": "run_done", "status": "completed", "artifact_dir": ""},
        ],
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.TaskRepository.get_all",
        lambda run_id=None: [
            {"id": "without_output", "status": "running", "outputs": []},
            {"id": "with_output", "status": "waiting_review", "outputs": ["out_1"]},
        ] if run_id == "run_active" else [],
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.TaskRepository.update_status",
        lambda task_id, status, **kwargs: updates.append((task_id, status, kwargs)),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.RunRepository.update_status",
        lambda run_id, status, **kwargs: updates.append((run_id, status, kwargs)),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda *args, **kwargs: None,
    )

    async def fake_execute(run_id):
        return run_id

    def fake_create_task(coro):
        coro.close()

    monkeypatch.setattr(run_execution_service, "execute", fake_execute)
    monkeypatch.setattr("backend.app.services.run_execution_service.asyncio.create_task", fake_create_task)
    assert run_execution_service.recover_interrupted_runs() == ["run_active"]
    assert ("without_output", "pending") in [(item[0], item[1]) for item in updates]
    assert ("with_output", "running") in [(item[0], item[1]) for item in updates]


def test_simulated_review_can_make_draft_but_not_publishable(monkeypatch):
    evidence = {
        "sources": [{"id": "s1", "metadata": {"citation_eligible": True}}],
        "excerpts": [{"id": "p1", "source_id": "s1", "excerpt_type": "fulltext", "excerpt": "evidence"}],
        "links": [{"claim_id": "c1", "source_id": "s1", "excerpt_id": "p1", "relation_type": "supports"}],
        "claims": [], "assessments": [],
    }
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: evidence)
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [{"id": "c1", "status": "supported"}])
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: {"research_type": "empirical"})
    monkeypatch.setattr(
        ExperimentResultRepository, "get_by_run",
        lambda _run_id: [{"metrics": {"publishable": True}}],
    )
    task = {
        "id": "task_1", "task_type": "literature_survey", "status": "completed",
        "review_result": {"quality_gates": {
            "passed": True,
            "layers": {"independent_review": {"passed": True, "simulation": True}},
        }},
    }
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [task])
    quality = scientific_quality_gate_service.evaluate_report(
        "run_1", "# Thesis\n\n## 参考文献\n", {"passed": True},
    )
    assert quality["passed"] is True
    assert quality["publication_ready"] is False
    assert quality["publication_blockers"] == ["mock_or_simulated_independent_review"]

    task["review_result"]["quality_gates"]["layers"]["independent_review"]["simulation"] = False
    quality = scientific_quality_gate_service.evaluate_report(
        "run_1", "# Thesis\n\n## 参考文献\n", {"passed": True},
    )
    assert quality["publication_ready"] is True
