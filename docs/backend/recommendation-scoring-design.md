# Recommendation & Scoring 推荐与评分设计

> 状态：后端已实现（2026-07-08 WP4-A 落地 §4-§11/§17：三层管线 L3 精排、
> recommendation_policy 与 rubric 编译/生效、purpose 预算三桶、反馈再估计每日 job、
> 迁移 f1a2b3c4d5e6；测试 `backend/tests/test_recommendation_rerank.py`、
> `test_recommendation_policy.py`）。§7 排序一致性/空指标的前端展示面与解释字段
> 展示归 WP4-E；L2 语义层接口预留、默认关闭（§4.3）。
> 本文是推荐准入、三层推荐管线（规则粗排 → 可选语义层 → LLM 精排）、内容导向
> rubric、推荐 run、分数解释、排序一致性和反馈反哺的后端模块事实源。
> 机器契约：`config/contracts/recommendation_ranking.json`。
> 反馈数据本身见 `docs/backend/collaboration-notification-design.md`，
> 热度/来源评分与周期再估计细节见 `docs/backend/feedback-heat-scoring.md`。

## 1. 模块定位

Recommendation & Scoring 负责从去重后的候选中选出值得进入日报/周报/成稿流程的内容，
并按工作台的「内容导向」对候选做可解释的相关性排序。

输入：

```text
dedupe_groups active winner
news_items
data_sources / workspace_source_links
workspace label policy
workspace recommendation_policy（内容导向 rubric，本轮新增）
content_scorer config
feedback aggregates（源先验/主题权重周期再估计）
```

输出：

```text
recommendation_runs
recommendation_items（含粗排分、LLM 精排分、rubric 命中与理由）
selected candidates for generated_news / reports
explainable scoring fields
```

它不负责：

- 抓取 raw 和标准化 news，见 `docs/backend/data-ingestion-flow-storage-design.md`。
- 用户评论、点赞、评分的原始写入，见 `docs/backend/collaboration-notification-design.md`。
- 日报/周报采信和成稿，见 `docs/backend/report-renditions-design.md`。
- 生成模型 provider 实例配置与密钥，见 `docs/backend/generation-provider-design.md`。

## 2. 现状诚实评估与差距（2026-07 R1 审计）

设计必须基于真实现状。以下为代码级事实，不做粉饰。

### 2.1 现状事实（代码落点）

推荐主链路在 `backend/app/recommendations/service.py`（约 2000 行）：

1. **纯关键词/规则打分，无任何语义理解。** `_content_admission` 依赖文件顶部
   30 余组硬编码关键词元组（`TECHNICAL_TEXT_HINTS`、`HARDWARE_TEXT_HINTS`、
   `COMMERCIAL_TEXT_HINTS`、`BIOMEDICAL_NOISE_HINTS` 等），按命中计数加减分，
   再按阈值（85/60/44/30）切 P0/P1/P2/P3/R，后接一条 20 余分支的 `elif` 噪声降级链。
2. **推荐决策 0 次 LLM 参与。** LLM 只在候选选中后用于成稿
   （`generate_news_with_minimax`）。`config/scoring/content_scorer_v2.json` 中保留了
   旧系统（Tech Insight Loop）的 LLM 评分器 `prompt_template`（14 板块、专家路由、
   0-100 打分 rubric），但 `backend/app/scoring/content_scorer.py` 的 `ContentScorer`
   从不调用模型——该提示词是**死配置**，现实现只用了同文件里的
   source_tier/channel 打分表、`board_relevance_json` 元数据加权和 `noise_rules`
   正则惩罚。
3. **无 embedding、无向量、无相似度计算。** 去重只有 URL/标题硬去重
   （`00-system-design` §8），语义近重复（同一事件不同标题）无法识别。
4. **无学习闭环。** `_feedback_score` 只读 rating 均值 ×20 加 requirement
   `score_delta`；`_heat_score` 对每条候选逐条 live 查询 reactions/comments/ratings。
   `docs/backend/feedback-heat-scoring.md` 定义的 `news_heat_snapshots`、
   `source_score_snapshots` **两张表在代码中不存在**（无模型、无定时任务）。
   采信/驳回没有反哺任何源先验或主题权重。
5. **无用户导向输入。** 工作台只有 `label_policy` 关键词先验（`scoring_prior_keywords`），
   用户无法用自然语言描述"我想要什么/不要什么"；`planning_intel` 的口径全部硬编码在
   Python 常量里，改口径等于改代码。
6. **文档与代码公式已漂移。** 本文旧版 §5 写的公式是
   `quality*0.25 + topic*0.25 + freshness*0.15 + source*0.15 + heat*0.10 + feedback*0.10 + diversity`；
   代码实际是
   `admission*0.35 + quality*0.15 + topic*0.20 + freshness*0.10 + source*0.10 + heat*0.10 + feedback*0.05 + diversity`
   （R 封顶 25、P3 封顶 44）。本次大修以代码公式为粗排层事实源（§4.2），旧公式作废。
7. **排序不一致实据。**
   - Dashboard 头条候选先按"是否今日"再按 `final_score` 混排
     （`DashboardPage.vue` briefingHeadlines）。
   - 候选池 `GET /api/news-items/dedupe-groups` 默认 `sort=updated_desc`，
     不是分数序（`backend/app/api/routes/news.py`）。
   - 日报页在 `rating_count=0` 时渲染 "0.0 平均评分"（`DailyReportsPage.vue`
     averageRating），空指标当真值展示。

### 2.2 差距结论

对照用户批评逐条确认：

| 批评 | 事实核对 | 结论 |
|---|---|---|
| "不应该是 AI 做推荐吗" | 推荐决策链 0 次模型调用 | 成立。目标：LLM listwise 精排（§4.4） |
| "核心技术点根本没做到" | 无语义、无学习、无校准，仅关键词 | 成立。目标：三层管线（§4） |
| "挑选导向应该让用户描述，然后格式化成指标" | 无自然语言导向入口，口径硬编码 | 成立。目标：recommendation_policy + rubric 编译（§5） |
| "每个新闻格式化的时候，带着不同格式的 json 去格式化" | 成稿侧已有模板增量字段（renditions §10.4），推荐侧无 per-item rubric JSON | 推荐侧目标：精排输出结构化 rubric 命中 JSON（§4.4/§6） |

粗排规则层本身**不删除**：它是零成本的准入与降噪底座、预算耗尽时的降级路径，
以及"不配置导向时行为不变"的回归基线。

## 3. 业界与学术实践参照（方案依据）

### 3.1 两阶段/多阶段检索-排序架构

