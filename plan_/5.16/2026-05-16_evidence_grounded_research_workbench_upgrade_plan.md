# ResearchGroup-Agent 自动化研究工作台阶段性升级计划

**日期：** 2026-05-16  
**目标读者：** 项目维护者 / 后续实现 Agent  
**目标定位：** 将当前系统从“多 Agent 科研流程演示器”升级为“能真实辅助用户完成一项研究的、以证据为中心的自动化研究工作台”。  
**总体原则：** 先把“研究对象、证据链、实验链、用户阅读路径”做真，再逐步增强多 Agent、自主性和外部工具接入。  

---

## 0. 总体判断

当前项目已经具备较完整的工程骨架：

- `Run / Task / Output / Review / Approval / Memory / Evidence / ExperimentPlan` 等基础对象已经出现。
- 任务 DAG、审批、运行事件、Agent skill、实验执行器等能力已经开始成形。
- 前端已经有首页、任务板、运行页、产出页、实验页、Agent 页等基础界面。

但从“真实完成研究”的标准看，当前系统仍然存在四个根本问题：

1. **系统的一等对象仍然是流程，不是研究。**  
   当前主轴仍是 `Run -> Task -> Output -> Report`，研究被压缩成工单流，缺少 `ResearchQuestion / Hypothesis / Claim / Protocol / Decision / Uncertainty` 等真正支撑研究推进的核心对象。

2. **证据链还不是真实求证链。**  
   当前文献侧主要依赖内置 bibliography，`EvidenceProvider` 仍是预留接口；实验侧已有受控执行雏形，但许多实验仍是固定脚本或演示数据驱动，尚未围绕真实研究问题形成完整证据闭环。

3. **审核机制主要在检查“产物存在”，还没有真正检查“结论是否站得住”。**  
   当前 review rubric 对 `papers_read`、`methods_found`、`metrics` 等字段依赖较重，尚未建立 claim-level 的支持、反驳、置信度和缺口评估。

4. **前端信息架构按系统模块组织，不按研究者阅读路径组织。**  
   用户能看到很多页面和状态，但系统没有明确告诉用户：
   - 现在研究到了哪一步；
   - 当前最重要的结论是什么；
   - 哪些结论可信，哪些还只是暂定；
   - 下一步最值得看什么、做什么。

因此，后续升级不能继续把主要精力放在“再加一些 Agent 功能”上，而应转向：

> 先建立真实研究的骨架，再让 Agent 在这个骨架里工作。

---

## 1. 总体目标

### 1.1 产品目标

将 ResearchGroup-Agent 升级为一个能够围绕单个研究课题，完成以下闭环的自动化研究工作台：

```text
研究问题定义
-> 假设提出
-> 证据检索与整理
-> 方法选择
-> 实验设计与执行
-> 结果分析
-> 结论形成
-> 不确定性标注
-> 报告生成
-> 后续研究建议
```

### 1.2 用户完成一次研究时，系统必须能提供

1. 一个明确的研究问题与范围定义；
2. 一组显式假设，以及每个假设当前的验证状态；
3. 可追溯的证据来源、证据主张和支持/反驳关系；
4. 可复现的实验协议、数据、命令、指标和结果文件；
5. 结论与证据之间的一一映射；
6. 清楚标注的未知项、风险项和下一步研究动作；
7. 一份不是“任务汇总”，而是“围绕研究问题展开论证”的报告。

### 1.3 阶段性成功标准

完成本计划前半段后，至少要达到以下状态：

- 用户可以提交一个明确研究问题；
- 系统可以生成研究简报、假设、证据计划和实验计划；
- 系统能接入真实文献来源或真实用户上传材料，而不是只依赖内置样例；
- 实验产物能被真实执行、复现、引用；
- 报告中的每个关键结论都能回溯到证据和实验；
- 前端首页能回答五个问题：
  1. 现在研究到哪里了？
  2. 当前最重要的结论是什么？
  3. 哪些结论最可信？
  4. 哪些地方仍然不确定？
  5. 用户下一步应该看什么或确认什么？

---

## 2. 总体开发原则

