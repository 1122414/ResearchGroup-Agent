# Phase 3：质量保障与Grounding增强

**优先级：** 高（P1）  
**预计工期：** 1-2周  
**前置依赖：** Phase 1（部分可并行）  
**目标：** 从依赖prompt指令约束LLM，转为结构化机制强制保证输出基于真实证据

---

## 1. 核心问题：Prompt约束为何不够

当前的学术诚信机制本质上是 **"指令式约束"**：

```
Prompt: "你不得编造论文..."
LLM: （尝试遵守，但当证据不足时仍会幻觉补充）
```

**为什么prompt约束不可靠？**

| 原因 | 说明 |
|------|------|
| 指令遵循有概率性 | LLM不是确定性系统，长输出中容易忘记约束 |
| 知识边界模糊 | LLM无法准确区分"搜索结果提供的信息"和"训练数据中的记忆" |
| 输出压力 | 当被要求"覆盖面要广"时，倾向于补充内容以满足长度/深度要求 |
| 检查粒度不足 | 只检查`references_used`字段，不检查正文中的隐式引用 |

**解决方向：从"告诉LLM不要做"变为"让LLM做不到"（结构化Grounding）**

---

## 2. 结构化Grounding生成

### 2.1 设计原理

```
传统方式: LLM自由生成 → 事后检查是否有幻觉
Grounding: LLM只能引用编号片段 → 结构上不可能编造
```

### 2.2 核心实现