工业推荐与搜索系统的标准形态是"候选生成（召回/粗排）→ 精排"的多阶段漏斗
（如 YouTube 深度推荐的 candidate generation + ranking 两塔、搜索引擎的
BM25 召回 + 神经重排）。原则：**便宜的层砍量，贵的层提质**；每层只对上一层的
top-M 工作。本系统映射：现有规则打分即粗排层（对全量当日 winner，零模型成本），
LLM 只精排 top-M（默认 60），语义层作为可选增强插在中间。

### 3.2 LLM-as-ranker：pointwise / pairwise / listwise

- **Pointwise**：对单条打绝对分（如 G-Eval 用 rubric + 链式思考给 0-N 分）。
  优点是可解释、可并行、天然产出"相关分"；缺点是 LLM 打分跨请求不可比、
  分布漂移（miscalibration），需要校准手段。
- **Pairwise**：两两比较（PRP 等），排序质量高但调用量 O(n²)，成本不可接受。
- **Listwise**：一次给模型一个窗口的候选列表，输出窗口内排序或逐条分数。
  代表工作：RankGPT（滑动窗口 permutation generation，用重叠窗口把
  top 候选"冒泡"到前列）、RankLLaMA/RankZephyr（把 listwise 能力蒸馏进专用
  排序模型）。listwise 在窗口内做相对判断，稳定性优于孤立 pointwise。

**本系统采纳**：listwise 分窗 + 窗口内逐条 0-100 rubric 打分（listwise 上下文、
pointwise 输出的混合式）。理由：既要排序（相对判断在窗口内完成），又要
面向前端的可解释绝对分与理由（rubric 命中项）；窗口重叠锚点做跨窗校准（§4.4）。
不自训 ranker 模型：本系统体量（每工作台每日数百候选）远不到蒸馏专用模型的
成本临界点，直接用生成 provider 的指令模型。

### 3.3 Embedding 语义召回与去重增强

Bi-encoder embedding（余弦相似度）是语义近重复识别与主题聚类的标准手段；
新闻聚合产品（Google News 类）用向量聚类把"同一事件多来源"折叠成簇。
相对 SimHash/MinHash 字面指纹，embedding 能捕捉"不同标题同一事件"。
**本系统采纳**：作为可选 L2 层做去重增强（advisory 标记，不改 dedupe 事实）
与主题聚类（供多样性约束），接口预留、默认关闭（§4.3）——当前硬去重 +
source cap 已能压住大部分刷屏，语义层是增强不是前置依赖。

### 3.4 编辑方针作为评分 rubric

G-Eval 一类工作证明：把评估标准写成**结构化 rubric**（维度 + 权重 + 判据）比
自由文本 prompt 更稳定、更可复现；rubric 本身可版本化、可审计、可回归测试。
新闻编辑室的"编辑方针"（想要什么/不要什么/加分信号）天然适合编译成 rubric。
**本系统采纳**：用户自然语言导向 → LLM 编译 → 固定 schema 的 rubric JSON →
预览确认 → 版本化生效（§5）。旧系统 `content_scorer_v2.json` 的 prompt_template
证明这条路在本领域走通过（它就是一份 14 板块 rubric），本次把它从死配置升级为
"默认导向的编译产物"。

### 3.5 反馈信号的周期再估计（preference aggregation）

工业界对显式反馈（采信/驳回/点赞）的轻量用法是**周期性批量再估计先验**
（empirical-Bayes 风格：把源的历史采信率折算成源先验分），而非在线学习。
bandit/RLHF 一类在线方法需要训练基础设施与探索流量，本系统明确**不引入
在线训练依赖**。**本系统采纳**：每日 job 把 trailing 窗口内的采信/驳回/点赞
聚合成（a）源先验增量、（b）rubric 主题权重乘子，公式写死、幅度上限防振荡、
快照可回溯（§8）。

### 3.6 校准、分数漂移与位置偏差

LLM 打分的两类已知偏差必须在协议层规避：

- **跨请求不可比/分布漂移**：不同窗口、不同日期的绝对分基准会漂。对策：
  窗口重叠锚点线性校准（§4.4）＋ run 级分数分布监控（mean/std 记入 summary，
  与近 7 个 run 均值偏差超阈值只告警不整形）。
- **位置偏差**：列表靠前的候选易得高分。对策：窗口内候选顺序用确定性种子
  洗牌（seed = run_key + window_index），输出按 id 对齐而非按位置。

### 3.7 成本工程

通行做法：只对粗排 top-M 精排；prompt 压缩（摘要截断而非全文）；结果缓存
（同一 item 在同一 rubric 版本下的分数可复用）；预算闸门 + 降级路径（预算尽
即回退便宜层，服务不中断）。**本系统采纳**：全部四条，预算闸门复用
`generation_daily_usage` 机制的设计延伸（§9）。

## 4. 目标架构：三层推荐管线

### 4.1 总览

```text
dedupe winner (当日 active)
-> eligibility filter
-> L1 规则粗排（现状保留）：admission P0-P3/R + coarse_score
-> [L2 可选语义层：embedding 去重增强 + 主题聚类（默认关闭）]
-> L3 LLM 精排：粗排 top-M 按工作台 rubric listwise 分窗打分
-> final_score 融合（w_llm*llm + w_coarse*coarse；无 LLM 分时 = coarse）
-> diversity / source caps 选择
-> recommendation_items（全分数拆解 + rubric 命中 + 理由持久化）
-> generated_news / daily_report_items
```

运行顺序不可调换：L3 永远消费 L1 的产物；L3 失败/预算尽/未启用时管线在
L1 结果上直接完成（降级不是异常，是一等路径）。

### 4.2 L1 规则粗排（现状保留，行为基线）

L1 完全保留现状实现（`_score_candidate` + `_content_admission` +
`ContentScorer`），唯一变化是把它的输出**改名并持久化**为 `coarse_score`：

```text
coarse_score =
  admission_score * 0.35
  + quality_score * 0.15
  + topic_score  * 0.20
  + freshness_score * 0.10
  + source_score * 0.10
  + heat_score   * 0.10
  + feedback_score * 0.05
  + diversity_score
封顶规则：admission=R -> min(coarse_score, 25)；admission=P3 -> min(coarse_score, 44)
```

这是**代码现状公式**，取代本文旧版 §5 与 `feedback-heat-scoring.md` 旧 §7 的
建议公式（后者作废）。`_source_score` 在现状基础上叠加 §8 的源先验增量
`source_prior_delta`（无快照时增量为 0，行为与现状一致）。