### 2.1 先做真的，再做大的

- 先做一个狭窄但真实可用的研究闭环；
- 不追求一开始就覆盖所有学科；
- 第一阶段优先支持“文献综述 + 小型可复现实验 + 研究报告”这一类可验证课题。

### 2.2 研究对象优先于 Agent 角色

- 研究对象是系统主轴；
- Agent 只是推进研究对象状态变化的执行者；
- 不再让“谁来做”压过“我们究竟在证明什么”。

### 2.3 证据优先于叙事

- 报告不能先有漂亮话，再补证据；
- 结论必须先绑定证据，再进入最终报告；
- 无法支撑的结论必须保留为 `tentative / unsupported / needs_more_evidence`。

### 2.4 自动化必须保留可审查性

- 所有外部检索、实验执行、报告发布都要保留来源、时间、输入、输出；
- 关键步骤允许自动推进，但必须能够被用户复盘；
- 当前阶段宁可“自动化少一点”，也不能“自动化得不可信”。

### 2.5 先建立契约，再预留扩展

- 每一阶段都要有稳定数据模型、API 契约和 artifacts 约定；
- 后续外部工具、远程执行、向量库、图数据库、多用户等能力只做接口预留，不在早期阶段展开实现。

---

## 3. 总体任务边界

### 3.1 当前阶段必须做

- 建立真实研究所需的核心领域模型；
- 将证据、假设、结论、实验协议从 task 输出中独立出来；
- 引入真实可追溯证据来源；
- 将实验从“演示脚本”升级为“围绕研究问题的可复现实验”；
- 重写报告链路，使其围绕 claim 和 evidence 生成；
- 重组前端信息架构，让用户先看到研究进展和研究结论，再看到内部流程；
- 保持 `MOCK_MODE=true` 下仍可完整演示，但同时支持真实模式逐步接入。

### 3.2 当前阶段严禁做

- 严禁把目标继续定义为“Agent 数量更多、协作动画更多、流程更热闹”；
- 严禁优先开发花哨 office、3D、社交化、多角色闲聊；
- 严禁一开始就支持多学科、多团队、多导师、多租户；
- 严禁直接接一堆外部工具却没有统一证据模型；
- 严禁让系统自动生成无法回溯来源的最终结论；
- 严禁让实验结果脱离真实输入、真实命令和真实 artifacts；
- 严禁为了“显得智能”而隐藏失败、不确定性和反证。

### 3.3 本计划只覆盖

- 单课题；
- 单用户；
- 单机优先；
- 本地 artifacts；
- 文献、附件、实验、报告这条主链路；
- 受控自动化；
- 可逐步扩展的接口设计。

---

## 4. 分阶段路线图总览

| 阶段 | 名称 | 目标 | 优先级 |
|---|---|---|---|
| Phase 0 | 基线修复与契约冻结 | 先把现有系统变成可继续演进的可靠地基 | P0 |
| Phase 1 | 研究核心模型重建 | 从 task-first 改为 research-object-first | P0 |
| Phase 2 | 真实证据链建设 | 让系统真的能围绕问题收集与组织证据 | P0 |
| Phase 3 | 可复现实验闭环 | 让实验真正回答问题，并能被复盘和引用 | P1 |
| Phase 4 | 迭代式研究编排 | 从一次性流程变成“提出-验证-修正”的循环 | P1 |
| Phase 5 | 用户工作台重构 | 让用户知道先看什么、现在相信什么、下一步做什么 | P1 |
| Phase 6 | 扩展接口与平台化预留 | 为后续大规模能力接入留出稳定边界 | P2 |

---

## 5. Phase 0：基线修复与契约冻结

### 5.1 阶段目标

先修地基，不在混乱的基础上继续堆功能。该阶段完成后，系统必须具备：

- 可读；
- 可测；
- 可追踪；
- 可安全扩展。

### 5.2 必须做

1. **彻底清理乱码和编码问题**
   - 前端 UI 文案；
   - Prompt；
   - 报告模板；
   - README / plan；
   - artifacts 文件名与正文；
   - API 返回的中文字段。

