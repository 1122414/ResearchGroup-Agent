# Phase 2：搜索架构重构 — 从单程管道到迭代循环

**优先级：** 高（P1）  
**预计工期：** 1-2周  
**前置依赖：** Phase 1 完成  
**目标：** 将文献调研从"一次搜索+一次生成"改为"多轮搜索+逐步验证+策略自适应"

---

## 1. 架构对比

### 1.1 当前架构（单程管道）

```
用户研究目标
    ↓
拼接query（无改写）
    ↓
一次性搜索（CrossRef + OpenAlex + arXiv）
    ↓
搜索结果注入prompt
    ↓
LLM一次性生成最终输出
    ↓
白名单检查 + 导师审核
    ↓
通过 / 打回（重走同样流程）
```

**缺陷**：没有中间反馈环路。搜索质量差 → 生成质量差 → 打回 → 但搜索策略不变。

### 1.2 目标架构（迭代循环体）

```
用户研究目标
    ↓
┌─────────────────────────────────────────┐
│  搜索循环 (max_iterations=5)            │
│                                          │
│  [Think] 分析当前证据是否足够             │
│      ↓                                   │
│  [Plan] 制定下一步搜索策略               │
│      ↓                                   │
│  [Search] 执行多源搜索                   │
│      ↓                                   │
│  [Filter] 相关性过滤 + 验证              │
│      ↓                                   │
│  [Accumulate] 加入知识库                 │
│      ↓                                   │
│  [Evaluate] 够了吗？→ 不够则回到Think    │
│                                          │
└─────────────────────────────────────────┘
    ↓ (够了)
严格Grounding生成（只基于已验证来源）
    ↓
导师审核
```

---

## 2. 核心组件设计

### 2.1 IterativeResearchEngine