**回归红线**：工作台未配置内容导向（`recommendation_policy` 缺省或
`llm_rerank_enabled=false`）时，`final_score = coarse_score`，
`recommendation_items` 的 rank 序列必须与现状实现逐位一致。

### 4.3 L2 可选语义层（接口预留，本期默认不启用）

**本期启用判定（锁定）**：默认不启用。仅当实例配置 `EMBEDDING_ENABLED=true`
且 provider 探活成功时链路才执行；未启用时零调用、零新表写入、对 L1/L3 无影响。
L2 不是 L3 的前置依赖。

接口（预留）：

```text
EmbeddingProvider.embed_texts(texts: list[str]) -> list[list[float]]
实例 env：EMBEDDING_ENABLED / EMBEDDING_BASE_URL / EMBEDDING_API_KEY(_REF)
        / EMBEDDING_MODEL / EMBEDDING_DIM
（openai_compatible /embeddings 端点；密钥规则与 GENERATION_API_KEY 完全一致，见 §17）
```

启用后的两个用途（都只产 advisory 信息，不改事实）：

1. **去重增强**：同工作台同 day_key 候选两两余弦相似度 ≥ 0.92 →
   在 `recommendation_items.scorer_breakdown_json.semantic_duplicate_of` 记录
   建议折叠对象（news_item_id）。**不修改 `dedupe_groups`**——"去重发生在
   news_items 之后、推荐之前"的硬约束不变，语义层只给编辑提示。
2. **主题聚类**：对 top-M 候选做简单聚类（阈值 0.85 的贪心聚簇），簇标签写入
   run `summary_json.semantic_clusters`，供多样性约束和前端"同题材"分组展示。

持久化（仅启用时）：`news_item_embeddings(news_item_id, model, dim,
vector_json, created_at)`，unique(news_item_id, model)。

### 4.4 L3 LLM 精排（listwise 分窗规范，写死）

**触发条件（全部满足才执行）**：

```text
recommendation_policy.llm_rerank_enabled = true
AND rubric_status = active（存在已确认的 compiled rubric）
AND generation provider usable（enabled 且 key 已配；按 resolve_generation_config
    统一解析链判定——凭据 → 实例 env，见 §17 D1 与 generation-provider-design §9.4）
AND 当日 rerank 预算未耗尽（§9）
```

任一不满足 → 本 run `summary_json.llm_rerank.status` 记
`disabled | skipped`（含 `skip_reason`），全部候选 `final_score = coarse_score`。

**输入集**：L1 完成后，取 `admission_level ∈ {P0, P1, P2}` 的候选按
`coarse_score` 降序取前 M 条。M 默认 60（`rerank_top_m`，取值 10..200）。
**R/P3 永不进精排**，其封顶规则保持不变。

**分窗（写死）**：窗口大小 W=12（`rerank_window_size`，6..20），锚点重叠 A=2，
步长 = W−A = 10。候选按 coarse_score 降序编号 c1..cM，窗口 k（k≥0）覆盖下标
`[k*(W-A), k*(W-A)+W-1]`，直到覆盖全部 M 条（末窗允许不满）。
M=60/W=12/A=2 时共 6 窗。相邻窗口共享 A 条锚点候选（前窗末 A 条 = 后窗首 A 条）。

**每窗一次模型调用**。prompt 组成（`rerank_prompt_v1`，版本号入库）：

```text
- 工作台 compiled rubric JSON（含 §8 再估计后的 effective topic weights）
- 窗口内每条候选的紧凑 JSON：
  {id(短句柄), title, summary(≤300字截断), source_name, published_at, admission_pool}
- 输出要求：严格 JSON 数组
  [{"id": "...", "relevance_score": 0-100 整数,
    "rubric_hits": ["topic/exclusion/boost 的 code"...],
    "reason": "一句话理由（≤60字）"}]
```

**位置偏差规避**：窗口内候选顺序以 `sha256(run_key + ":" + window_index)`
为种子做确定性洗牌后再入 prompt；解析输出按 id 对齐，不依赖输出顺序。
同一 run_key 重放必须产生相同的窗口划分与提交顺序（可复现性断言）。

**跨窗校准（写死）**：

```text
delta_0 = 0
窗口 k≥1：O = 锚点集合（在窗 k-1 得到校准分 s_prev、在窗 k 得到原始分 s_raw）
delta_k = mean(s_prev - s_raw)（O 为空或前窗失败时 delta_k = delta_{k-1}）
窗 k 内每条：calibrated = clamp(round(s_raw + delta_k), 0, 100)
锚点候选的最终 llm_relevance_score 取先到窗口（k-1）的校准值；后窗值只用于算 delta
```

**失败与重试（写死）**：输出 JSON 解析失败 / 候选 id 缺失或多余 → 同窗重试
1 次（重试计预算）；仍失败 → 该窗全部候选 `llm_rerank_status = window_failed`、
退回 coarse_score；失败窗口数 > 总窗数的 1/2 → 整个 run
`llm_rerank.status = failed`，全部候选退回 coarse_score。

**运行中预算耗尽**：已完成窗口的分数保留（`status = partial`），剩余窗口候选
退回 coarse_score，`skip_reason = budget_exhausted`。

**分数漂移监控**：run summary 记录 `llm_score_mean / llm_score_std`；
std < 5 记 `low_variance = true`；mean 与最近 7 个 scored run 的均值偏差 > 15
记 `drift_alert = true`。v1 只告警不整形（不做分布强制对齐），避免引入不可
解释的二次变换。

**结果缓存**：同一 `news_item_id` 在相同 `rubric_version + rerank_prompt_v1`
下 7 天内已有 `llm_rerank_status = scored` 的分数时，重跑 run 直接复用
（`llm_rerank_status = cached`，计 0 次调用）。

**边界**：L3 只产排序信号。它**不得**修改 `admission_level / admission_pool /
noise_types / reject_reasons`（准入归 L1），不得写 raw/news/dedupe，不得改变
"R/P3 默认不进日报"的规则。

### 4.5 与选择层的关系

选择（哪些进日报）与排序（怎么排）解耦：

- **选择**：保留现状算法——按准入优先级（P0/P1 先、P2 补位）+ source cap +
  pool cap + paper cap 逐条尝试（§15），但候选遍历顺序从
  `(admission_order, -coarse_score)` 改为 `(admission_order, -final_score)`。
- **排序**：所有展示序一律 `final_score` 降序（§7 排序一致性契约）。

## 5. 内容导向：recommendation_policy 与 rubric 编译

### 5.1 recommendation_policy 字段规格

存放：`workspaces.config_json.recommendation_policy`（与 label/feedback/report/
schedule/generation policy 同级）。契约：`config/contracts/recommendation_ranking.json`。