```python
"""
backend/app/services/grounded_generation.py

结构化Grounding生成器
确保LLM输出中的每个事实性陈述都有明确的证据支撑
"""

from dataclasses import dataclass


@dataclass
class EvidenceSnippet:
    """一个可引用的证据片段"""
    id: str           # E1, E2, ...
    source_id: str    # 来源论文/网页的唯一ID
    title: str        # 来源标题
    text: str         # 证据原文片段（200-500字）
    doi: str          # DOI（如有）
    url: str          # URL
    year: str         # 发表年份
    authors: str      # 作者


class GroundedGeneration:
    """
    强制LLM基于证据片段生成内容
    
    核心规则：
    1. 每个陈述必须标注来源编号 [E_n]
    2. 不允许使用证据之外的信息
    3. 证据不足时必须明确说明
    """
    
    GROUNDED_PROMPT_TEMPLATE = """
## 你的唯一知识来源

以下是经过验证的证据片段，编号为 E1 至 E{n}。
你只能基于这些片段中的信息进行回答。

{evidence_block}

---

## 严格规则

1. **引用标注**：你的每一句事实性陈述后必须标注来源，格式为 [E1] 或 [E1][E3]
2. **禁止外部知识**：不得使用上述证据之外的任何信息，包括你训练数据中的知识
3. **诚实承认不足**：如果证据不足以回答某个方面，明确写"基于当前证据，该方面信息不足"
4. **不得推测**：不能写"据推测"、"可能"加上你编造的内容。如果证据没有，就是没有
5. **不得补充论文**：不能在回答中提及任何未出现在上述证据中的论文、作者、年份或DOI
6. **元信息一致**：引用来源时，标题、作者、年份必须与证据片段中完全一致

## 违规示例（绝对禁止）
- ❌ "Smith et al. (2023) 提出了..." （如果E1-E{n}中没有Smith 2023）
- ❌ "此外，还有研究表明..." （没有标注来源编号）
- ❌ "根据相关文献..." （模糊引用，必须具体到E几）

## 合规示例
- ✅ "Transformer架构通过self-attention机制实现了长距离依赖建模 [E3]"
- ✅ "基于当前证据，尚无关于该方法在小样本场景下的实验数据"
- ✅ "与传统方法相比，该方法在BLEU分数上提升了15% [E2][E7]"

---

## 研究问题

{research_goal}

## 输出要求

请基于上述证据片段，生成结构化的研究综述。
输出JSON格式：
{{
    "summary": "200字以内的核心摘要（必须有引用标注）",
    "findings": [
        {{"point": "发现1（含引用标注）", "evidence_ids": ["E1", "E3"], "confidence": "high/medium/low"}},
        ...
    ],
    "gaps": ["证据不足的方面1", ...],
    "references_used": ["E1", "E2", ...],
    "coverage_self_assessment": "对研究问题的覆盖度自评（0-1）"
}}
"""

    def build_prompt(self, goal: str, snippets: list[EvidenceSnippet]) -> str:
        """构建Grounding prompt"""
        evidence_block = self._format_evidence_block(snippets)
        return self.GROUNDED_PROMPT_TEMPLATE.format(
            n=len(snippets),
            evidence_block=evidence_block,
            research_goal=goal
        )
    
    def _format_evidence_block(self, snippets: list[EvidenceSnippet]) -> str:
        """格式化证据片段"""
        blocks = []
        for s in snippets:
            block = f"""
### [{s.id}] {s.title}
- **作者**: {s.authors}
- **年份**: {s.year}
- **DOI**: {s.doi or "N/A"}
- **URL**: {s.url or "N/A"}
- **来源ID**: {s.source_id}

> {s.text}
"""
            blocks.append(block)
        return "\n".join(blocks)
    
    async def verify_grounding(self, output: dict, snippets: list[EvidenceSnippet]) -> "GroundingReport":
        """
        验证LLM输出是否严格基于证据片段
        
        检查项：
        1. 所有引用标注 [E_n] 是否对应有效的snippet
        2. 是否存在无标注的事实性陈述
        3. references_used是否与正文引用一致
        4. 是否出现了snippet中不存在的论文/作者/年份
        """
        violations = []
        
        # 检查1: 引用标注有效性
        cited_ids = self._extract_citations(output)
        valid_ids = {s.id for s in snippets}
        invalid_citations = cited_ids - valid_ids
        if invalid_citations:
            violations.append(f"引用了不存在的证据编号: {invalid_citations}")
        
        # 检查2: 未标注的事实性陈述
        ungrounded = self._find_ungrounded_claims(output, snippets)
        if ungrounded:
            violations.append(f"发现{len(ungrounded)}处无来源标注的事实性陈述")
        
        # 检查3: 幻觉检测 - 输出中是否有snippet中不存在的论文信息
        hallucinated = self._detect_hallucinated_references(output, snippets)
        if hallucinated:
            violations.append(f"检测到疑似幻觉引用: {hallucinated}")
        
        return GroundingReport(
            passed=len(violations) == 0,
            violations=violations,
            grounding_score=1.0 - len(violations) * 0.2,
            cited_evidence_ids=list(cited_ids & valid_ids)
        )
    
    def _extract_citations(self, output: dict) -> set:
        """从输出文本中提取所有 [E_n] 引用"""
        import re
        text = json.dumps(output, ensure_ascii=False)
        return set(re.findall(r'\[E\d+\]', text))
    
    def _find_ungrounded_claims(self, output: dict, snippets: list) -> list:
        """检测未标注来源的事实性陈述"""
        # 简单规则：包含年份(20xx)、百分比(xx%)、具体数字的句子如果没有[E_n]标注
        import re
        text = output.get("summary", "") + " ".join(f.get("point", "") for f in output.get("findings", []))
        sentences = re.split(r'[。.!！?？]', text)
        
        ungrounded = []
        for sent in sentences:
            if not sent.strip():
                continue
            has_fact_pattern = bool(re.search(r'(20\d{2}|[\d.]+%|\d+\.\d+)', sent))
            has_citation = bool(re.search(r'\[E\d+\]', sent))
            if has_fact_pattern and not has_citation:
                ungrounded.append(sent.strip())
        
        return ungrounded
    
    def _detect_hallucinated_references(self, output: dict, snippets: list) -> list:
        """检测输出中是否出现了证据片段中不存在的论文信息"""
        import re
        
        # 收集所有snippet中的作者和标题
        known_authors = set()
        known_titles = set()
        for s in snippets:
            known_authors.update(s.authors.lower().split(","))
            known_titles.add(s.title.lower())
        
        text = json.dumps(output, ensure_ascii=False).lower()
        
        # 检测 "Author et al. (Year)" 模式
        author_refs = re.findall(r'(\w+)\s+et\s+al\.?\s*\(?(\d{4})\)?', text)
        hallucinated = []
        for author, year in author_refs:
            if not any(author in a for a in known_authors):
                hallucinated.append(f"{author} et al. ({year})")
        
        return hallucinated


grounded_generation = GroundedGeneration()
```

---

## 3. DOI真实性验证

### 3.1 DOI解析验证器

