# Phase 1：致命缺陷修复方案

**优先级：** 最高（P0）  
**预计工期：** 3-5天  
**目标：** 让调研Agent能产出真实、相关的文献，打破"搜不到→编造→打回→循环"的死结

---

## 1. 智能Query改写服务

### 1.1 问题回顾

当前 `evidence_pipeline_service._query_for_task()` 直接拼接任务的 `description + title` 作为搜索query。例如：

- 用户输入：「研究基于大语言模型的多Agent协作系统在学术研究自动化中的应用」
- 当前query：整段中文原文
- CrossRef搜索效果：几乎为0（CrossRef对中文支持极差）

### 1.2 解决方案

新增 `backend/app/services/query_rewriter.py`：

```python
"""
智能搜索Query改写服务

职责：
1. 将用户的自然语言研究目标拆解为多个精准的学术搜索query
2. 自动翻译为英文（学术API主要支持英文）
3. 生成不同角度的query变体
4. 支持基于反馈的query迭代优化
"""

from app.core.llm_provider import create_llm_provider

REWRITE_PROMPT = """
你是一名学术文献检索专家。请将以下研究目标转化为精准的学术搜索query列表。

## 规则
1. 输出4-8个英文搜索query
2. 每个query使用3-6个学术关键词
3. 覆盖不同角度：核心方法、应用场景、评估方法、相关技术
4. 使用学术规范术语（如 multi-agent system 而非 multiple AI agents）
5. 包含同义词变体（如 LLM / large language model / foundation model）
6. 避免过于宽泛的query（如单独的 "AI" 或 "machine learning"）

## 输出JSON格式
{
  "queries": [
    {"query": "...", "aspect": "核心方法/应用/评估/对比/理论"},
    ...
  ],
  "key_terms": ["term1", "term2", ...],
  "suggested_venues": ["conference/journal names if known"]
}

## 研究目标
{goal}

## 任务类型
{task_type}
"""

FEEDBACK_REWRITE_PROMPT = """
你是一名学术文献检索专家。之前的搜索未能找到足够相关的文献，请基于反馈调整搜索策略。

## 上次的搜索query
{previous_queries}

## 导师反馈/打回原因
{feedback}

## 搜索结果中的问题
{issues}

## 原始研究目标
{goal}

## 请生成新的改进query
要求：
1. 避免重复之前的query
2. 根据反馈调整搜索角度
3. 尝试更具体或更宽泛的表述
4. 考虑相关但不同的学术领域

输出JSON同上。
"""


class QueryRewriter:
    def __init__(self):
        self.llm = create_llm_provider()
    
    async def rewrite(self, research_goal: str, task_type: str = "literature_survey") -> dict:
        """将研究目标转化为多个精准搜索query"""
        prompt = REWRITE_PROMPT.format(goal=research_goal, task_type=task_type)
        result = await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            role="graduate",
            json_schema={...}  # QueryRewriteSchema
        )
        return result
    
    async def rewrite_with_feedback(
        self, 
        research_goal: str, 
        previous_queries: list[str],
        feedback: str,
        issues: str = ""
    ) -> dict:
        """基于审核反馈生成改进的搜索query"""
        prompt = FEEDBACK_REWRITE_PROMPT.format(
            goal=research_goal,
            previous_queries="\n".join(previous_queries),
            feedback=feedback,
            issues=issues
        )
        result = await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            role="graduate",
            json_schema={...}
        )
        return result


query_rewriter = QueryRewriter()
```

### 1.3 集成点

修改 `evidence_pipeline_service.py`：

```python
# 修改前
query = self._query_for_task(task)
results = await self.evidence_provider.search_with_trace(query)

# 修改后
raw_goal = self._query_for_task(task)
rewrite_result = await query_rewriter.rewrite(raw_goal, task.get("task_type"))

all_results = []
for q in rewrite_result["queries"]:
    results = await self.evidence_provider.search_with_trace(q["query"])
    all_results.extend(results)

# 去重
all_results = deduplicate_by_doi_or_title(all_results)
```

---

## 2. 启用并扩展网络搜索

### 2.1 Tavily配置激活

```bash
# .env 必填
WEB_SEARCH_ENABLED=true
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxx
```

### 2.2 添加备选搜索引擎（降低单点依赖）

新增 `backend/app/services/serper_search.py`（Serper = Google Search API包装）：

```python
"""
Serper.dev - Google Search API
免费层: 2500次/月
优势: 覆盖面广，中英文都支持，学术结果质量高
"""
import httpx

class SerperSearchProvider:
    BASE_URL = "https://google.serper.dev/search"
    
    async def search(self, query: str, num_results: int = 10) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.BASE_URL,
                json={"q": query, "num": num_results},
                headers={"X-API-KEY": settings.serper_api_key}
            )
            data = resp.json()
            return self._parse_results(data.get("organic", []))
```

### 2.3 Google Scholar 集成

```python
"""
通过 SerpAPI 的 Google Scholar 引擎获取学术结果
比 CrossRef/OpenAlex 的学术搜索质量更高
"""
class GoogleScholarProvider:
    async def search(self, query: str) -> list[dict]:
        # 使用 serpapi.com/google-scholar-api
        # 或使用 scholarly 库 (免费但可能被限流)
        pass
```

---

## 3. 修复返工时Query不变问题

### 3.1 当前问题代码

在 `run_execution_service.py` 中，创建修订任务时：