```python
"""
backend/app/services/iterative_research_engine.py

迭代式研究引擎 - 替代当前的单次搜索+生成模式
"""

from dataclasses import dataclass, field
from typing import Optional
import asyncio

from app.core.llm_provider import create_llm_provider
from app.services.evidence_provider import evidence_provider
from app.services.web_search_tool import web_search_tool
from app.services.query_rewriter import query_rewriter
from app.services.relevance_ranker import relevance_ranker


@dataclass
class ResearchState:
    """研究过程的状态"""
    goal: str
    task_type: str
    verified_sources: list = field(default_factory=list)
    search_history: list = field(default_factory=list)  # 已执行的query
    rejected_sources: list = field(default_factory=list)  # 被过滤掉的来源
    iteration: int = 0
    sufficient: bool = False
    gaps: list = field(default_factory=list)  # 尚未覆盖的方面
    

class IterativeResearchEngine:
    """
    核心迭代研究引擎
    
    工作流程：
    1. Think: 评估当前证据状态
    2. Plan: 决定下一步搜索策略
    3. Search: 执行搜索
    4. Filter: 过滤和验证
    5. Evaluate: 判断是否充分
    """
    
    def __init__(self):
        self.llm = create_llm_provider()
        self.max_iterations = 5
        self.min_sources = 5  # 至少需要5个验证来源
        self.max_sources = 30  # 上限防止token溢出
    
    async def research(self, goal: str, task_type: str, 
                       seed_papers: list = None,
                       feedback: str = None) -> ResearchResult:
        """
        执行完整的迭代研究流程
        
        Args:
            goal: 研究目标
            task_type: 任务类型 (literature_survey, related_work, etc.)
            seed_papers: 用户提供的种子论文
            feedback: 如果是返工，导师上次的反馈
        """
        state = ResearchState(goal=goal, task_type=task_type)
        
        # 如果有种子论文，先加入
        if seed_papers:
            state.verified_sources.extend(seed_papers)
        
        # 如果有反馈，纳入初始gap分析
        if feedback:
            state.gaps = await self._extract_gaps_from_feedback(feedback)
        
        # 迭代循环
        for i in range(self.max_iterations):
            state.iteration = i + 1
            
            # Step 1: Think - 分析当前状态
            thinking = await self._think(state)
            
            if thinking["sufficient"]:
                state.sufficient = True
                break
            
            # Step 2: Plan - 制定搜索策略
            plan = await self._plan(state, thinking)
            
            # Step 3: Search - 执行搜索
            raw_results = await self._search(plan["queries"])
            state.search_history.extend(plan["queries"])
            
            # Step 4: Filter - 相关性过滤和验证
            relevant = await self._filter_and_verify(raw_results, state)
            state.verified_sources.extend(relevant)
            
            # Step 5: 更新gaps
            state.gaps = thinking.get("remaining_gaps", [])
            
            # 安全阀：达到上限
            if len(state.verified_sources) >= self.max_sources:
                break
        
        # 最终生成（严格基于verified_sources）
        return await self._synthesize(state)
    
    async def _think(self, state: ResearchState) -> dict:
        """
        Think步骤：评估当前证据是否充分
        
        输出: {
            sufficient: bool,
            coverage_assessment: str,
            remaining_gaps: [str],
            confidence: float
        }
        """
        prompt = f"""
        你是一个研究证据评估专家。请评估当前已收集的证据是否足以回答研究问题。
        
        ## 研究目标
        {state.goal}
        
        ## 已验证的来源 ({len(state.verified_sources)}篇)
        {self._format_sources_brief(state.verified_sources)}
        
        ## 已尝试过的搜索 ({len(state.search_history)}次)
        {state.search_history[-5:]}  # 最近5次
        
        ## 要求
        判断：
        1. 当前证据是否足以覆盖研究目标的核心方面？
        2. 还有哪些方面的证据缺失？
        3. 你对当前证据的信心程度（0-1）？
        4. 是否需要继续搜索？
        
        至少需要{self.min_sources}个高质量来源才算充分。
        """
        return await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            role="advisor",
            json_schema=ThinkingSchema
        )
    
    async def _plan(self, state: ResearchState, thinking: dict) -> dict:
        """
        Plan步骤：制定下一步搜索策略
        
        输出: {
            queries: [{query: str, source_preference: str, aspect: str}],
            strategy: str
        }
        """
        prompt = f"""
        你是一个学术搜索策略专家。基于以下信息制定下一步搜索计划。
        
        ## 研究目标
        {state.goal}
        
        ## 证据缺口
        {thinking.get("remaining_gaps", [])}
        
        ## 已尝试的搜索（避免重复）
        {state.search_history}
        
        ## 已有来源的关键词（避免同类）
        {self._extract_keywords_from_sources(state.verified_sources)}
        
        ## 要求
        1. 生成3-5个新的搜索query，针对证据缺口
        2. 每个query指定优先使用的数据源（crossref/openalex/arxiv/web）
        3. 尝试不同角度和关键词组合
        4. 如果之前的搜索太宽泛，这次更具体；反之亦然
        """
        return await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            role="advisor",
            json_schema=PlanSchema
        )
    
    async def _search(self, queries: list[dict]) -> list[dict]:
        """Search步骤：执行多源并行搜索"""
        all_results = []
        
        tasks = []
        for q in queries:
            source = q.get("source_preference", "all")
            if source == "crossref" or source == "all":
                tasks.append(evidence_provider._search_crossref(q["query"]))
            if source == "openalex" or source == "all":
                tasks.append(evidence_provider._search_openalex(q["query"]))
            if source == "arxiv" or source == "all":
                tasks.append(evidence_provider._search_arxiv(q["query"]))
            if source == "web" or source == "all":
                tasks.append(web_search_tool.search_with_trace(q["query"]))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_results.extend(r)
        
        return self._deduplicate(all_results)
    
    async def _filter_and_verify(self, results: list[dict], state: ResearchState) -> list[dict]:
        """
        Filter步骤：相关性过滤 + 来源验证
        """
        # 1. 相关性排序
        ranked = await relevance_ranker.rank(results, state.goal)
        
        # 2. 取top-K
        top_results = ranked[:15]
        
        # 3. 基础验证（DOI检查、URL可访问性）
        verified = []
        for paper in top_results:
            if await self._basic_verify(paper):
                verified.append(paper)
            else:
                state.rejected_sources.append(paper)
        
        return verified
    
    async def _synthesize(self, state: ResearchState) -> "ResearchResult":
        """
        最终合成：严格基于verified_sources生成研究结论
        """
        # 使用Grounded Generation（见Phase 3文档）
        # 每个陈述必须标注来源编号
        # 不允许使用来源之外的任何信息
        pass
```