```json
{
  "guidance": {"want": "", "avoid": "", "boost": ""},
  "active_rubric": null,
  "rubric_version": 0,
  "rubric_status": "none",
  "llm_rerank_enabled": false,
  "rerank_top_m": 60,
  "rerank_window_size": 12,
  "daily_rerank_call_budget": 60,
  "fusion_weights": {"llm": 0.6, "coarse": 0.4},
  "semantic_layer_enabled": false
}
```

| 字段 | 取值 | 语义 |
|---|---|---|
| `guidance.want / avoid / boost` | 各 `str(≤2000)` | 用户自然语言导向三段：想要什么 / 不要什么 / 加分信号 |
| `active_rubric` | `null\|rubric JSON`（§5.2 schema） | 当前生效的编译产物；只能经 activate 动作写入 |
| `rubric_version` | `int ≥0` | 每次 activate +1；0 = 从未生效 |
| `rubric_status` | `none \| active` | 预览不落库，所以无中间态 |
| `llm_rerank_enabled` | bool，默认 `false` | 总开关；false 时 final_score=coarse_score（回归基线） |
| `rerank_top_m` | `int(10..200)`，默认 60 | 精排输入条数 |
| `rerank_window_size` | `int(6..20)`，默认 12 | listwise 窗口大小 |
| `daily_rerank_call_budget` | `null\|int(1..500)`，默认 60 | 每日精排模型调用上限（含重试）；null=不限（不建议） |
| `fusion_weights` | `{llm, coarse}` 均 `0..1` 且和 =1.0 | final_score 融合权重，默认 0.6/0.4 |
| `semantic_layer_enabled` | bool，默认 `false` | 工作台级 L2 开关（还需实例 EMBEDDING_ENABLED） |

校验规则：字段越界 422；`fusion_weights` 两权重和 ≠1.0（容差 0.001）422；
payload 命中 secret-like 检测（复用 `privacy.py`）422；写操作审计
`workspace.recommendation_policy.update`（before/after 快照）。

### 5.2 rubric schema（固定，schema_version=1）

编译产物必须严格符合以下 schema，多余键剥离、缺失键 422：

```json
{
  "schema_version": 1,
  "topics": [
    {"code": "inference_serving", "label": "推理与服务加速",
     "weight": 4.0, "keywords_hint": ["kv cache", "吞吐"]}
  ],
  "exclusions": [
    {"code": "no_funding_news", "rule": "融资/财报/股价类纯商业新闻", "severity": "hard"}
  ],
  "boost_signals": [
    {"code": "first_party_benchmark", "description": "一手 benchmark 或架构细节", "bonus": 8}
  ],
  "scoring_dimensions": [
    {"code": "relevance", "weight": 0.5},
    {"code": "evidence", "weight": 0.2},
    {"code": "impact", "weight": 0.2},
    {"code": "timeliness", "weight": 0.1}
  ],
  "language": "zh",
  "source_guidance_fingerprint": "sha256:..."
}
```

| 约束 | 规则 |
|---|---|
| `topics` | 3..12 项；`code` 匹配 `^[a-z0-9_]{2,32}$` 且全局唯一；`weight` 0.0..5.0 |
| `exclusions` | 0..10 项；`severity=hard` 命中时该条 `llm_relevance_score` 封顶 20（不改 admission） |
| `boost_signals` | 0..8 项；`bonus` 1..10（提示模型加分，非算术外加） |
| `scoring_dimensions` | 必含 `relevance`；code 枚举 `relevance/evidence/impact/timeliness/actionability`；weight 和 =1.0 |
| `source_guidance_fingerprint` | 编译输入指纹，保证产物可溯源 |

### 5.3 编译动作与幂等预览

```text
POST /api/workspaces/{code}/recommendation-policy/compile-rubric   workspace admin+
body: {"guidance": {...}}（缺省取已存 policy.guidance）
```

流程：

1. 计算 `fingerprint = sha256(canonical_json(guidance) + schema_version + compile_prompt_v1)`。
2. 查 `recommendation_rubric_compiles` 缓存：命中 → 直接返回缓存产物，
   **零模型调用**（幂等预览）。
3. 未命中 → 1 次模型调用（记账 `purpose=rubric_compile`，日固定上限 20 次/工作台，
   与 rerank 预算相互独立）把三段导向编译为 §5.2 schema 的 rubric；schema 校验
   失败重试 1 次，仍失败返回 502 与原始错误摘要。
4. 成功产物写入 `recommendation_rubric_compiles`（见 §10），响应：

```json
{"rubric": {...}, "fingerprint": "sha256:...", "persistence": "not_persisted",
 "cached": false}
```

编译**不改变** `active_rubric / rubric_version`——预览确认前对推荐零影响。

### 5.4 生效、版本化与审计

```text
POST /api/workspaces/{code}/recommendation-policy/activate-rubric   workspace admin+
body: {"fingerprint": "sha256:..."}
```

- fingerprint 必须命中本工作台 7 天内的编译记录，否则 422（防陈旧产物生效）。
- 生效：`active_rubric = 编译产物`，`rubric_version += 1`，`rubric_status = active`。
- 审计：`workspace.recommendation_rubric.activate`，before/after 记
  `{rubric_version, fingerprint}`；配合 `recommendation_rubric_compiles` 表可完整
  回溯"谁在何时用什么导向编译出什么 rubric 并何时生效"。
- 前端行为（设计级）：工作台推荐/报告设置新增「内容导向」卡——三段文本框 →
  「编译预览」展示结构化 rubric（主题权重表 / 排除规则 / 评分维度）→
  「确认生效」；卡上常显当前版本号与最近生效时间。页面规格落
  `docs/product/page-specs/frontend-page-specs.md`（产品文档轮次承接）。

### 5.5 planning_intel 默认导向（行为兼容基线）

现状硬编码口径转写为默认 guidance 文本（转写内容锁定在契约
`default_guidance.planning_intel`）：

- `want`：AI 工程能力与基础设施、模型训练/推理与服务加速、智能体平台、
  AI/通算硬件与芯片、核心网与通信系统架构、标准与产业联盟进展、厂商技术路线。
- `avoid`：融资/财报/股价等纯商业新闻、消费电子与个人数码、活动报名与营销
  宣传、航天火箭等离题工程、生物医学与纯学术离题论文、法律/版权元讨论、
  标题党与未经证实爆料。
- `boost`：一手技术证据（论文/官方工程博客/benchmark）、架构与成本/能耗/性能
  量化数据、开源可复现产物、厂商官方技术白皮书。

