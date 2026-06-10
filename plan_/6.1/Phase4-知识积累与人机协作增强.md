# Phase 4：知识积累与人机协作增强

**优先级：** 中（P2）  
**预计工期：** 持续迭代  
**前置依赖：** Phase 1-3 基本完成  
**目标：** 从无状态系统进化为有记忆的研究助手，支持用户深度参与研究过程

---

## 1. 当前问题：每次Run都是"失忆"重来

| 场景 | 当前表现 | 理想表现 |
|------|----------|----------|
| 用户第二次研究同一主题 | 重新搜索、重新验证 | 复用上次验证过的文献 |
| 用户提供了种子论文 | 无法有效利用 | 从种子出发做citation graph扩展 |
| 连续多个相关任务 | 各自独立搜索 | 共享已验证的知识库 |
| 搜索方向错误 | 用户只能等任务失败 | 用户可中途介入纠正 |
| 某篇假文献被反复推荐 | 每次都要重新识别 | 一次拉黑永不再出现 |

---

## 2. 跨Run文献知识库

### 2.1 架构设计

```python
"""
backend/app/services/literature_knowledge_base.py

持久化的文献知识库
- 存储历次搜索中验证通过的论文
- 支持语义搜索和关键词搜索
- 记录论文的使用历史和评价
"""

import sqlite3
from datetime import datetime
from typing import Optional


class LiteratureKnowledgeBase:
    """
    跨Run的文献知识库
    
    存储层次：
    1. verified_papers: 验证通过的论文（DOI/URL可访问）
    2. rejected_papers: 被拒绝的论文（幻觉/不可访问/不相关）
    3. search_cache: 搜索结果缓存（避免重复API调用）
    4. user_annotations: 用户对论文的标注
    """
    
    def __init__(self, db_path: str = "artifacts/literature_kb.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY,
                    doi TEXT UNIQUE,
                    title TEXT NOT NULL,
                    authors TEXT,
                    year INTEGER,
                    abstract TEXT,
                    venue TEXT,
                    url TEXT,
                    source TEXT,  -- crossref/openalex/arxiv/web/user_provided
                    verified BOOLEAN DEFAULT FALSE,
                    verification_date TEXT,
                    relevance_topics TEXT,  -- JSON array of topics
                    times_used INTEGER DEFAULT 0,
                    last_used TEXT,
                    user_rating INTEGER,  -- 1-5, NULL if not rated
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS rejected_papers (
                    id TEXT PRIMARY KEY,
                    doi TEXT,
                    title TEXT,
                    reason TEXT,  -- hallucination/unreachable/irrelevant/duplicate
                    rejected_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    query TEXT,
                    source TEXT,
                    results TEXT,  -- JSON
                    created_at TEXT,
                    expires_at TEXT  -- 缓存过期时间
                );
                
                CREATE TABLE IF NOT EXISTS user_seeds (
                    id TEXT PRIMARY KEY,
                    doi TEXT,
                    title TEXT,
                    provided_by_user BOOLEAN DEFAULT TRUE,
                    research_topic TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
                CREATE INDEX IF NOT EXISTS idx_papers_topics ON papers(relevance_topics);
                CREATE INDEX IF NOT EXISTS idx_rejected_doi ON rejected_papers(doi);
            """)
    
    async def find_relevant(self, query: str, top_k: int = 10) -> list[dict]:
        """从知识库中找到与query相关的已验证论文"""
        # 方案1: 关键词搜索（轻量）
        # 方案2: 语义搜索（需embedding）
        pass
    
    async def add_verified(self, paper: dict, topic: str):
        """添加一篇验证通过的论文"""
        pass
    
    async def add_rejected(self, paper: dict, reason: str):
        """记录一篇被拒绝的论文（下次不再推荐）"""
        pass
    
    async def is_rejected(self, doi: str = None, title: str = None) -> bool:
        """检查论文是否在黑名单中"""
        pass
    
    async def get_user_seeds(self, topic: str) -> list[dict]:
        """获取用户针对某主题提供的种子论文"""
        pass
    
    async def get_search_cache(self, query: str, source: str, 
                               max_age_hours: int = 24) -> Optional[list]:
        """获取搜索缓存（避免重复API调用）"""
        pass
    
    async def update_usage(self, paper_id: str):
        """更新论文使用计数"""
        pass


literature_kb = LiteratureKnowledgeBase()
```