2. **冻结现有运行链路契约**
   - 明确当前 `Run / Task / Output / Review / Approval / Memory / Evidence / ExperimentPlan` 的字段语义；
   - 补齐缺失的接口文档；
   - 明确哪些字段是过渡字段，后续会被新模型替代。

3. **建立最小测试基线**
   - 后端接口 smoke；
   - 前端关键页面 smoke；
   - 一条完整 mock run；
   - 一条真实附件输入 run；
   - 一条 experiment approval run；
   - 一条 report publish run。

4. **统一 artifacts 生命周期**
   - 规范 run 目录；
   - 明确输入、证据、实验、报告、日志的目录结构；
   - 不再出现“有 workspace 但没有正式研究产物”的情况。

5. **补齐状态机边界**
   - 明确 `created / decomposing / scheduling / executing / reviewing / waiting_confirmation / reporting / completed / failed / cancelled` 的转换条件；
   - 明确 task 与 run 的阻塞关系；
   - 明确审批后的恢复逻辑。

### 5.3 严禁做

- 严禁在本阶段引入新的复杂 Agent；
- 严禁新增外部检索源；
- 严禁重写整个前端；
- 严禁开始做多用户、云同步、远程执行；
- 严禁在没有测试基线的情况下继续扩展更多能力。

### 5.4 预留接口

- `ArtifactStore` 抽象；
- `RunStateMachine` 抽象；
- `PromptContractValidator`；
- `ArtifactManifest`；
- `ResearchObjectRepository` 预留 namespace。

### 5.5 验收标准

- 所有主界面中文可读；
- 一条 mock run 从创建到报告生成全链路稳定；
- 一条带附件 run 能稳定进入 artifacts；
- 一条需要审批的实验 run 可暂停、确认、继续；
- 现有模型与 API 文档化完成；
- 后续阶段开发不再依赖口口相传的隐式约定。

---

## 6. Phase 1：研究核心模型重建

### 6.1 阶段目标

把系统主轴从“任务流程”切换为“研究对象”。该阶段完成后，系统应该已经能明确表达：

- 研究问题是什么；
- 研究要验证哪些假设；
- 当前有哪些 claim；
- 哪些 claim 已被支持、反驳或仍待验证；
- 研究中有哪些决策和不确定性。

### 6.2 必须做

新增以下核心模型：

1. `ResearchBrief`
   - `id`
   - `run_id`
   - `title`
   - `research_question`
   - `background`
   - `scope`
   - `success_criteria`
   - `constraints`
   - `created_at`
   - `updated_at`

2. `Hypothesis`
   - `id`
   - `run_id`
   - `statement`
   - `rationale`
   - `status: proposed | active | supported | weakened | rejected`
   - `confidence`
   - `related_claim_ids`
   - `related_experiment_ids`

3. `Claim`
   - `id`
   - `run_id`
   - `statement`
   - `claim_type: observation | interpretation | recommendation`
   - `status: unsupported | tentative | supported | disputed`
   - `confidence`
   - `supporting_evidence_ids`
   - `opposing_evidence_ids`
   - `source_task_id`

4. `DecisionLog`
   - `id`
   - `run_id`
   - `decision`
   - `reasoning`
   - `alternatives_considered`
   - `linked_claim_ids`
   - `created_at`

5. `Uncertainty`
   - `id`
   - `run_id`
   - `description`
   - `kind: missing_evidence | conflicting_evidence | methodological_risk | external_dependency`
   - `severity`
   - `resolution_plan`
   - `status`

6. `ResearchMilestone`
   - 用于表达“研究阶段目标”，替代部分过度依赖 task status 的展示。

### 6.3 需要改造的现有模块

- `task_decomposer.py`
  - 从“直接拆 3-7 个任务”改为：
    1. 先生成 `ResearchBrief`；
    2. 再生成初始 `Hypothesis`；
    3. 最后根据 brief/hypothesis 派生任务。

- `task_executor.py`
  - 任务输出不再只生成 summary/findings；
  - 必须允许产出 claim、evidence_request、protocol_request、uncertainty_update。