其编译产物（默认 rubric）在实施期生成并人工 review 后固化到
`config/scoring/rubrics/planning_intel_default.json`，供「一键采用默认导向」。
**回归红线**：默认 `llm_rerank_enabled=false`，因此 planning_intel 不显式开启
导向时，排序与现状纯粗排逐位一致；开启导向后 L1 准入与噪声口径也不变
（rubric 只影响 L3 排序），基线回归测试固定一组 fixture 断言 rank 序列。

## 6. final_score 融合与可解释字段

融合公式（权重可配，默认写死 0.6/0.4）：

```text
候选有校准后 llm_relevance_score（status=scored/cached）时：
  final_score = round(w_llm * llm_relevance_score + w_coarse * coarse_score, 2)
  默认 w_llm=0.6, w_coarse=0.4（fusion_weights，和必须为 1.0）
否则（未启用/降级/未进 top-M/窗口失败）：
  final_score = coarse_score
```

融合后不重算准入：`admission_level` 与 R≤25/P3≤44 封顶只作用于 coarse_score
（R/P3 不进精排，天然不受融合影响）。

可解释字段（API 与前端必须展示）：

```text
coarse_score               粗排分（回归基线可见）
llm_relevance_score        LLM 精排 0-100（可空）
llm_rerank_status          not_run / scored / cached / window_failed / skipped / disabled
llm_rerank_reason          一句话理由（≤60字，可空）
rubric_hits_json           命中的 rubric code 列表（topic/exclusion/boost）
rubric_version             打分时使用的 rubric 版本
final_score                融合后总分（一切排序的唯一依据）
recommendation_reason      现状拼接理由保留，追加 "llm_rerank=<status>"
```

## 7. 排序一致性契约

**唯一排序键：`final_score` 降序**（并列时按 `news_item_id` 升序稳定排序）。
以下展示面全部适用，写入契约并由前端 spec 断言看护：

| 展示面 | 集合定义 | 排序 |
|---|---|---|
| Dashboard 今日头条候选 | 最新 run 中 `day_key=今日` 且 admission ∈ P0/P1/P2 的候选 top 6 | final_score desc（废除现状 today-first 混排——非今日候选直接不入集合） |
| 候选池（/news dedupe-groups） | 当前过滤集 | 默认 `sort=score_desc`（final_score desc）；其他 sort 仅显式选择 |
| 日报选择（draft 条目 sort_order） | 本次 run selected 集合 | sort_order 按 final_score desc 赋值 |
| 今日速览（Dashboard 全页候选类卡片） | 各卡片集合 | final_score desc |
| 推荐 run 详情 items | run 全量 | rank = final_score desc 的序号（R/P3 沉底由分数封顶自然保证） |

**空指标规则**：无数据的评分类指标不得以 0 值展示——`rating_count=0` 时
"平均评分"整项隐藏（现状 "0.0 平均评分" 为违例）；`final_score` 缺失
（历史数据）时显示"未评分"而非 0.0。前端看护断言进对应 Page.spec。

## 8. 反馈反哺：源先验与主题权重周期再估计

原始反馈（reactions/ratings/comments/editorial_actions）归 Collaboration 模块；
推荐层只消费聚合产物。公式与幅度上限写死，防振荡；快照可回溯。
细节附录：`docs/backend/feedback-heat-scoring.md` §10。

**每日 job**：`feedback_reaggregate_daily`（scheduler 注册，每日 02:00
Asia/Shanghai，处理 trailing 14 天窗口，幂等：同 day_key 重跑覆盖当日快照）。

### 8.1 源先验增量（进 L1 `_source_score`）

对每个 (workspace, data_source)，统计 trailing 14 天内曾进入推荐
（recommendation_items 存在）的条目：

```text
adopt_rate  = 被采信条目数(adoption_status=2 且日报已发布) / max(1, 推荐条目数)
reject_rate = 被剔除条目数(adoption_status=3)              / max(1, 推荐条目数)
like_rate   = min(1.0, 点赞数 / max(1, 推荐条目数))
source_prior_delta = clamp(8*adopt_rate - 6*reject_rate + 2*like_rate, -6.0, +6.0)
```

写入 `source_score_snapshots`（window=14d，含各计数与 delta，见 §10）。
L1 `_source_score` 读取最新快照：`base += source_prior_delta`，叠加后仍
clamp 0..100。**每日全量重估、非累加**——delta 天然有界，不会漂移发散；
无快照时 delta=0，行为与现状一致。

### 8.2 主题权重乘子（进 L3 rerank prompt）

仅对 `rubric_status=active` 的工作台。对 rubric 每个 topic code t，统计
trailing 14 天内 `rubric_hits_json` 含 t 的条目：

```text
pos_t = 其中被采信的条目数
neg_t = 其中被剔除的条目数
effective_weight_t = clamp(
    authored_weight_t * (1 + 0.1 * (pos_t - neg_t) / max(5, pos_t + neg_t)),
    0.5 * authored_weight_t,
    1.5 * authored_weight_t)
```

- 单次再估计幅度 ≤ ±10%，累计钳制在 authored weight 的 [0.5, 1.5] 倍——
  用户写的导向永远是锚，反馈只微调。
- 写入 `rubric_topic_priors` 快照（§10）；rerank prompt 使用 effective weight，
  `active_rubric` 里的 authored weight **永不被改写**。
- `rubric_version` 变更时统计清零重来。

### 8.3 保留的现状路径与禁止事项

需求结论反馈（`requirement.feedback_to_recommendation` → `feedback_score`）
与热度/评分进 L1 的现状路径保持不变。禁止：推荐模块修改原始评论/通知状态/
Strategy Loop 状态；把点赞逐条当通知；把反馈直接写回 rubric authored 字段。

### 8.4 周/月反馈回哺工作流（延伸层，2026-07-08 定稿）

> 状态：`design_final_pending_implementation`（实施工作包 WP4-G）。
> 事实源：`docs/backend/feedback-heat-scoring.md` §11-§18；机器契约：
> `config/contracts/recommendation_ranking.json` `feedback_workflow`。

在本节每日再估计（§8.1-§8.3，WP4-A 已实现，不动）之上追加周/月两级节拍，
把"采纳/不采纳"升级为完整反馈工作流。本节只记边界，细节归事实源：

- **周 job `feedback_weekly_rollup`**（周一 03:00，接入方式复用
  `feedback_reaggregate_daily` 的实例级固定时刻 + 心跳幂等模式）：产出周期
  评估快照 `feedback_rollups`（precision@K 对照采信、rerank 相对粗排
  uplift、覆盖多样性、位次去偏后的采信率、低数据源清单）、源分层升降建议
  （advisory，不改 tier/enabled）、rubric 修订提案
  `rubric_revision_proposals`（LLM 从本周采信 vs 驳回代表样本生成 diff 提案，
  `pending_review` 入库，走 `purpose=feedback_rollup` 新预算桶，固定 4 次/
  工作台/日）。