### 2.2 相关性排序器 (RelevanceRanker)

```python
"""
backend/app/services/relevance_ranker.py

对搜索结果进行相关性排序，确保只有高质量、高相关的论文进入LLM的context
"""

class RelevanceRanker:
    """
    多策略相关性排序
    
    策略1: 关键词重叠度（快速、免费）
    策略2: Embedding语义相似度（中等成本）
    策略3: LLM判断（高质量、高成本，用于top-K精排）
    """
    
    async def rank(self, papers: list[dict], goal: str, 
                   strategy: str = "hybrid") -> list[dict]:
        """
        排序搜索结果
        
        strategy:
        - "keyword": 纯关键词匹配（最快）
        - "embedding": 语义相似度排序
        - "llm": LLM判断相关性（最准但最贵）
        - "hybrid": keyword粗排 → embedding精排
        """
        if strategy == "keyword":
            return self._keyword_rank(papers, goal)
        elif strategy == "embedding":
            return await self._embedding_rank(papers, goal)
        elif strategy == "llm":
            return await self._llm_rank(papers, goal)
        else:  # hybrid
            # 先用关键词粗排（取top-30）
            coarse = self._keyword_rank(papers, goal)[:30]
            # 再用embedding精排（取top-15）
            fine = await self._embedding_rank(coarse, goal)
            return fine
    
    def _keyword_rank(self, papers: list[dict], goal: str) -> list[dict]:
        """基于关键词重叠的快速排序"""
        goal_terms = set(self._extract_terms(goal))
        
        scored = []
        for paper in papers:
            paper_text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
            paper_terms = set(self._extract_terms(paper_text))
            
            # Jaccard相似度
            overlap = goal_terms & paper_terms
            score = len(overlap) / max(len(goal_terms | paper_terms), 1)
            
            scored.append({**paper, "_relevance_score": score})
        
        return sorted(scored, key=lambda x: x["_relevance_score"], reverse=True)
    
    async def _embedding_rank(self, papers: list[dict], goal: str) -> list[dict]:
        """基于embedding的语义相似度排序"""
        # 使用OpenAI embedding API 或本地模型
        # goal_embedding = await embed(goal)
        # paper_embeddings = [await embed(p['title'] + p['abstract']) for p in papers]
        # 计算余弦相似度并排序
        pass
    
    async def _llm_rank(self, papers: list[dict], goal: str) -> list[dict]:
        """LLM判断相关性（用于精排）"""
        prompt = f"""
        研究目标: {goal}
        
        请判断以下论文与研究目标的相关程度（0-10分）：
        
        {self._format_papers_for_ranking(papers)}
        
        输出JSON: [{{"paper_index": 0, "relevance": 8, "reason": "直接相关"}}, ...]
        """
        # 调用LLM，按分数排序
        pass


relevance_ranker = RelevanceRanker()
```

### 2.3 搜索数据源扩展