- `review_service.py`
  - 从 task-level review 逐步扩展到 claim-level review。

- `report_service.py`
  - 先保持兼容；
  - 但报告数据源要开始转向 `Claim + Evidence + Experiment + Decision`。

### 6.4 严禁做

- 严禁此阶段就把所有 task 删掉；
- 严禁一下子改成完全自治研究；
- 严禁让 hypothesis 只存在于 prompt，不落库；
- 严禁把 claim 继续藏在 JSON blob 中；
- 严禁为了界面好看而先做“结论图谱”，却没有真实领域模型支撑。

### 6.5 预留接口

- `ResearchBriefService`
- `HypothesisService`
- `ClaimService`
- `DecisionService`
- `UncertaintyService`
- `ResearchGraphService`
- `ClaimEvaluationProvider`

### 6.6 验收标准

- 任意 run 都能在 UI 和 API 中看到研究问题、假设、claim、不确定性；
- 任务能够关联到 hypothesis 或 claim；
- 研究总结不再只能从 task outputs 反推，而能直接从研究对象读取；
- 新模型在 mock 模式下也能完整生成。

---

## 7. Phase 2：真实证据链建设

### 7.1 阶段目标

让系统从“引用资料”升级为“组织证据”。该阶段完成后，系统必须能够：

- 基于研究问题检索真实来源；
- 区分来源、摘录、主张、方法、反证；
- 让每一个 claim 都能回溯到支持它的 evidence；
- 对证据缺口做显式提示。

### 7.2 必须做

1. **升级证据模型**
   - 在现有 `EvidenceSource / EvidenceClaim` 基础上新增：
     - `EvidenceExcerpt`
     - `EvidenceAssessment`
     - `EvidenceLink`
   - 支持：
     - 支持关系；
     - 反驳关系；
     - 方法来源；
     - 数据来源；
     - 可信度；
     - 原文定位；
     - 采集时间。

2. **实现真实 EvidenceProvider**
   - 第一批只接一种到两种真实来源即可：
     - 用户上传文档；
     - arXiv / Crossref / Semantic Scholar 三选一或两种；
   - 要求统一输出 schema；
   - 内置 bibliography 退化为 mock fallback，不再作为真实模式主路径。

3. **建立证据采集流水线**
   - query plan；
   - retrieval；
   - dedup；
   - extraction；
   - citation normalization；
   - evidence scoring；
   - claim linking。

4. **建立证据质量规则**
   - 是否一手来源；
   - 是否同行评审；
   - 是否过时；
   - 是否与当前问题直接相关；
   - 是否与其他证据冲突；
   - 是否存在反证。

5. **前端新增证据工作台**
   - 来源列表；
   - 摘录；
   - claim 绑定；
   - 支持 / 反驳标记；
   - 缺证据提醒；
   - 引用预览。

### 7.3 严禁做

- 严禁现阶段接一堆来源却没有统一 schema；
- 严禁把搜索结果直接当结论；
- 严禁只做“论文标题列表”，不做 claim 映射；
- 严禁让最终报告引用无出处文本；
- 严禁在证据质量还没建立前做大规模自动写综述。

### 7.4 预留接口

- `EvidenceProvider` 插件化；
- `CitationResolver`;
- `DocumentParser`;
- `ChunkingStrategy`;
- `RetrieverBackend`;
- `VectorIndexBackend`;
- `SourceRanker`;
- `EvidenceConflictDetector`;
- 后续 Zotero / 本地文献库 / PDF parser 接口。

### 7.5 验收标准

- 用户提交一个真实问题后，系统能基于真实来源生成证据集合；
- 至少一个 claim 同时展示 supporting evidence 与 opposing evidence；
- UI 可以从 claim 反查到来源与摘录；
- 报告中的引用均可追溯；
- 当证据不足时，系统能明确说“不足以支持该结论”。

---

## 8. Phase 3：可复现实验闭环

### 8.1 阶段目标

让实验从“Agent 生成一个脚本”升级为“为验证 hypothesis 而设计、执行、记录、解释的一套协议”。

### 8.2 必须做

