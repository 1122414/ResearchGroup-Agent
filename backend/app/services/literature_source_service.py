from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import EvidenceRepository, RunRepository
from .run_artifact_service import run_artifact_service


TRACEABLE_LIBRARY = [
    {
        "id": "lewis-2020-rag",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "authors": "Patrick Lewis et al.",
        "year": 2020,
        "venue": "NeurIPS 2020",
        "url": "https://arxiv.org/abs/2005.11401",
        "methods": ["RAG", "retrieval-augmented generation", "dense retrieval"],
        "keywords": ["rag", "检索", "生成", "retrieval", "文档", "chunk"],
    },
    {
        "id": "karpukhin-2020-dpr",
        "title": "Dense Passage Retrieval for Open-Domain Question Answering",
        "authors": "Vladimir Karpukhin et al.",
        "year": 2020,
        "venue": "EMNLP 2020",
        "url": "https://arxiv.org/abs/2004.04906",
        "methods": ["DPR", "dual-encoder retrieval", "passage retrieval"],
        "keywords": ["rag", "检索", "retrieval", "passage", "召回"],
    },
    {
        "id": "reimers-2019-sbert",
        "title": "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
        "authors": "Nils Reimers and Iryna Gurevych",
        "year": 2019,
        "venue": "EMNLP-IJCNLP 2019",
        "url": "https://arxiv.org/abs/1908.10084",
        "methods": ["sentence embedding", "semantic similarity", "bi-encoder"],
        "keywords": ["embedding", "相似度", "语义", "向量", "检索"],
    },
    {
        "id": "robertson-2009-bm25",
        "title": "The Probabilistic Relevance Framework: BM25 and Beyond",
        "authors": "Stephen Robertson and Hugo Zaragoza",
        "year": 2009,
        "venue": "Foundations and Trends in Information Retrieval",
        "doi": "10.1561/1500000019",
        "url": "https://doi.org/10.1561/1500000019",
        "methods": ["BM25", "probabilistic retrieval", "lexical retrieval"],
        "keywords": ["bm25", "关键词", "检索", "ranking", "排序"],
    },
    {
        "id": "hoare-1962-quicksort",
        "title": "Quicksort",
        "authors": "C. A. R. Hoare",
        "year": 1962,
        "venue": "The Computer Journal",
        "doi": "10.1093/comjnl/5.1.10",
        "url": "https://doi.org/10.1093/comjnl/5.1.10",
        "methods": ["Hoare partition", "divide and conquer", "quicksort"],
        "keywords": ["快速排序", "快排", "quicksort", "partition", "排序"],
    },
    {
        "id": "bentley-1993-sort",
        "title": "Engineering a Sort Function",
        "authors": "Jon L. Bentley and M. Douglas McIlroy",
        "year": 1993,
        "venue": "Software: Practice and Experience",
        "doi": "10.1002/spe.4380231105",
        "url": "https://doi.org/10.1002/spe.4380231105",
        "methods": ["three-way partition", "fat partition", "practical sorting"],
        "keywords": ["快速排序", "快排", "sort", "partition", "重复元素"],
    },
    {
        "id": "musser-1997-introsort",
        "title": "Introspective Sorting and Selection Algorithms",
        "authors": "David R. Musser",
        "year": 1997,
        "venue": "Software: Practice and Experience",
        "doi": "10.1002/(SICI)1097-024X(199708)27:8<983::AID-SPE117>3.0.CO;2-%23",
        "url": "https://doi.org/10.1002/(SICI)1097-024X(199708)27:8%3C983::AID-SPE117%3E3.0.CO;2-%23",
        "methods": ["introsort", "heapsort fallback", "worst-case guard"],
        "keywords": ["快速排序", "快排", "introsort", "sort", "最坏情况"],
    },
]