### 2.2 集成到搜索流程

```python
# 在迭代研究引擎中集成知识库
class IterativeResearchEngine:
    async def research(self, goal, task_type, ...):
        # 在搜索前先查知识库
        cached_relevant = await literature_kb.find_relevant(goal, top_k=10)
        if cached_relevant:
            state.verified_sources.extend(cached_relevant)
        
        # 在搜索结果过滤时排除黑名单
        for result in raw_results:
            if await literature_kb.is_rejected(doi=result.get("doi")):
                continue  # 跳过已知假/坏论文
            ...
        
        # 搜索完成后，将新验证的论文加入知识库
        for paper in newly_verified:
            await literature_kb.add_verified(paper, topic=goal)
```

---

## 3. 用户种子文献机制

### 3.1 API接口

```python
"""
backend/app/api/literature.py

用户文献管理API
"""

from fastapi import APIRouter, UploadFile, File

router = APIRouter(prefix="/api/literature", tags=["literature"])


@router.post("/seeds")
async def add_seed_paper(data: SeedPaperInput):
    """
    用户提供种子论文
    
    支持输入方式：
    - DOI: "10.xxxx/yyyy"
    - URL: "https://arxiv.org/abs/xxxx"
    - 标题+作者: {"title": "...", "authors": "..."}
    - BibTeX: "@article{...}"
    """
    # 1. 解析输入
    paper = await parse_seed_input(data)
    # 2. 验证真实性
    verified = await doi_verifier.verify(paper.doi) if paper.doi else None
    # 3. 存入知识库
    await literature_kb.add_user_seed(paper, topic=data.research_topic)
    return {"status": "added", "paper": paper}


@router.post("/seeds/batch")
async def add_seed_papers_batch(data: BatchSeedInput):
    """批量添加种子论文（从BibTeX文件或引用列表）"""
    pass


@router.post("/seeds/from-pdf")
async def extract_seeds_from_pdf(file: UploadFile = File(...)):
    """
    从用户上传的PDF中提取参考文献列表作为种子
    使用 GROBID 或类似工具解析PDF
    """
    pass


@router.get("/knowledge-base")
async def list_knowledge_base(topic: str = None, limit: int = 50):
    """查看知识库中的文献"""
    pass


@router.delete("/knowledge-base/{paper_id}")
async def remove_from_knowledge_base(paper_id: str):
    """从知识库中移除（用户认为不相关的）"""
    pass


@router.post("/blacklist")
async def blacklist_paper(data: BlacklistInput):
    """用户手动将某论文加入黑名单（永不再推荐）"""
    pass
```

### 3.2 前端UI

```
/literature 页面功能：
├── 种子论文管理
│   ├── 添加DOI/URL/标题
│   ├── 上传BibTeX文件
│   ├── 上传PDF提取引用
│   └── 查看已添加的种子
├── 知识库浏览
│   ├── 按主题分类
│   ├── 按验证状态过滤
│   ├── 用户评分
│   └── 使用统计
├── 黑名单管理
│   ├── 查看被拒绝的论文
│   ├── 手动拉黑
│   └── 拉黑原因
└── 搜索历史
    ├── 历次搜索的query和结果
    ├── 命中率统计
    └── 搜索策略优化建议
```

---

## 4. 增强的人机协作（HITL 2.0）

### 4.1 当前HITL的局限

- 只在3个固定节点（实验执行前、报告发布前、返工时）
- 用户只能"批准/拒绝"，不能提供具体指导
- 文献调研过程完全不可见，用户看不到搜索了什么、为什么选了这些

### 4.2 细粒度介入点