1. **新增实验领域模型**
   - `ExperimentProtocol`
   - `DatasetSpec`
   - `MetricSpec`
   - `BaselineSpec`
   - `ExperimentRun`
   - `ExperimentResult`
   - `ExperimentFinding`

2. **从 hypothesis 生成 protocol**
   - 每个实验必须回答一个明确问题；
   - 明确：
     - 自变量；
     - 因变量；
     - 基线；
     - 指标；
     - 数据来源；
     - 停止条件；
     - 预期风险。

3. **升级现有实验执行器**
   - 保留当前受控执行与审批；
   - 将固定 demo script 改造成：
     - 由 protocol 生成 workspace；
     - 由真实输入或用户上传数据驱动；
     - 产出规范化 artifacts；
     - 回写 experiment result。

4. **实验结果必须进入 claim 评估**
   - 实验不是孤立页面；
   - 实验 finding 必须支持、削弱或反驳某个 hypothesis / claim。

5. **失败实验也必须被保留**
   - 保存 stdout/stderr；
   - 保存退出码；
   - 保存失败解释；
   - 报告中允许出现“实验未能支持假设”。

### 8.3 严禁做

- 严禁继续把“实验跑通”直接等价于“研究完成”；
- 严禁实验数据、指标、基线都写死在服务内部；
- 严禁失败实验被静默丢弃；
- 严禁未经审批执行高风险命令；
- 严禁此阶段就引入 GPU 集群、远程执行、分布式调度。

### 8.4 预留接口

- `ExperimentBackend`
- `DatasetProvider`
- `MetricEvaluator`
- `ExecutionSandbox`
- `RemoteRunner`
- `DockerRunner`
- `NotebookExporter`
- `ResultVisualizer`

### 8.5 验收标准

- 至少一种真实研究场景能生成 protocol、执行 experiment、产出 result；
- 一个 hypothesis 能因为实验结果被 supported / weakened / rejected；
- 实验 artifacts 可以复盘；
- 报告中能引用实验命令、数据、指标、结果；
- 失败实验不会被系统伪装成成功。

---

## 9. Phase 4：迭代式研究编排

### 9.1 阶段目标

将系统从“一次性流水线”升级为“研究循环”：

```text
提出假设
-> 收集证据
-> 设计实验
-> 获取结果
-> 更新 claim / hypothesis
-> 识别缺口
-> 生成下一轮研究动作
```

### 9.2 必须做

1. **新增 Research Loop Orchestrator**
   - 不再只按固定 task type 执行；
   - 根据 `Uncertainty`、`Claim status`、`Evidence gap`、`Experiment result` 决定下一步。

2. **引入研究状态机**
   - `framing`
   - `evidence_gathering`
   - `hypothesis_testing`
   - `synthesis`
   - `revision`
   - `ready_to_report`

3. **把任务生成改为按研究缺口驱动**
   - 缺文献 -> 生成 retrieval task；
   - claim disputed -> 生成 counter-evidence task；
   - hypothesis active but untested -> 生成 experiment task；
   - 证据冲突 -> 生成 adjudication task。

4. **引入 stop / continue 判断**
   - 达到 success criteria；
   - 预算耗尽；
   - 证据不足；
   - 需用户决策；
   - 可继续自动研究。

5. **让 Agent 分工回归服务于研究**
   - 调度器仍可保留；
   - 但调度对象要来自研究缺口，而不只是初始拆解。

### 9.3 严禁做

- 严禁继续只靠最初一次 task decomposition 跑到底；
- 严禁让系统为了“自动推进”而忽略证据冲突；
- 严禁把 loop 做成无限 agent 聊天；
- 严禁在没有预算、停止条件和审计记录时开放长循环。

### 9.4 预留接口

- `ResearchPlanner`
- `GapAnalyzer`
- `NextBestActionPolicy`
- `BudgetPolicy`
- `StopConditionEvaluator`
- `HumanInterventionPolicy`

### 9.5 验收标准

- 系统能根据研究缺口自动生成第二轮任务；
- 一个 claim 在新证据进入后能更新状态；
- 用户能看到“为什么现在要做这一步”；
- 系统能说明“继续研究的收益”和“现在停止的理由”。