```python
# 当前逻辑：修订任务的description和title与原始任务相同
revision_task = {
    "title": f"[修订] {original_task['title']}",
    "description": original_task["description"],  # ← 问题：和原始一样
    ...
}
```

### 3.2 修复方案

```python
# 修改 run_execution_service.py 中创建修订任务的逻辑

async def _create_revision_task(self, original_task: dict, review_result: dict) -> dict:
    # 1. 提取导师反馈中的搜索建议
    feedback = review_result.get("feedback", "")
    missing_aspects = review_result.get("missing_aspects", [])
    
    # 2. 生成改进的搜索query
    improved_queries = await query_rewriter.rewrite_with_feedback(
        research_goal=original_task["description"],
        previous_queries=original_task.get("_search_queries_used", []),
        feedback=feedback,
        issues="; ".join(missing_aspects)
    )
    
    # 3. 在修订任务中携带搜索改进信息
    revision_task = {
        "title": f"[修订] {original_task['title']}",
        "description": original_task["description"],
        "revision_of_task_id": original_task["id"],
        # 新增：携带搜索策略改进
        "_revision_search_hints": improved_queries,
        "_previous_search_queries": original_task.get("_search_queries_used", []),
        "_revision_feedback": feedback,
    }
    return revision_task
```

同步修改 `evidence_pipeline_service.py`：

```python
async def collect_for_task(self, task: dict) -> list:
    # 如果是修订任务且有搜索提示，使用改进的query
    if task.get("_revision_search_hints"):
        queries = [q["query"] for q in task["_revision_search_hints"]["queries"]]
    else:
        raw_goal = self._query_for_task(task)
        rewrite_result = await query_rewriter.rewrite(raw_goal, task.get("task_type"))
        queries = [q["query"] for q in rewrite_result["queries"]]
    
    # 记录使用的query（供下次返工参考）
    task["_search_queries_used"] = queries
    
    # 多query并行搜索
    all_results = []
    for q in queries:
        results = await self.evidence_provider.search_with_trace(q)
        all_results.extend(results)
    
    return deduplicate(all_results)
```

---

## 4. 改进硬编码Fallback

### 4.1 方案：动态缓存替代静态列表

```python
# 修改 literature_source_service.py

class LiteratureSourceService:
    """
    改造为动态验证文献缓存，而非硬编码列表
    """
    
    def __init__(self):
        self._cache_path = Path("artifacts/literature_cache.json")
        self._cache = self._load_cache()
    
    def _load_cache(self) -> dict:
        """加载历次搜索中验证通过的文献"""
        if self._cache_path.exists():
            return json.loads(self._cache_path.read_text())
        return {"papers": [], "last_updated": None}
    
    def add_verified_paper(self, paper: dict):
        """当证据管道验证通过一篇论文时，加入缓存"""
        if not self._is_duplicate(paper):
            self._cache["papers"].append(paper)
            self._save_cache()
    
    def search_cache(self, query: str, top_k: int = 5) -> list[dict]:
        """从缓存中基于关键词搜索（作为远程搜索的补充，非替代）"""
        # 使用简单的TF-IDF或关键词匹配
        # 明确标记来源为 "local_cache" 而非 "web_search"
        pass
    
    # 移除 TRACEABLE_LIBRARY 硬编码列表
    # 或保留但仅在显式指定 FALLBACK_ENABLED=true 时启用
```

---

## 5. 增加搜索结果数量和去重

### 5.1 配置调整

```python
# config.py 修改默认值
evidence_max_results_per_source: int = 15  # 从5提升到15
evidence_max_total_results: int = 50       # 新增：总结果上限
literature_min_grounded_sources: int = 3   # 从2提升到3
```

### 5.2 智能去重

```python
class PaperDeduplicator:
    """
    跨数据源去重
    - DOI完全匹配
    - 标题模糊匹配 (Levenshtein距离 < 0.15)
    - 作者+年份+标题首词匹配
    """
    
    def deduplicate(self, papers: list[dict]) -> list[dict]:
        seen = {}
        unique = []
        for paper in papers:
            key = self._normalize_key(paper)
            if key not in seen:
                seen[key] = paper
                unique.append(paper)
            else:
                # 合并元数据（保留信息最全的版本）
                seen[key] = self._merge_metadata(seen[key], paper)
        return unique
```

---

## 6. 验证清单

完成Phase 1后，通过以下测试验证：

| 测试项 | 预期结果 |
|--------|----------|
| 中文研究目标 → query改写 | 生成4-8个英文学术query |
| 改写后的query → CrossRef搜索 | 返回≥5条相关结果 |
| 改写后的query → Tavily搜索 | 返回≥3条相关网页 |
| 完整搜索流程 | 总计≥10条去重后的来源 |
| LLM生成（有充足来源） | 不出现allowed_sources之外的引用 |
| 导师打回后返工 | 使用改进的query，搜索到新的文献 |
| 无网络时fallback | 明确报告"证据不足"而非返回假文献 |

---

## 7. 文件改动清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `backend/app/services/query_rewriter.py` | 智能query改写 |
| 修改 | `backend/app/services/evidence_pipeline_service.py` | 集成query改写，多query搜索 |
| 修改 | `backend/app/services/run_execution_service.py` | 修订任务携带搜索策略 |
| 修改 | `backend/app/services/literature_source_service.py` | 动态缓存替代硬编码 |
| 修改 | `backend/app/core/config.py` | 新增配置项 |
| 修改 | `.env` | 启用Tavily等搜索源 |
| 可选新增 | `backend/app/services/serper_search.py` | Google搜索备选 |