```python
"""
新增的HITL介入点
"""

class ResearchHITLPoints:
    """用户可在以下节点介入"""
    
    # 搜索策略确认
    SEARCH_STRATEGY = "search_strategy"
    # 用户可以看到query改写结果，并修改/确认
    
    # 搜索结果审查
    SEARCH_RESULTS = "search_results"
    # 用户可以看到搜索到的论文列表，标记哪些相关哪些不相关
    
    # 证据片段确认
    EVIDENCE_SELECTION = "evidence_selection"
    # 用户可以审查将被注入prompt的证据片段
    
    # 生成结果预览
    GENERATION_PREVIEW = "generation_preview"
    # 用户可以在导师审核前先看到生成结果
    
    # 方向纠正
    DIRECTION_CORRECTION = "direction_correction"
    # 用户发现方向偏差时可中途纠正


class HITLInteraction:
    """HITL交互数据结构"""
    
    async def request_user_input(self, 
                                  point: str,
                                  context: dict,
                                  options: list = None,
                                  timeout_seconds: int = 300) -> dict:
        """
        在指定节点请求用户输入
        
        如果用户超时未响应，使用默认策略继续
        """
        # 通过WebSocket或轮询机制与前端通信
        interaction = {
            "id": generate_id(),
            "point": point,
            "context": context,
            "options": options,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }
        
        # 存入数据库，等待前端轮询
        await self._save_interaction(interaction)
        
        # 等待用户响应（或超时）
        response = await self._wait_for_response(interaction["id"], timeout_seconds)
        
        if response is None:
            return {"action": "auto_proceed", "reason": "timeout"}
        
        return response
```

### 4.3 实时进度可视化

```python
"""
通过SSE/WebSocket推送研究进度

用户可以实时看到：
- 当前迭代轮次 (1/5)
- 已执行的搜索query
- 每个query的结果数量
- 已验证的论文列表
- 当前证据覆盖度评估
- 存在的证据缺口
"""

class ResearchProgressStream:
    async def emit(self, event_type: str, data: dict):
        """推送进度事件到前端"""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        await self.channel.send(event)
    
    # 事件类型
    EVENTS = {
        "iteration_start": "开始第N轮搜索",
        "query_executed": "执行了搜索: {query}",
        "results_found": "找到{count}个结果",
        "paper_verified": "验证通过: {title}",
        "paper_rejected": "验证失败: {title} (原因: {reason})",
        "gap_identified": "发现证据缺口: {gap}",
        "coverage_update": "当前覆盖度: {score}",
        "thinking": "Agent正在思考: {thought}",
        "synthesis_start": "开始综合归纳",
        "complete": "研究完成",
    }
```

---

## 5. 研究方向记忆

### 5.1 用户研究画像

```python
"""
backend/app/services/user_research_profile.py

记录用户的研究偏好和历史
"""

class UserResearchProfile:
    """
    用户研究画像
    
    记录：
    - 研究领域关键词
    - 常用的学术来源偏好
    - 历次任务的主题分布
    - 被采纳 vs 被打回的论文特征
    - 质量偏好（重覆盖面 vs 重深度）
    """
    
    async def update_from_run(self, run_id: str, outcomes: dict):
        """从一次完整的run中更新用户画像"""
        # 分析哪些论文被采纳
        adopted = outcomes.get("adopted_papers", [])
        rejected = outcomes.get("rejected_papers", [])
        
        # 提取特征
        adopted_venues = [p.get("venue") for p in adopted]
        adopted_keywords = extract_keywords(adopted)
        
        # 更新画像
        self.profile["preferred_venues"].update(adopted_venues)
        self.profile["core_keywords"].update(adopted_keywords)
        self.profile["research_directions"].append(outcomes.get("topic"))
    
    async def get_search_hints(self) -> dict:
        """基于用户画像提供搜索建议"""
        return {
            "preferred_sources": self.profile.get("preferred_venues", []),
            "core_keywords": self.profile.get("core_keywords", []),
            "avoid_topics": self.profile.get("rejected_topics", []),
        }
```