---

## 10. Phase 5：用户工作台重构

### 10.1 阶段目标

让用户不需要理解系统内部实现，也能顺着界面看懂一项研究。

### 10.2 必须做

重构为三个核心工作区：

1. **Overview**
   - 研究问题；
   - 当前阶段；
   - 关键结论；
   - 置信度；
   - 未解决问题；
   - 下一步建议；
   - 当前需要用户确认的事项。

2. **Workbench**
   - hypothesis；
   - task graph；
   - experiment protocols；
   - blocked items；
   - approvals；
   - Agent 分工；
   - 最新进展。

3. **Evidence & Report**
   - claim -> evidence -> experiment -> paragraph 的追踪链；
   - 支持与反驳证据；
   - 证据缺口；
   - 报告草稿；
   - 最终报告；
   - 引用导出。

### 10.3 关键体验原则

- 首页默认先回答“研究结论”，不是先展示系统指标；
- 运行页默认先展示“现在最值得看什么”；
- 报告页默认先展示“关键结论及其证据”，不是先铺开全部内部输出；
- 审计视图保留，但退居次级；
- office 视图如果保留，应作为附属监控体验，不得压过主工作流。

### 10.4 严禁做

- 严禁继续堆砌同级页面，让用户自己拼装研究故事；
- 严禁把 dashboards 做成指标墙；
- 严禁把 `outputs` 当作真正面向用户的最终信息架构；
- 严禁继续优先扩展视觉装饰而不解决阅读路径。

### 10.5 预留接口

- `ResearchOverviewViewModel`
- `ClaimEvidenceViewModel`
- `ResearchTimelineViewModel`
- `InterventionQueueViewModel`
- `ReportCompositionViewModel`

### 10.6 验收标准

- 新用户第一次进入 run 页面，30 秒内能说出：
  - 研究问题；
  - 当前结论；
  - 最大不确定性；
  - 下一步动作；
- 每个关键 claim 都能点击回证据和实验；
- 用户不需要在 4 个页面之间跳转才能理解同一个结论；
- 报告读起来像研究报告，而不是任务日报。

---

## 11. Phase 6：扩展接口与平台化预留

### 11.1 阶段目标

在核心研究闭环稳定后，再为后续平台化留下扩展位。

### 11.2 当前只预留，不实现

1. **外部证据源**
   - Zotero
   - Semantic Scholar
   - Crossref
   - arXiv
   - 用户私有知识库

2. **检索与记忆**
   - 向量数据库；
   - 图数据库；
   - 项目级长期记忆；
   - 跨 run 研究资产复用。

3. **实验执行**
   - Docker；
   - 远程主机；
   - GPU；
   - 队列系统；
   - Notebook export。

4. **协作**
   - 多用户；
   - 多导师；
   - 权限；
   - 评论；
   - 审阅流。

5. **平台能力**
   - 插件系统；
   - 模型路由；
   - 成本策略；
   - 自动评测；
   - 研究模板市场。

### 11.3 预留要求

- 所有 provider 都必须接口化；
- 所有 artifacts 都必须有 manifest；
- 所有外部引用都必须保留来源 metadata；
- 研究核心模型不得依赖某个单一外部工具；
- 即使未来接入新工具，`Claim / Evidence / Protocol / Result` 仍是系统内部稳定语言。

---

## 12. 建议的数据模型演进顺序

### 12.1 立即新增

- `research_briefs`
- `hypotheses`
- `claims`
- `decision_logs`
- `uncertainties`
- `research_milestones`

### 12.2 第二批新增

- `evidence_excerpts`
- `evidence_assessments`
- `claim_evidence_links`
- `experiment_protocols`
- `experiment_runs`
- `experiment_results`

### 12.3 后续预留

- `research_templates`
- `research_assets`
- `research_versions`
- `cross_run_memories`
- `provider_connections`

---

## 13. 建议的服务层演进顺序

### 13.1 第一批服务