```python
"""
backend/app/services/doi_verifier.py

通过DOI.org官方API验证论文DOI真实存在
"""

import httpx
from typing import Optional


@dataclass
class DOIVerificationResult:
    doi: str
    exists: bool
    title_match: bool  # 声称的title是否与DOI对应的真实title匹配
    real_title: Optional[str] = None
    real_authors: Optional[list] = None
    real_year: Optional[str] = None
    error: Optional[str] = None


class DOIVerifier:
    """
    验证DOI真实性
    
    验证层次：
    1. DOI是否存在（能否解析）
    2. 元数据是否匹配（title/authors/year）
    3. 年份是否合理（不能是未来的）
    """
    
    DOI_API = "https://api.crossref.org/works/"
    
    async def verify(self, doi: str, claimed_title: str = None,
                     claimed_year: str = None) -> DOIVerificationResult:
        """验证单个DOI"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.DOI_API}{doi}",
                    headers={"Accept": "application/json"}
                )
                
                if resp.status_code == 404:
                    return DOIVerificationResult(
                        doi=doi, exists=False, title_match=False,
                        error="DOI not found in CrossRef"
                    )
                
                if resp.status_code != 200:
                    return DOIVerificationResult(
                        doi=doi, exists=False, title_match=False,
                        error=f"API error: {resp.status_code}"
                    )
                
                data = resp.json()["message"]
                real_title = data.get("title", [""])[0]
                real_year = str(data.get("published-print", {}).get("date-parts", [[""]])[0][0])
                real_authors = [
                    f"{a.get('given', '')} {a.get('family', '')}"
                    for a in data.get("author", [])
                ]
                
                # 标题匹配检查（模糊匹配）
                title_match = True
                if claimed_title:
                    title_match = self._fuzzy_match(claimed_title, real_title)
                
                return DOIVerificationResult(
                    doi=doi,
                    exists=True,
                    title_match=title_match,
                    real_title=real_title,
                    real_authors=real_authors,
                    real_year=real_year
                )
                
        except Exception as e:
            return DOIVerificationResult(
                doi=doi, exists=False, title_match=False,
                error=str(e)
            )
    
    async def batch_verify(self, papers: list[dict]) -> list[DOIVerificationResult]:
        """批量验证论文DOI"""
        results = []
        for paper in papers:
            doi = paper.get("doi")
            if not doi:
                continue
            result = await self.verify(
                doi=doi,
                claimed_title=paper.get("title"),
                claimed_year=paper.get("year")
            )
            results.append(result)
            # 避免限流
            await asyncio.sleep(0.5)
        return results
    
    def _fuzzy_match(self, a: str, b: str, threshold: float = 0.8) -> bool:
        """模糊标题匹配"""
        from difflib import SequenceMatcher
        a_clean = a.lower().strip()
        b_clean = b.lower().strip()
        ratio = SequenceMatcher(None, a_clean, b_clean).ratio()
        return ratio >= threshold


doi_verifier = DOIVerifier()
```

### 3.2 集成到证据管道

```python
# 在 evidence_pipeline_service.py 中增加DOI验证步骤
async def _verify_evidence(self, sources: list[dict]) -> list[dict]:
    """对搜索结果进行DOI验证"""
    verified = []
    
    for source in sources:
        doi = source.get("doi")
        if doi:
            result = await doi_verifier.verify(doi, source.get("title"))
            if result.exists and result.title_match:
                source["_doi_verified"] = True
                verified.append(source)
            else:
                source["_doi_verified"] = False
                source["_verification_error"] = result.error
                # 记录但不使用
                logger.warning(f"DOI verification failed: {doi} - {result.error}")
        else:
            # 无DOI的来源需要URL验证
            source["_doi_verified"] = None
            verified.append(source)  # 暂时保留，靠浏览器验证
    
    return verified
```

---

## 4. 增强的输出审核

### 4.1 多层审核Pipeline