class LiteratureSourceService:
    def enrich_result(self, task: dict, result: dict) -> dict:
        sources = self.select_sources(task)
        methods = self.methods_from_sources(sources)
        artifacts = self.write_artifacts(task, sources, methods)
        self.persist_evidence(task, sources, methods)
        enriched = dict(result)
        enriched["source_mode"] = "curated_traceable_bibliography"
        enriched["papers_read"] = sources
        enriched["methods_found"] = methods
        enriched["source_artifacts"] = artifacts
        return enriched

    def select_sources(self, task: dict) -> list[dict]:
        text = " ".join(
            [
                primary_goal(str(task.get("description") or "")),
                str(task.get("title") or ""),
            ]
        ).lower()
        tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", text))
        scored: list[tuple[int, dict]] = []
        for source in TRACEABLE_LIBRARY:
            score = sum(1 for keyword in source["keywords"] if keyword.lower() in text or keyword.lower() in tokens)
            scored.append((score, source))
        selected = [source for score, source in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0]
        if not selected:
            selected = TRACEABLE_LIBRARY[: settings.literature_fallback_source_count]
        return [self._source_view(source) for source in selected[: settings.literature_source_limit]]

    @staticmethod
    def methods_from_sources(sources: list[dict]) -> list[dict]:
        methods: list[dict] = []
        for source in sources:
            for method in source.get("methods", []):
                methods.append(
                    {
                        "method": method,
                        "source_id": source["id"],
                        "evidence": f"{source['authors']} ({source['year']}), {source['title']}",
                        "url": source.get("url"),
                    }
                )
        return methods

    def persist_evidence(self, task: dict, sources: list[dict], methods: list[dict]) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        now = datetime.now().isoformat()
        for source in sources:
            EvidenceRepository.upsert_source(
                {
                    "id": source["id"],
                    "run_id": run_id,
                    "task_id": task.get("id"),
                    "title": source["title"],
                    "authors": source.get("authors", ""),
                    "year": source.get("year"),
                    "venue": source.get("venue", ""),
                    "doi": source.get("doi"),
                    "url": source.get("url"),
                    "source_type": "paper",
                    "metadata": {"methods": source.get("methods", [])},
                    "created_at": now,
                }
            )
        for item in methods:
            EvidenceRepository.insert_claim(
                {
                    "id": f"claim_{uuid.uuid4().hex[:10]}",
                    "run_id": run_id,
                    "task_id": task.get("id"),
                    "source_id": item["source_id"],
                    "claim": item["evidence"],
                    "method": item["method"],
                    "relation_type": "supports",
                    "created_at": now,
                }
            )

    def write_artifacts(self, task: dict, sources: list[dict], methods: list[dict]) -> dict:
        run_id = task.get("run_id")
        run = RunRepository.get_by_id(run_id) if run_id else None
        base_dir = run_artifact_service.run_dir(run, run_id) / "workspaces" / "grad_researcher" / self._safe_name(task)
        base_dir.mkdir(parents=True, exist_ok=True)
        sources_path = base_dir / "literature_sources.json"
        notes_path = base_dir / "literature_notes.md"
        sources_path.write_text(json.dumps({"sources": sources, "methods": methods}, ensure_ascii=False, indent=2), encoding="utf-8")
        notes_path.write_text(self._notes(task, sources, methods), encoding="utf-8")
        return {
            "workspace_dir": str(base_dir),
            "sources_json": str(sources_path),
            "notes_md": str(notes_path),
        }

    @staticmethod
    def _source_view(source: dict) -> dict:
        return {
            key: source[key]
            for key in ("id", "title", "authors", "year", "venue", "doi", "url", "methods")
            if key in source
        }

    @staticmethod
    def _safe_name(task: dict) -> str:
        raw = str(task.get("title") or task.get("id") or "literature_task")
        raw = re.sub(r'[\\/:*?"<>|#`]+', "", raw).strip()
        return f"{task.get('id', 'task')}_{raw[:24]}"

    @staticmethod
    def _notes(task: dict, sources: list[dict], methods: list[dict]) -> str:
        lines = [
            f"# 文献研究记录：{task.get('title', '')}",
            "",
            f"- 生成时间：{datetime.now().isoformat()}",
            f"- 任务 ID：{task.get('id')}",
            "",
            "## 读到的可追溯来源",
            "",
        ]
        for source in sources:
            lines.append(f"- {source['authors']} ({source['year']}). {source['title']}. {source.get('venue', '')}. {source.get('url', '')}")
        lines.extend(["", "## 从来源抽取的方法", ""])
        for item in methods:
            lines.append(f"- {item['method']}：来自 {item['source_id']}，证据 {item['evidence']}")
        return "\n".join(lines) + "\n"


literature_source_service = LiteratureSourceService()