- **月 job `feedback_monthly_review`**（每月 1 日 03:30，零 LLM 调用）：长期
  漂移检测、失效源清理建议（advisory）、月度评估汇总。
- **人审硬门**：提案 accept 由服务端原子登记 compile 记录并走本文档 §5.4 的
  既有 activate 版本化链（`rubric_version += 1`、同一审计动作）；authored
  导向永不被自动改写——§8.2 的"authored weight 永不被改写"约束原样覆盖
  延伸层。
- **零直接改分**：周/月层不写 `source_score_snapshots` /
  `rubric_topic_priors` / `recommendation_items`；进分数的路径仍只有每日
  job 的两个快照，§8.1/§8.2 公式与幅度上限不变。
- **探索保留**：`recommendation_policy.feedback_workflow.exploration_epsilon`
  （0..0.1，默认 0.0）在选择层为低数据源保留至多每 run 1 条探索位（确定性
  抽签、不改准入、不绕 caps）；默认关闭，缺省行为与现状逐位一致——§18
  断言 1 的回归红线原样覆盖。

## 9. 预算闸门、成本工程与降级路径

### 9.1 预算记账（generation_daily_usage 机制延伸）

复用既有 `generation_daily_usage` 表与 `GenerationRuntime.try_acquire_call()`
闸门语义（`docs/backend/generation-provider-design.md` §3.2），延伸为按用途分桶：

```text
generation_daily_usage 新增列 purpose: String(24) 默认 'generation'
unique 约束改为 (workspace_code, day_key, purpose)
purpose 枚举：generation | rerank | rubric_compile
迁移：存量行回填 purpose='generation'
```

三桶配额互不挤占：

| purpose | 配额来源 | 默认 |
|---|---|---|
| `generation` | `generation_policy.daily_generation_budget`（现状不变） | null 不限 |
| `rerank` | `recommendation_policy.daily_rerank_call_budget` | 60 |
| `rubric_compile` | 固定 20 次/工作台/日（不可配，防滥用） | 20 |

`RerankRuntime`（GenerationRuntime 的同构延伸）：`try_acquire_call()` 在
purpose=rerank 桶上判定+登记；耗尽时 `budget_exhausted_total += 1` 并由调用方
走降级。成功+失败（含重试）都计数——与 generation 口径一致。

### 9.2 成本估算（默认参数）

```text
每 run：窗口 6 个 + 重试上限 6 = 最多 12 次调用
每窗 prompt ≈ rubric ~0.8K + 12 条候选 ~4-5K ≈ 6K tokens 入 / ~1.2K 出
每 run ≈ ≤40K tokens 入 / ≤8K 出；默认预算 60 次/日 ≈ 5 个全量 run
rubric 编译：1 次/编译，缓存命中 0 次
```

结果缓存（§4.4）使同日重跑边际成本趋近 0。

### 9.3 降级路径总表

| 场景 | 行为 | run summary 标记 |
|---|---|---|
| policy 缺省 / llm_rerank_enabled=false | 纯粗排，final=coarse | `llm_rerank.status=disabled` |
| rubric 未 activate | 同上 | `disabled`（reason=no_active_rubric） |
| provider 不可用（未启用/无 key） | 零外呼，纯粗排 | `skipped`（reason=provider_unavailable） |
| run 开始时预算已尽 | 零外呼，纯粗排 | `skipped`（reason=budget_exhausted） |
| run 中途预算尽 | 已 scored 窗口保留，其余退 coarse | `partial`（reason=budget_exhausted） |
| 单窗解析失败（重试后） | 该窗退 coarse | `scored/partial` + `windows_failed` 计数 |
| 失败窗 > 1/2 | 全量退 coarse | `failed` |
| 编译失败（schema 两次不合法） | 502，active rubric 不变 | 不涉及 run |

所有降级都**不阻断**推荐 run：日报草稿照常产出，只是排序退回规则层。

## 10. 数据模型增量

一次迁移完成（Alembic 单版本）：

```text
generation_daily_usage
  + purpose            String(24)  default 'generation'  （回填存量行）
  ~ unique (workspace_code, day_key) -> (workspace_code, day_key, purpose)

recommendation_items
  + coarse_score          Float    default 0.0   （回填：存量行 = final_score）
  + llm_relevance_score   Float    nullable
  + llm_rerank_status     String(24) default 'not_run'
                          枚举 not_run/scored/cached/window_failed/skipped/disabled
  + llm_rerank_reason     Text     default ''
  + rubric_hits_json      JSON     default []
  + rubric_version        Integer  default 0

recommendation_runs.summary_json 增键（无迁移，JSON）：
  llm_rerank: {status, skip_reason, windows_total, windows_failed,
               calls_used, rubric_version, llm_score_mean, llm_score_std,
               low_variance, drift_alert}

recommendation_rubric_compiles（新表）
  id, workspace_code(idx), fingerprint(unique with workspace_code),
  guidance_json, rubric_json, prompt_version, model_called(bool),
  created_by, created_at

source_score_snapshots（新表，落地 feedback-heat-scoring §8 的表并扩展）
  id, workspace_code(idx), data_source_id(idx), window('14d'),
  recommended_count, adopted_count, rejected_count, like_count,
  adopt_rate, reject_rate, like_rate, source_prior_delta,
  day_key, computed_at；unique(workspace_code, data_source_id, window, day_key)

rubric_topic_priors（新表）
  id, workspace_code(idx), rubric_version, topic_code,
  pos_count, neg_count, effective_weight, day_key, computed_at
  unique(workspace_code, rubric_version, topic_code, day_key)

news_item_embeddings（新表，仅 L2 启用时写入）
  id, news_item_id(FK), model, dim, vector_json, created_at
  unique(news_item_id, model)

workspaces.config_json.recommendation_policy（无迁移，JSON policy，§5.1）
```

## 11. API 目标态

现状已实现接口保持不变；本轮增量在末段。

```text
POST /api/recommendation/runs
GET  /api/recommendation/runs
GET  /api/recommendation/runs/{id}
GET  /api/recommendation/runs/{id}/items
GET  /api/recommendation/scorer-policy
POST /api/recommendation/scorer-preview
POST /api/daily-reports/bulk-adopt-from-candidates
POST /api/daily-reports/bulk-reject-from-candidates
POST /api/pipeline/daily-runs

--- 本轮增量（design_final_pending_implementation） ---
GET   /api/workspaces/{code}/recommendation-policy          workspace viewer+
PATCH /api/workspaces/{code}/recommendation-policy          workspace admin+ 或 super_admin
POST  /api/workspaces/{code}/recommendation-policy/compile-rubric    workspace admin+
POST  /api/workspaces/{code}/recommendation-policy/activate-rubric   workspace admin+
```