- `research_brief_service.py`
- `hypothesis_service.py`
- `claim_service.py`
- `uncertainty_service.py`
- `decision_service.py`
- `research_graph_service.py`

### 13.2 第二批服务

- `evidence_pipeline_service.py`
- `citation_resolver.py`
- `document_parser.py`
- `claim_evaluation_service.py`
- `experiment_protocol_service.py`
- `experiment_result_service.py`

### 13.3 第三批服务

- `research_planner.py`
- `gap_analyzer.py`
- `next_best_action_service.py`
- `research_synthesis_service.py`

---

## 14. 建议的前端演进顺序

### 14.1 第一批页面改造

- 首页：从“创建 run + cockpit”改为“创建研究 + 最近研究摘要”；
- run 页：新增 overview 默认视图；
- outputs 页：逐步降级为内部 artifacts 页；
- 新增 claim/evidence 关联视图；
- 新增 hypothesis 面板。

### 14.2 第二批页面改造

- 新增 evidence workbench；
- 新增 experiment protocol/detail；
- 新增 uncertainty / next action 面板；
- 新增 report composition 视图。

### 14.3 第三批页面改造

- office 视图变成附属监控；
- skills 页面与研究工作流解耦；
- 审计页保留但不再作为主阅读路径。

---

## 15. 优先级清单

### P0：必须先做

1. 清理乱码与 artifacts 规范；
2. 新增研究核心模型；
3. 让报告开始围绕 claim 组织；
4. 建立真实 evidence provider；
5. 建立 claim-evidence 绑定；
6. 为实验协议建模。

### P1：随后推进

1. 真实实验闭环；
2. 研究 loop orchestrator；
3. Overview / Workbench / Evidence & Report 前端重构；
4. 停止条件、预算、下一步动作建议。

### P2：核心稳定后再做

1. 向量检索；
2. 外部文献库；
3. 远程实验后端；
4. 跨 run 记忆；
5. 多用户与权限。

### P3：远期可选

1. 多导师；
2. 模板市场；
3. 可视化研究图谱；
4. 复杂自动评测；
5. 更强自治 Agent。

---

## 16. 本阶段推荐实施顺序

1. **先完成 Phase 0**
   - 否则后续所有改造都会踩在不稳定地基上。

2. **Phase 1 与 Phase 2 紧密衔接**
   - 没有 `Claim`，证据不知道要支持谁；
   - 没有真实 `Evidence`，claim 仍然只是漂亮文本。

3. **Phase 3 只选一个窄场景做真**
   - 例如：
     - RAG 方案比较；
     - 排序算法比较；
     - 小型 benchmark 复现；
   - 不要一开始就追求通用科研平台。

4. **Phase 4 再引入迭代研究**
   - 在 claim/evidence/experiment 还不稳时，不要急着上自主循环。

5. **Phase 5 与 Phase 4 可部分并行**
   - 当核心对象稳定后，前端可同步重构；
   - 但不应在 Phase 1 前大规模重做 UI。

---

## 17. 最小可行研究闭环定义

建议把下一版真正的 MVP 定义为：

```text
用户提交一个研究问题
-> 系统生成 ResearchBrief 与 Hypothesis
-> 系统检索真实证据并建立 Claim
-> 系统围绕至少一个 Hypothesis 生成 ExperimentProtocol
-> 用户审批后执行实验
-> 系统将实验结果写回 Claim/Hypothesis
-> 系统标注支持、反驳、不确定
-> 系统生成可追溯报告
```

### 该闭环完成前，以下事情都不应抢优先级

- office 视觉升级；
- 更多 Agent 人设；
- 多页面扩张；
- 多租户；
- 云同步；
- 花哨可视化；
- 插件市场；
- “完全自治”的营销式能力。

---

## 18. 最终产品形态判断

### 当前形态

`Multi-agent research workflow simulator`

### 本计划完成后的目标形态

`Evidence-grounded automated research workbench`

### 更远期才考虑的形态

`Semi-autonomous research group operating system`

顺序不能倒。  
只有先把“证据、实验、结论、阅读路径”做真，后面的 Agent 自主化才有意义。