---

## 6. 跨Run的研究连续性

### 6.1 研究项目（Project）概念

```python
"""
引入"研究项目"概念，允许多次Run构成一个连续的研究过程
"""

class ResearchProject:
    """
    一个研究项目包含：
    - 一个核心研究问题
    - 多次Run（每次可能聚焦不同子问题）
    - 共享的文献知识库
    - 累积的研究笔记
    - 进化的研究方向
    """
    
    id: str
    name: str
    core_question: str
    runs: list[str]  # Run IDs
    knowledge_base_id: str
    notes: list[dict]
    status: str  # active/paused/completed
    
    async def get_accumulated_knowledge(self) -> dict:
        """获取项目累积的所有知识"""
        return {
            "verified_papers": await literature_kb.find_by_project(self.id),
            "confirmed_findings": await self._get_confirmed_findings(),
            "open_questions": await self._get_open_questions(),
            "rejected_directions": await self._get_rejected_directions(),
        }
    
    async def suggest_next_run(self) -> dict:
        """基于当前进度，建议下一次Run的方向"""
        knowledge = await self.get_accumulated_knowledge()
        # 用LLM分析还有哪些方面需要研究
        pass
```

### 6.2 研究笔记系统

```python
class ResearchNotes:
    """
    允许用户在任何时候添加研究笔记
    这些笔记会被注入到后续任务的context中
    """
    
    async def add_note(self, project_id: str, content: str, 
                       note_type: str = "observation"):
        """
        note_type: observation/insight/question/correction/direction
        """
        pass
    
    async def get_relevant_notes(self, task: dict) -> list[dict]:
        """获取与当前任务相关的研究笔记"""
        pass
```

---

## 7. 前端改造需求

### 7.1 新增页面

| 页面 | 功能 |
|------|------|
| `/projects` | 研究项目管理（创建、查看、归档） |
| `/projects/{id}/knowledge` | 项目知识库（文献、笔记、发现） |
| `/projects/{id}/literature` | 文献管理（种子、黑名单、评分） |
| `/runs/{id}/live` | 运行实时监控（搜索进度、Agent思考过程） |
| `/runs/{id}/intervene` | HITL介入界面（审查搜索结果、纠正方向） |

### 7.2 实时交互功能

```
运行监控页面:
┌─────────────────────────────────────────────────────┐
│  研究进度: [████████░░] 迭代 3/5                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  当前状态: 正在搜索 "multi-agent collaboration..."    │
│                                                      │
│  已验证文献 (7/10目标):                               │
│  ✅ [E1] "A Survey of LLM-based Agents" (2024)      │
│  ✅ [E2] "AgentBench: Evaluating LLMs..." (2023)    │
│  ✅ [E3] "CAMEL: Communicative Agents..." (2023)    │
│  ❌ [R1] "Smith et al. 2025" - DOI不存在            │
│                                                      │
│  证据缺口:                                           │
│  ⚠️ 缺少: 评估方法论方面的文献                       │
│  ⚠️ 缺少: 实际部署案例                              │
│                                                      │
│  [提供种子论文] [修改搜索方向] [直接跳过] [中止]      │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## 8. 实施优先级

| 功能 | 优先级 | 复杂度 | 预期收益 |
|------|--------|--------|----------|
| 文献知识库基础版 | P1 | 中 | 避免重复搜索，积累资产 |
| 用户种子论文API | P1 | 低 | 用户可引导搜索方向 |
| 黑名单机制 | P1 | 低 | 假文献不再反复出现 |
| 搜索缓存 | P2 | 低 | 节省API调用成本 |
| 实时进度推送 | P2 | 中 | 用户知道系统在做什么 |
| HITL细粒度介入 | P2 | 高 | 用户可中途纠正 |
| 研究项目概念 | P3 | 高 | 长期研究的连续性 |
| 用户画像 | P3 | 中 | 个性化搜索策略 |
| Citation Graph | P3 | 中 | 发现更多相关论文 |