`POST /api/recommendation/runs` 参数：

```text
workspace_code
domain_code
day_key
limit
source_daily_limit
include_admission_levels
create_daily_draft
```

返回必须包含：

- run 状态、候选数、选中数。
- 每条 item 的分数拆解（含 §6 全部可解释字段）。
- 被拒或未选原因。
- `summary_json.llm_rerank` 块（§10）。
- 最新关联日报 trace：`day_key`、`report_status`、`adoption_status`、`daily_report_item_id`。

`GET recommendation-policy` 响应附只读 resolved 状态（仿 generation-policy）：

```json
{
  "policy": {"...": "..."},
  "resolved": {
    "llm_rerank_available": true,
    "provider_usable": true,
    "rerank_calls_used_today": 12,
    "rerank_budget": 60,
    "active_rubric_version": 3,
    "semantic_layer_available": false
  }
}
```

`GET /api/recommendation/scorer-policy` 是评分器运营页 v1 的只读入口。它按
`workspace_code` 做 viewer gate，只返回当前生效配置的运营摘要：配置版本、阈值、日报/周报
准入层、权重 TopN、主题 TopN、source tier/channel 摘要、噪声规则数量、直接拒绝噪声类型和
公式说明。它不返回完整关键词表，不提供在线编辑或重算。

`POST /api/recommendation/scorer-preview` 是评分器运营页 v1 的只读校验入口。它按
`workspace_code` 做 admin gate，接收单条临时候选的标题、摘要、源类型、源等级、渠道、源分、
来源标签、板块相关性和 freshness 分，复用推荐 run 中同一条 content admission scorer 路径返回
准入等级、准入分、候选池、日报可入选标记、噪声、拒绝原因、正向理由、专家路由和分数拆解。
该接口必须返回 `persistence=not_persisted`，不得创建 `recommendation_runs`、
`recommendation_items`、`generated_news`、`daily_report_items`、`editorial_actions`、
`raw_items` 或 `news_items`。它不是配置编辑器，也不是批量重算入口。

`/recommendations` 的观察池复核 v1 不新增独立状态机。页面从当前推荐 run 中筛出
`selected=false` 且 `admission_level in (P2, P3)` 的候选，调用日报模块既有
`POST /api/daily-reports/bulk-adopt-from-candidates` 或
`POST /api/daily-reports/bulk-reject-from-candidates` 写入日报草稿采信/剔除。写入必须沿
`dedupe_group -> recommendation_item -> generated_news -> daily_report_item` 链路完成，不能绕过推荐链
直接从任意 `news_items` 创建日报条目。复核后 `GET /api/recommendation/runs/{id}` 返回每条
`recommendation_item.daily_report` trace，前端据此显示"已采信/已剔除/未处理"。

## 12. 准入层（保留）

准入层先回答"这条是否值得进入候选池/推荐池"，再计算排序分。准入完全归 L1，
LLM 精排不得改变准入结论。

| 等级 | 含义 | 默认处理 |
|---|---|---|
| P0 | 强相关、强时效、强价值 | 优先推荐；进精排 |
| P1 | 明确相关、有日报价值 | 可推荐；进精排 |
| P2 | 有价值但需观察 | 观察池；进精排（补位规则见 §15） |
| P3 | 弱相关或信息不完整 | 默认不选；不进精排；final ≤44 |
| R | 噪声、重复低质、不符合范围 | 拒绝；不进精排；final ≤25 |

准入结果必须持久化，不能只在日志里。

## 13. 评分配置

L1 评分配置来源不变：`config/scoring/content_scorer_v2.json`（阈值、source
tier/channel、topic weights、noise rules、专家路由）。其中 `prompt_template`
字段为旧系统遗留，现实现不消费；其口径已被 §5.5 默认导向承接，实施期从该
文件移除或标注 `deprecated`。

新增配置面：

```text
config/scoring/rubrics/planning_intel_default.json   默认导向编译产物（实施期固化）
workspaces.config_json.recommendation_policy         工作台导向与精排参数（§5.1）
```

新增评分字段时必须同步：`recommendation_items` schema、API response、前端
推荐页/候选池解释字段、测试 fixture、`config/contracts/recommendation_ranking.json`。

## 14. 工作台与标签策略

推荐必须读取当前工作台策略：

```text
workspaces.config_json.label_policy
workspaces.config_json.recommendation_policy
workspace_source_links.source_weight
workspace_source_links.daily_limit
```

规则：

- `planning_intel` 使用 AI 十分类和公司 SQL 兼容格式；rubric 与 topic code
  **不写入** `generated_news.category`，成品新闻一级标签仍只来自
  `config/taxonomy/news_categories.json` 十分类。
- 新工作台可以使用自己的标签策略与内容导向。
- 数据源方向标签只作为先验，不写入 `generated_news.category`。
- 推荐不能把工作台 A 的策略（含 rubric）污染到工作台 B。

## 15. source cap 与多样性

推荐不能被单一来源或单一主题刷屏。应支持：

```text
source_daily_limit
source_type caps
primary_label diversity
secondary_label diversity
duplicate group winner only
[L2 启用时] semantic cluster caps（同簇入选上限，advisory）
```

当一个高分候选因多样性或日限被压下，`recommendation_items` 必须记录原因，
便于前端解释。选择算法保留现状（准入优先级 + caps），遍历顺序按 final_score
降序（§4.5）。

## 16. 与流水线的关系

完整日更流水线：

```text
ingestion -> normalize -> dedupe
-> recommendation (L1 粗排 -> [L2] -> L3 精排 -> 融合 -> 选择)
-> generation -> daily report draft
```

推荐层必须可单独重跑，也必须能被 `POST /api/pipeline/daily-runs` 编排调用。

约束：

- 已发布日报不可被重跑覆盖。
- 推荐 run 不应修改 raw/news/dedupe 事实。
- 推荐 run 可以读取最新 feedback aggregate 与 rubric，但结果要快照化保存
  （item 上持久化 rubric_version 与全部分数）。
- 精排调用失败/预算尽不阻断流水线（§9.3）。

## 17. 密钥与安全边界（决策变更记录）

本轮涉及密钥面的决策变更与风险缓解，显式记录：