```python
"""
backend/app/services/output_auditor.py

LLM输出的多层审核管道
在导师审核之前，先进行程序化检查
"""


class OutputAuditor:
    """
    审核LLM生成的文献综述输出
    
    审核层次：
    Layer 1: 结构完整性检查（JSON格式、必填字段）
    Layer 2: 引用一致性检查（references_used vs 正文引用）
    Layer 3: Grounding验证（每个claim是否有证据支撑）
    Layer 4: 幻觉检测（是否出现allowed_sources之外的论文）
    Layer 5: 事实一致性（引用的年份、作者是否与来源匹配）
    """
    
    async def audit(self, output: dict, allowed_sources: list[dict],
                    evidence_snippets: list["EvidenceSnippet"]) -> AuditResult:
        """执行完整审核"""
        issues = []
        
        # Layer 1: 结构
        structural = self._check_structure(output)
        issues.extend(structural)
        
        # Layer 2: 引用一致性
        citation_issues = self._check_citation_consistency(output, allowed_sources)
        issues.extend(citation_issues)
        
        # Layer 3: Grounding
        grounding_report = await grounded_generation.verify_grounding(output, evidence_snippets)
        if not grounding_report.passed:
            issues.extend(grounding_report.violations)
        
        # Layer 4: 幻觉检测
        hallucinations = self._detect_hallucinations(output, allowed_sources)
        issues.extend(hallucinations)
        
        # Layer 5: 事实一致性
        fact_issues = self._check_fact_consistency(output, allowed_sources)
        issues.extend(fact_issues)
        
        return AuditResult(
            passed=len(issues) == 0,
            issues=issues,
            score=max(0, 1.0 - len(issues) * 0.15),
            layer_scores={
                "structure": 1.0 - len(structural) * 0.2,
                "citations": 1.0 - len(citation_issues) * 0.3,
                "grounding": grounding_report.grounding_score,
                "hallucination": 1.0 if not hallucinations else 0.3,
                "fact_consistency": 1.0 - len(fact_issues) * 0.2,
            }
        )
    
    def _detect_hallucinations(self, output: dict, allowed_sources: list[dict]) -> list[str]:
        """
        检测正文中是否存在allowed_sources之外的论文引用
        
        扫描模式：
        1. "Author et al. (Year)" 格式
        2. "Title (Year)" 格式
        3. DOI格式 "10.xxxx/..."
        4. arXiv ID格式 "arXiv:xxxx.xxxxx"
        """
        import re
        
        text = json.dumps(output, ensure_ascii=False)
        issues = []
        
        # 收集allowed_sources中的所有作者和标题
        allowed_authors = set()
        allowed_dois = set()
        for s in allowed_sources:
            for author in (s.get("authors") or "").split(","):
                allowed_authors.add(author.strip().lower())
            if s.get("doi"):
                allowed_dois.add(s["doi"].lower())
        
        # 检查 "Author et al." 模式
        for match in re.finditer(r'(\w{3,})\s+et\s+al', text, re.IGNORECASE):
            author = match.group(1).lower()
            if author not in allowed_authors and author not in {"evidence", "current", "above"}:
                issues.append(f"疑似幻觉作者引用: '{match.group(0)}' 不在allowed_sources中")
        
        # 检查未知DOI
        for match in re.finditer(r'10\.\d{4,}/[\w.\-/]+', text):
            doi = match.group(0).lower()
            if doi not in allowed_dois:
                issues.append(f"疑似幻觉DOI: '{doi}' 不在allowed_sources中")
        
        return issues


output_auditor = OutputAuditor()
```

---

## 5. 增强的导师审核Rubric

### 5.1 文献任务专用审核标准

```python
LITERATURE_REVIEW_RUBRIC = {
    "grounding": {
        "weight": 0.35,
        "description": "每个结论是否有明确的证据标注",
        "scoring": {
            1.0: "所有事实性陈述都有[E_n]标注且验证通过",
            0.7: "90%以上有标注，少量遗漏",
            0.4: "有标注但不完整，存在未标注的事实性陈述",
            0.1: "大量陈述无标注，疑似依赖模型记忆",
        }
    },
    "coverage": {
        "weight": 0.25,
        "description": "对研究目标的覆盖程度",
        "scoring": {
            1.0: "覆盖了研究目标的所有核心方面",
            0.7: "覆盖了主要方面，少量次要方面缺失",
            0.4: "只覆盖了部分方面",
            0.1: "严重偏离研究目标",
        }
    },
    "source_quality": {
        "weight": 0.25,
        "description": "来源的学术质量和相关性",
        "scoring": {
            1.0: "来源来自顶级期刊/会议，与主题高度相关",
            0.7: "多数来源质量良好",
            0.4: "来源质量参差不齐，部分不够相关",
            0.1: "来源质量差或与主题无关",
        }
    },
    "honesty": {
        "weight": 0.15,
        "description": "是否诚实报告了证据局限性",
        "scoring": {
            1.0: "明确标注了证据不足的方面和局限",
            0.7: "部分标注了局限",
            0.4: "未标注局限但也未编造",
            0.0: "隐藏证据不足，可能存在编造",
        }
    }
}
```