```python
"""
backend/app/services/extended_search_providers.py

扩展搜索源，提高学术文献覆盖面
"""

class GoogleScholarProvider:
    """
    Google Scholar 搜索
    方案A: 通过 SerpAPI 的 scholar 引擎（付费，稳定）
    方案B: 通过 scholarly 库（免费，可能限流）
    """
    
    async def search(self, query: str, num_results: int = 10) -> list[dict]:
        # SerpAPI方案
        params = {
            "engine": "google_scholar",
            "q": query,
            "num": num_results,
            "api_key": settings.serpapi_key
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            data = resp.json()
            return self._parse_scholar_results(data.get("organic_results", []))


class DBLPProvider:
    """
    DBLP - 计算机科学文献索引
    API完全免费，覆盖CS领域几乎所有论文
    """
    BASE_URL = "https://dblp.org/search/publ/api"
    
    async def search(self, query: str, num_results: int = 10) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self.BASE_URL,
                params={"q": query, "h": num_results, "format": "json"}
            )
            data = resp.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            return [self._parse_hit(h) for h in hits]
    
    def _parse_hit(self, hit: dict) -> dict:
        info = hit.get("info", {})
        return {
            "title": info.get("title", ""),
            "authors": info.get("authors", {}).get("author", []),
            "year": info.get("year", ""),
            "venue": info.get("venue", ""),
            "doi": info.get("doi", ""),
            "url": info.get("ee", ""),
            "source": "dblp"
        }


class PubMedProvider:
    """
    PubMed / NCBI - 生物医学文献
    适用于医学、生物、健康相关研究
    """
    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    
    async def search(self, query: str, num_results: int = 10) -> list[dict]:
        # 1. 搜索获取PMID列表
        # 2. 批量获取论文详细信息
        pass


class IEEEXploreProvider:
    """
    IEEE Xplore - 电气/电子/计算机工程文献
    需要API Key（免费开发者额度）
    """
    pass


class ACMDigitalLibraryProvider:
    """
    ACM Digital Library - 计算机科学文献
    通过 DOI 和 CrossRef 间接访问
    """
    pass
```

---

## 3. 搜索策略自适应

### 3.1 基于研究领域的数据源选择

```python
class SearchStrategySelector:
    """
    根据研究主题自动选择最合适的搜索数据源组合
    """
    
    DOMAIN_SOURCE_MAP = {
        "computer_science": ["dblp", "arxiv", "semantic_scholar", "google_scholar"],
        "medicine": ["pubmed", "google_scholar", "crossref"],
        "physics": ["arxiv", "crossref", "openalex"],
        "general": ["google_scholar", "crossref", "openalex", "web"],
        "engineering": ["ieee", "crossref", "google_scholar"],
    }
    
    async def select_sources(self, goal: str) -> list[str]:
        """基于研究目标自动判断领域并选择数据源"""
        # 用LLM判断研究领域
        domain = await self._classify_domain(goal)
        return self.DOMAIN_SOURCE_MAP.get(domain, self.DOMAIN_SOURCE_MAP["general"])
    
    async def _classify_domain(self, goal: str) -> str:
        """轻量级领域分类"""
        prompt = f"""
        判断以下研究目标属于哪个学科领域：
        {goal}
        
        选项: computer_science, medicine, physics, engineering, general
        只输出一个选项。
        """
        result = await self.llm.generate(...)
        return result.strip()
```

### 3.2 搜索深度自适应

```python
class AdaptiveSearchDepth:
    """
    根据搜索效果自动调整搜索深度
    
    - 如果前几次搜索结果丰富 → 减少迭代
    - 如果搜索结果稀少 → 扩大范围、增加迭代
    - 如果高度不相关 → 改变策略（更具体或更宽泛）
    """
    
    def should_go_deeper(self, state: ResearchState) -> tuple[bool, str]:
        """判断是否需要更深入的搜索"""
        
        # 来源足够且质量高
        if len(state.verified_sources) >= 10 and state.gaps == []:
            return False, "sufficient"
        
        # 搜索多次但几乎没有结果 → 需要改变策略
        if state.iteration >= 3 and len(state.verified_sources) < 3:
            return True, "broaden"  # 扩大搜索范围
        
        # 有一些结果但有明确gap
        if state.gaps:
            return True, "targeted"  # 针对gap搜索
        
        return True, "continue"
```

---