| 决策 | 内容 | 风险与缓解 |
|---|---|---|
| D1 精排/编译复用生成 provider 解析链 | L3 与 rubric 编译一律复用生成 provider 的**统一解析链** `resolve_generation_config`——工作台 `generation_policy.credential_id` 选中的落库凭据 → 实例 `GENERATION_*` env（优先级见 `docs/backend/generation-provider-design.md` §9.4 与 `config/contracts/llm_providers.json` `resolution_priority`；D-2026-07-08-KEY 前的实例上退化为纯 env 链）。**推荐模块自身不新增任何密钥字段**；key 明文永不进 `recommendation_policy`、Git、同步包或 API 响应（落库密钥仅允许 `llm_provider_credentials` 的 Fernet 密文形态，归 R2 治理） | 无新增密钥面；预算分桶（§9.1）防止精排流量挤占生成配额；凭据被禁用/解密失败按 `key_source=credential_missing` 视作 provider 不可用，走 §9.3 `skipped(provider_unavailable)` 降级 |
| D2 L2 embedding 独立 env（仅启用时存在） | `EMBEDDING_API_KEY(_REF)` 为新增实例级 env，规则与 `GENERATION_API_KEY` 完全一致：credential_ref（env:VAR\|file:/path）、启动 fail-fast（ENABLED=true 而 key 空则拒绝启动）、privacy redaction 覆盖 | 新增一处密钥面但默认关闭；实施时同步 `config/contracts/deployment_modes.json` `related_env` 与 startup_failfast_rules、`docs/backend/security-secrets-privacy-design.md` |
| D3 guidance 文本边界 | `guidance` 是业务导向不是密钥，但 PATCH/compile payload 必须过 secret-like 检测（误贴 key 一律 422）；guidance 与 rubric 随 workspace config 留在本环境，不进入公司 SQL 与导出 | 防误存密钥；导向文本可能含内部关注点，同步策略沿用 workspace config 现行边界（intranet pull-only 下不回传公网） |
| D4 候选内容出境面 | 精排把候选标题/摘要（≤300 字截断）发送给生成 provider——与现状成稿链路的出境面相同，不扩大数据类别；raw 全文不出境 | 与 generation 同一信任边界；intranet 形态禁采集时无候选可精排，天然关闭 |

## 18. 验收断言

与 `config/contracts/recommendation_ranking.json` `acceptance_assertions` 一一对应：

1. **无导向时与现状排序一致（回归红线）**：`recommendation_policy` 缺省或
   `llm_rerank_enabled=false` 时，固定 fixture 下 `recommendation_items` 的
   rank 序列与 final_score 与纯粗排现状实现逐位一致。
2. **预算耗尽降级**：rerank 预算耗尽后 run 正常完成，`llm_rerank.status ∈
   {skipped, partial}` 且 `skip_reason=budget_exhausted`，未精排候选
   `final_score = coarse_score`。
3. **provider 不可用降级**：provider 未启用/无 key 时零外呼，
   `llm_rerank.status=skipped(provider_unavailable)`，run 正常完成。
4. **rubric 编译幂等预览**：相同 guidance 连续编译两次返回相同 fingerprint 与
   rubric，第二次零模型调用（缓存命中），且 `active_rubric / rubric_version` 不变。
5. **生效版本化与审计**：activate 后 `rubric_version+1`，`audit_logs` 记
   `workspace.recommendation_rubric.activate`（before/after 版本与 fingerprint）；
   过期/未知 fingerprint 422。
6. **分窗确定可复现**：同一 run_key 下窗口划分、锚点与窗口内洗牌顺序完全可复现
   （seed = sha256(run_key + window_index)）。
7. **窗口失败降级**：单窗重试 1 次后仍失败 → 该窗候选
   `llm_rerank_status=window_failed` 且退回 coarse；失败窗 >1/2 → 整 run
   `llm_rerank.status=failed` 全量退回。
8. **融合公式**：scored 候选 `final_score = round(0.6*llm + 0.4*coarse, 2)`
   （默认权重）；`fusion_weights` 和 ≠1.0 的 PATCH 422。
9. **排序一致性**：Dashboard 头条候选 / 候选池默认排序 / 日报 draft
   sort_order / 今日速览一律 final_score 降序；前端 spec 断言看护。
10. **空指标隐藏**：`rating_count=0` 时不渲染"0.0 平均评分"；final_score 缺失
    显示"未评分"而非 0.0。
11. **精排不改准入**：L3 不改变 `admission_level/admission_pool/noise_types/
    reject_reasons`，不写 raw/news/dedupe；R/P3 不进精排输入集且封顶保持。
12. **反哺有界**：`source_prior_delta ∈ [-6, +6]`；topic
    `effective_weight ∈ [0.5w, 1.5w]`；每日全量重估非累加；authored rubric
    权重永不被改写。
13. **预算分桶互不挤占**：精排调用计 `generation_daily_usage(purpose=rerank)`，
    不增加 `purpose=generation` 计数，反之亦然。
14. **密钥边界**：recommendation-policy 各接口 payload 命中 secret-like 检测
    422；响应不含任何 key；rerank/compile 无新增密钥字段。
15. **既有验收保持**：推荐 run 只处理目标日 active winner；准入等级、分数拆解、
    拒绝原因持久化；候选可追溯 `news_items -> raw_items -> data_sources`；
    source daily limit 生效并记录未选原因；反馈聚合变化后新 run 分数可变、
    旧 run 快照不被覆盖；不同工作台策略互不污染；scorer-policy/scorer-preview/
    观察池复核 v1 行为不变。

## 19. 当前设计缺口

| 缺口 | 判定标准 |
|---|---|
| 三层管线与内容导向为设计态（design_final_pending_implementation） | 实施完成后按 §18 断言全绿，capability-map 更新证据 |
| L2 语义层本期默认关闭 | 启用判定与接口已锁定（§4.3）；启用评审需单独决策 |
| LLM 分数分布 v1 只监控不整形 | drift_alert/low_variance 进 run summary；整形方案待运行数据 |
| 评分配置运营视图仍需深化 | 只读策略摘要 v1、单条 scorer preview v1、P2/P3 观察池复核 v1 已完成；后续补策略编辑、批量重算影响和配置变更审计 |
| P2/P3 观察池运营仍需深化 | 已有筛选、复核、采信/剔除入口；后续补复核备注、抽检队列和批量重算联动 |
| news_heat_snapshots 仍未落地 | 现状 heat live 计算；快照化随 feedback_reaggregate_daily 实施一并处理 |
| 生产抽检机制不足 | 推荐 run 抽样验收分数、精排理由、拒绝原因和最终采信结果 |