### 5.2 审核流程改进

```python
async def review_literature_output(self, output: dict, task: dict, 
                                    evidence_snippets: list) -> ReviewResult:
    """
    增强的文献任务审核
    
    新增：
    1. 先执行程序化审核（OutputAuditor）
    2. 如果程序化审核不通过，直接打回（不需要LLM审核）
    3. 程序化通过后，再用LLM做内容质量审核
    """
    
    # Step 1: 程序化审核（快速、确定性）
    audit_result = await output_auditor.audit(output, allowed_sources, evidence_snippets)
    
    if not audit_result.passed:
        return ReviewResult(
            passed=False,
            score=audit_result.score,
            feedback=f"程序化审核未通过: {'; '.join(audit_result.issues)}",
            revision_type="fix_citations",  # 告知修订类型
            search_suggestions=[]  # 不需要重新搜索，只需要修正引用
        )
    
    # Step 2: LLM内容质量审核（针对覆盖度、分析深度等）
    llm_review = await self._llm_review(output, task, LITERATURE_REVIEW_RUBRIC)
    
    return llm_review
```

---

## 6. 证据不足时的优雅处理

### 6.1 "诚实报告"机制

```python
class InsufficientEvidenceHandler:
    """
    当搜索结果不足以回答研究问题时的处理策略
    
    替代当前的"强制生成导致幻觉"问题
    """
    
    INSUFFICIENT_OUTPUT_TEMPLATE = {
        "status": "insufficient_evidence",
        "summary": "基于当前可获取的证据，无法充分回答研究问题。以下是已找到的有限信息。",
        "available_evidence": [],  # 已有的少量有效来源
        "gaps": [],  # 明确的证据缺口
        "suggested_actions": [
            "扩大搜索范围（建议使用的搜索关键词）",
            "用户提供种子论文",
            "调整研究问题范围",
        ],
        "partial_findings": [],  # 基于有限证据的初步发现
        "confidence": 0.0,  # 诚实的置信度
    }
    
    def should_report_insufficient(self, state: "ResearchState") -> bool:
        """判断是否应该报告证据不足"""
        return (
            state.iteration >= 3 and  # 已搜索多轮
            len(state.verified_sources) < 3 and  # 验证来源极少
            not state.sufficient
        )
    
    def generate_insufficient_report(self, state: "ResearchState") -> dict:
        """生成'证据不足'报告"""
        report = self.INSUFFICIENT_OUTPUT_TEMPLATE.copy()
        report["available_evidence"] = [
            {"title": s["title"], "doi": s.get("doi"), "relevance": "partial"}
            for s in state.verified_sources
        ]
        report["gaps"] = state.gaps
        report["search_history"] = state.search_history
        report["suggested_actions"] = self._suggest_next_steps(state)
        return report
```

---

## 7. 实施路线

| 步骤 | 优先级 | 依赖 | 说明 |
|------|--------|------|------|
| Grounded Prompt模板 | P0 | 无 | 改写prompt即可，零代码改动 |
| OutputAuditor | P0 | 无 | 纯规则检查，替代部分LLM审核 |
| DOI验证器 | P1 | 无 | 独立服务，可并行开发 |
| Grounding验证 | P1 | Grounded Prompt | 验证LLM是否遵守了Grounding规则 |
| 增强审核Rubric | P1 | OutputAuditor | 改进导师审核标准 |
| 证据不足处理 | P2 | 迭代引擎 | 需要Phase 2的状态信息 |

---

## 8. 效果预期

| 指标 | 当前 | Phase 3后预期 |
|------|------|--------------|
| 幻觉文献比例 | ~40-60% | <5% |
| 引用可追溯率 | ~30% | >95% |
| 首次审核通过率 | ~20% | >60% |
| 平均返工次数 | 2次（上限） | 0.5次 |
| "证据不足"正确报告率 | 0%（从不报告） | >80% |