## 4. Citation Graph 扩展（滚雪球法）

```python
class CitationGraphExpander:
    """
    基于已找到的论文，通过引用关系扩展发现更多相关论文
    
    - Forward citation: 找到引用了这篇论文的后续工作
    - Backward citation: 找到这篇论文的参考文献
    - 同作者其他论文
    """
    
    async def expand(self, seed_papers: list[dict], 
                     max_expand: int = 20) -> list[dict]:
        """从种子论文出发，滚雪球式发现新论文"""
        discovered = []
        
        for paper in seed_papers[:5]:  # 只对top-5种子论文扩展
            doi = paper.get("doi")
            if not doi:
                continue
            
            # Forward citation (通过 OpenAlex/Semantic Scholar)
            citing = await self._get_citing_papers(doi)
            discovered.extend(citing[:5])
            
            # Backward citation (通过论文自身的 references)
            refs = await self._get_references(doi)
            discovered.extend(refs[:5])
        
        return self._deduplicate(discovered)
    
    async def _get_citing_papers(self, doi: str) -> list[dict]:
        """获取引用了该DOI的论文"""
        # OpenAlex API: GET /works?filter=cites:{doi}
        url = f"https://api.openalex.org/works?filter=cites:https://doi.org/{doi}&per_page=10"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            return self._parse_openalex_results(resp.json())
    
    async def _get_references(self, doi: str) -> list[dict]:
        """获取该DOI论文的参考文献"""
        # OpenAlex API: GET /works/{id}/references
        # 或 Semantic Scholar: GET /paper/{doi}/references
        pass
```

---

## 5. 集成到现有架构

### 5.1 修改 task_executor.py

```python
# 文献调研任务使用迭代研究引擎替代单次搜索
async def _execute_literature_task(self, task: dict, agent: dict) -> dict:
    engine = IterativeResearchEngine()
    
    result = await engine.research(
        goal=task["description"],
        task_type=task["task_type"],
        seed_papers=task.get("_seed_papers"),
        feedback=task.get("_revision_feedback")
    )
    
    return {
        "summary": result.summary,
        "findings": result.findings,
        "references_used": result.references,
        "search_trace": result.trace,  # 完整搜索过程记录
        "coverage_assessment": result.coverage,
    }
```

### 5.2 配置项新增

```python
# config.py 新增
class Settings(BaseSettings):
    # 迭代研究引擎
    research_max_iterations: int = 5
    research_min_sources: int = 5
    research_max_sources: int = 30
    research_relevance_strategy: str = "hybrid"  # keyword/embedding/llm/hybrid
    
    # 搜索源扩展
    dblp_enabled: bool = True
    google_scholar_enabled: bool = False  # 需要SerpAPI Key
    serpapi_key: str = ""
    pubmed_enabled: bool = False
    
    # Citation Graph
    citation_expansion_enabled: bool = True
    citation_max_expand: int = 20
    
    # 自适应搜索
    adaptive_search_enabled: bool = True
    domain_auto_detect: bool = True
```

---

## 6. 测试验证

### 6.1 单元测试场景

| 场景 | 输入 | 预期行为 |
|------|------|----------|
| 高质量目标 | "Survey of transformer architectures" | 1-2轮即找到足够来源 |
| 模糊目标 | "AI在教育中的应用" | query改写后找到英文论文 |
| 冷门主题 | 非常具体的小众topic | 多轮搜索，最终报告"证据有限" |
| 返工场景 | 带feedback的修订任务 | 搜索策略明显调整 |

### 6.2 集成测试

```python
async def test_iterative_research():
    engine = IterativeResearchEngine()
    result = await engine.research(
        goal="基于大语言模型的多Agent协作系统在学术研究自动化中的应用",
        task_type="literature_survey"
    )
    
    assert len(result.references) >= 5
    assert result.coverage > 0.7
    assert all(ref["doi"] or ref["url"] for ref in result.references)
    assert result.trace["iterations"] <= 5
```
