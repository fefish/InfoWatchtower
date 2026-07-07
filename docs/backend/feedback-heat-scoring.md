# 用户反馈、热度评分与反馈回哺工作流

本文档定义点赞、评论、用户评分、新闻热度、来源评分如何存储和进入推荐闭环，
并且是**反馈回哺工作流**（周/月节拍 rollup、离线评估指标、rubric 修订提案、
低数据源探索保留）的目标态事实源（§11-§18，2026-07-08 定稿并于同日随
WP4-G 实现，状态 `implemented`）。

当前推荐准入、推荐 run、分数解释和候选选择的目标态事实源是
`docs/backend/recommendation-scoring-design.md`（其 §8 每日再估计层已随 WP4-A
实现，本文 §10 为其公式附录；§8.4 为周/月延伸层的指路节）。机器契约：
`config/contracts/recommendation_ranking.json` `feedback_reestimation`（每日层，
已实现）与 `feedback_workflow`（周/月层，本文 §11-§18 的机器形）。
评论/通知原始协作流见 `docs/backend/collaboration-notification-design.md`。

## 1. 反馈对象

反馈可以挂在不同层级：

- `news_item`：针对原始/标准新闻本身。
- `daily_report_item`：针对日报中的展示条目。
- `weekly_report_item`：针对周报条目。
- `topic`：针对热点专题。

第一阶段重点支持：

- 日报新闻点赞。
- 日报新闻评分。
- 日报新闻评论和楼中楼回复。
- 管理员采信/剔除作为强反馈。

## 2. 点赞与收藏

表：`reactions`

```text
id
target_type              news_item / daily_report_item / weekly_report_item / comment
target_id
user_id
reaction_type            like / bookmark / useful / not_useful
created_at
updated_at
```

约束：

```text
unique(target_type, target_id, user_id, reaction_type)
```

说明：

- 点赞和收藏是轻量反馈。
- `not_useful` 可用于负反馈，但第一阶段可以只做 `like/bookmark`。

## 3. 评分

表：`ratings`

```text
id
target_type              news_item / daily_report_item / weekly_report_item
target_id
user_id
score                   1-5 或 1-10，第一阶段建议 1-5
reason
created_at
updated_at
```

约束：

```text
unique(target_type, target_id, user_id)
```

评分含义：

- 用户认为这条新闻对规划部是否重要。
- 不等于内容写得好不好；内容质量可后续单独拆分。

## 4. 评论与楼中楼

表：`comments`

```text
id
target_type              news_item / daily_report_item / weekly_report_item / topic / task
target_id
parent_id                null 表示一级评论；非 null 表示回复
root_id                  一级评论 id，便于楼中楼查询
user_id
content
status                   active / hidden / deleted
created_at
updated_at
```

说明：

- `parent_id` 支持回复任意评论。
- `root_id` 用于快速取一个讨论串。
- 删除建议软删除，保留审计。

## 5. 管理员采信反馈

管理员行为也是反馈，而且权重应高于普通用户点击。

表：`editorial_actions`

```text
id
target_type              news_item / daily_report_item / weekly_report_item
target_id
user_id
action_type              adopt / reject / promote / demote / lock / edit
reason
created_at
```

典型含义：

- `adopt`：采纳进日报/周报，强正反馈。
- `reject`：明确剔除，强负反馈。
- `promote`：手动上调优先级。
- `demote`：手动降权。

## 6. 新闻热度评分

热度是聚合指标，不建议每次查询实时算，应定时生成快照。

表：`news_heat_snapshots`

```text
id
news_item_id
window                  1d / 7d / 30d
like_count
bookmark_count
comment_count
rating_count
rating_avg
editorial_adopt_count
editorial_reject_count
view_count
heat_score
computed_at
```

第一阶段热度公式可以简单、可解释：

```text
heat_score =
  like_count * 1.0
  + bookmark_count * 1.5
  + comment_count * 2.0
  + rating_count * rating_avg * 1.2
  + editorial_adopt_count * 8.0
  - editorial_reject_count * 5.0
  + log(1 + view_count) * 0.5
```

再加时间衰减：

```text
decayed_heat_score = heat_score * exp(-age_hours / half_life_hours)
```

第一阶段建议：

- 日报推荐 half-life：48 小时。
- 周报候选 half-life：168 小时。

> 现状（2026-07 R1 审计）：`news_heat_snapshots` 与 `source_score_snapshots`
> 两张表尚未落地——当前实现对每条候选 live 查询 reactions/comments/ratings
> （`backend/app/recommendations/service.py` `_heat_score`/`_feedback_score`）。
> 快照化随 `feedback_reaggregate_daily` job（§10）一并实施。

## 7. 推荐评分

推荐评分表：`recommendation_items`

```text
quality_score
topic_score
freshness_score
feedback_score
diversity_score
source_score
heat_score
coarse_score              粗排分（2026-07 R1 新增）
llm_relevance_score       LLM 精排分（可空，2026-07 R1 新增）
final_score               融合总分（一切排序的唯一依据）
recommendation_reason
```

分数公式的事实源已移至 `docs/backend/recommendation-scoring-design.md`：
粗排 `coarse_score` 公式见其 §4.2（即当前代码实现的公式），LLM 精排与
`final_score` 融合公式见其 §6。本文旧版的
`quality*0.25 + topic*0.25 + ...` 建议公式与代码实现不一致，**已作废**。

说明：

- `diversity_score` 可以是正负修正项，不一定归一到 0-100。
- 初次生成日报时，用户反馈可能很少，主要靠质量、主题、时效、来源。
- 周报生成时，用户反馈和热度权重要更高。

## 8. 来源评分

表：`source_score_snapshots`

```text
id
data_source_id
window                  7d / 30d
fetch_success_rate
extract_success_rate
dedupe_win_rate
daily_adoption_rate
weekly_adoption_rate
avg_news_heat_score
avg_user_rating
duplicate_rate
low_signal_rate
source_score
computed_at
```

来源评分建议：

```text
source_score =
  fetch_success_rate * 15
  + extract_success_rate * 15
  + dedupe_win_rate * 15
  + daily_adoption_rate * 20
  + weekly_adoption_rate * 10
  + normalized(avg_news_heat_score) * 15
  + normalized(avg_user_rating) * 10
  - duplicate_rate * 10
  - low_signal_rate * 10
```

用途：

- 展示在数据源看板。
- 进入后续推荐的 `source_score`。
- 帮管理员发现低质源、失效源、刷屏源。

2026-07 R1 落地版以推荐反哺所需字段为准（机器契约
`config/contracts/recommendation_ranking.json` `data_model_deltas` 是字段事实源）：
`workspace_code`、`data_source_id`、`window(14d)`、`recommended_count`、
`adopted_count`、`rejected_count`、`like_count`、`adopt_rate`、`reject_rate`、
`like_rate`、`source_prior_delta`、`day_key`、`computed_at`。上表中的
fetch/extract 成功率等运营指标是后续扩展列，不在 R1 范围。
`source_prior_delta` 的计算见 §10.1，由推荐粗排层叠加进 `source_score`。

## 9. 闭环

闭环路径：

```text
用户点赞/评论/评分
-> reactions/comments/ratings
-> news_heat_snapshots
-> recommendation_items.feedback_score / heat_score
-> daily_report_items / weekly_report_items
-> source_score_snapshots
-> 下一轮推荐
```

管理员采信路径：

```text
daily_report_items.adoption_status = 2
-> editorial_actions(adopt)
-> news_heat_snapshots.editorial_adopt_count
-> source_score_snapshots.daily_adoption_rate
-> 下一轮推荐 source_score
```

需求结论路径：

```text
requirements.metadata_json.recommendation_feedback 或 resolved/closed/rejected 状态
-> editorial_actions(requirement.feedback_to_recommendation)
-> recommendation_items.feedback_score
-> recommendation_reason(requirement_feedback_positive/negative)
-> 下一轮推荐
```

该路径只把内部需求结论作为后续推荐输入，不覆盖 `raw_items`、`news_items`、评论或已有成稿。

这样系统不是只按抓取内容推荐，而是逐步学习“哪些新闻真的被用户和管理员认为有价值”。

## 10. 周期再估计：源先验与主题权重（2026-07 R1）

设计事实源：`docs/backend/recommendation-scoring-design.md` §8；机器契约：
`config/contracts/recommendation_ranking.json` `feedback_reestimation`。
本节是公式细节附录。

执行载体：每日 job `feedback_reaggregate_daily`（scheduler 注册，02:00
Asia/Shanghai，trailing 14 天窗口，幂等：同 `day_key` 重跑覆盖当日快照）。
简化的 preference aggregation：周期批量再估计，**不引入在线训练依赖**。

### 10.1 源先验增量（进粗排 `source_score`）

对每个 `(workspace, data_source)`，统计窗口内曾进入推荐的条目：

```text
adopt_rate  = 被采信条目数(adoption_status=2 且日报已发布) / max(1, 推荐条目数)
reject_rate = 被剔除条目数(adoption_status=3)              / max(1, 推荐条目数)
like_rate   = min(1.0, 点赞数 / max(1, 推荐条目数))
source_prior_delta = clamp(8*adopt_rate - 6*reject_rate + 2*like_rate, -6.0, +6.0)
```

写入 `source_score_snapshots`；粗排 `_source_score` 读取最新快照叠加
`source_prior_delta`，叠加后仍 clamp 0..100。**每日全量重估、非累加**，
delta 有硬界，不会漂移发散；无快照时 delta=0，行为与现状一致。

### 10.2 主题权重乘子（进 LLM 精排 prompt）

仅对 `rubric_status=active` 的工作台。对 rubric 每个 topic code `t`，统计
窗口内 `rubric_hits_json` 含 `t` 的条目：

```text
pos_t = 其中被采信的条目数
neg_t = 其中被剔除的条目数
effective_weight_t = clamp(
    authored_weight_t * (1 + 0.1 * (pos_t - neg_t) / max(5, pos_t + neg_t)),
    0.5 * authored_weight_t,
    1.5 * authored_weight_t)
```

- 单次再估计幅度 ≤ ±10%，累计钳制在 authored weight 的 [0.5, 1.5] 倍；
  用户写的导向是锚，反馈只微调，防振荡。
- 写入 `rubric_topic_priors` 快照，审计可回溯；`active_rubric` 里的
  authored weight **永不被改写**。
- `rubric_version` 变更时统计清零重来。

### 10.3 禁止事项

- 反馈不得直接改写 rubric authored 字段或 guidance 文本。
- 再估计不得修改历史 `recommendation_items` 快照。
- 推荐模块不得反向修改评论、通知或 Strategy Loop 状态。

## 11. 反馈回哺工作流：总览与业界方案参照（2026-07-08 定稿）

> 状态：`implemented`（2026-07-08 实施工作包 WP4-G，
> `docs/implementation/01-implementation-plan.md` §18；落点
> `backend/app/recommendations/rollup.py` + 迁移 `f3c4d5e6f7a8`，验收
> `backend/tests/test_feedback_rollup.py` / `test_rubric_proposals.py`）。
> 机器契约：`config/contracts/recommendation_ranking.json` `feedback_workflow`。
> 本层是 §10 每日再估计（WP4-A 已实现）的**延伸层**，不推翻每日公式。

### 11.1 核心规则（一票否决级）

**周/月层零直接改分。** 进入推荐分数的路径只有每日 job 的两个快照
（`source_score_snapshots.source_prior_delta` 与
`rubric_topic_priors.effective_weight`，公式见 §10.1/§10.2，不变）。
周/月层只产出三类东西：**评估快照**（feedback_rollups）、**建议**
（源分层升降/失效清理，advisory）、**提案**（rubric 修订，必须人审后经既有
compile+activate 版本化链生效）。authored 导向永不被任何自动流程改写。

### 11.2 节拍总览

```text
日（已实现，不动）：feedback_reaggregate_daily 02:00
  -> source_prior_delta / effective_topic_weight 快照（唯一进分数的路径）
周（本轮新增）：feedback_weekly_rollup 周一 03:00
  -> feedback_rollups(weekly)：评估指标 + 源分层建议 + 低数据源清单
  -> rubric_revision_proposals：LLM 修订提案（pending_review，人审）
月（本轮新增）：feedback_monthly_review 每月 1 日 03:30
  -> feedback_rollups(monthly)：长期漂移检测 + 失效源清理建议 + 月度汇总
人审：提案 accept -> 登记 compile 记录 -> 既有 activate 链（rubric_version+1）
  -> 每日 job 基于新 authored weight 自然重估 -> 下一轮推荐
```

### 11.3 业界方案参照与采纳结论

| 方案 | 内容 | 结论 | 理由 |
|---|---|---|---|
| 离线批量偏好聚合与周期性再加权（preference aggregation） | 周期批量把显式反馈折算成先验/权重，无在线训练依赖 | **采纳** | 每日层（§10）已用同范式落地并验证；周/月层沿用，体量（每工作台每日数百候选）远不到在线学习成本临界点 |
| 隐式反馈去偏：position bias 校正（简化版） | 展示位次靠前的条目更易被采信，采信率必须按位次归一才可比 | **采纳（简化）** | 全套 inverse-propensity 需要曝光日志与倾向估计，超出本系统数据面；简化为写死的 rank-bucket 权重归一（§12.3），只用于周评估与源分层建议，**不进每日公式** |
| 离线评估：precision@K / rerank uplift / 覆盖多样性 | 用采信作为 ground truth 离线评估推荐质量与精排增益 | **采纳** | 采信是本系统天然的高质量标注；uplift 直接回答"LLM 精排相对粗排值不值"（预算决策依据）；指标定义写死（§13.4） |
| Human-in-the-loop rubric 修订（RLHF-lite） | LLM 从反馈样本生成 rubric 修订提案，人审后生效 | **采纳（约束版）** | 复用已验证的 rubric 编译/activate 版本化链；提案只是"预填好的编译输入"，人审是硬门（§13.5）；**绝不自动改 authored 导向** |
| 低数据源探索保留（ε-greedy 防马太效应） | 预留小比例探索位给反馈样本不足的源，防止先验低分封死新源 | **采纳（有界、默认关）** | 源先验 delta 会让零反馈源长期沉底；ε 上限 0.1、每 run ≤1 条、只在 P1/P2 内、确定性种子可复现（§15）；默认 ε=0 保回归红线 |
| Bandit / 在线学习（LinUCB、Thompson sampling 等） | 在线更新排序参数 | **不采纳** | 重申每日层结论（recommendation-scoring-design §3.5）：需要训练基础设施与探索流量管理，本系统明确不引入在线训练依赖 |
| 偏好微调 / DPO（把反馈蒸馏进模型） | 用采信/驳回对训练排序模型 | **不采纳** | 样本量（每周数十对）远低于微调有效阈值；rubric 文本层的修订提案已覆盖"反馈改变模型行为"的诉求且完全可审计 |

## 12. 信号面清点（对照现有表逐个核实）

以下每个信号都已对照 `backend/app/models/` 核实存在。权重是周/月 rollup 的
**评估聚合权重**（用于指标、样本选择与建议排序），不是打分公式——周/月层
不改任何分（§11.1）。

### 12.1 信号清单与权重

| 信号 | 表/字段（已核实） | 极性/权重 | 去重规则 |
|---|---|---|---|
| 条目→requirement 转化（positive 结论） | `editorial_actions.action_type = requirement.feedback_to_recommendation` 且 `after_json.outcome=positive`（`requirements` + `requirement_source_links` 链，`backend/app/api/routes/operations.py` 写入） | 最强正 **+10** | 每 (requirement_id, news_item_id) 计 1 次（写入侧已有 action 幂等去重）；同 news_item 多需求取权重最高一条 |
| 日报采信 | `daily_report_items.adoption_status = 2` 且所属日报 `status=published`（`backend/app/models/reports.py`） | 强正 **+8** | 每 (news_item, daily_report) 计 1 次；同 news_item 跨日报重复出现取最新日报 |
| 周报采信 | `weekly_report_items.adoption_status = 2` 且周报 `status=published`；沿 `daily_report_item_id / generated_news_id` 回溯 news_item | 次强正 **+4** | 回溯到 news_item 后每 (news_item, weekly_report) 计 1 次 |
| 点赞 | `reactions(reaction_type=like, active=true)`，双维度（news_item / daily_report_item） | 弱正 **+2** | 每 user × target 计 1 次（active 行唯一）；daily_report_item 维度回溯 news_item 后合并 |
| 评分 | `ratings.score`（1-5，dimension=overall） | 弱 **±1**：均值 ≥4 计 +1，≤2 计 −1，(2,4) 不计 | 每 user × target 取最新一条；先按 news_item 聚合均值再判极性 |
| 日报驳回 | `daily_report_items.adoption_status = 3` | 强负 **−6** | 同日报采信 |
| 周报驳回 | `weekly_report_items.adoption_status = 3` | 弱负 **−2** | 同周报采信 |
| requirement 负向结论 | 同转化信号，`after_json.outcome=negative` | 负 **−4** | 同转化信号 |
| 编辑覆盖幅度 | `daily_report_items.editor_title / editor_summary / editor_content_json` 非空（对照 `generated_news` 生成稿） | **v1 不加权（0）**，只进观测列 `edit_rate` | 每 daily_report_item 计 1 次（任一 editor_* 非空即算被覆盖） |

**编辑覆盖幅度的 v1 判定（写死）**：不纳入加权。理由：编辑动机多义——大幅
改写既可能是"生成/选择不佳"（负），也可能是"内容重要值得精修"（正），无法在
无标注情况下可靠区分极性。v1 只统计 `edit_rate`（被采信条目中 editor_* 非空
占比）进 rollup 观测列，累计 ≥8 周数据后另行决策是否入权。

强弱信号口径与每日公式（§10.1 的 8/-6/+2）同族且不冲突：每日层只消费
采信/驳回/点赞三个信号（已实现，不动），周/月层消费全表。

### 12.2 信号窗口与归属

- 周窗口：上一个完整 ISO 周（周一 00:00 至周日 24:00，Asia/Shanghai）。
- 月窗口：上一个自然月。
- 事件归属时间：反馈动作的发生时间（`created_at` / `reviewed` 时刻），
  不是被反馈条目的推荐时间——避免旧条目的迟到反馈丢失。
- 只统计窗口内**曾进入推荐**（`recommendation_items` 存在且可回溯
  workspace）的条目；工作台之间互不污染。

### 12.3 位次去偏（position bias 简化校正，写死）

展示位次取日报草稿 `daily_report_items.sort_order`（现状按 final_score 降序
赋值）；未进日报的条目取推荐 run rank。归一化采信率：

```text
bucket 权重：rank 1-6 -> 1.0；rank 7-15 -> 1.2；rank >=16 -> 1.4
normalized_adopt_rate = min(1.0,
    Σ_bucket(bucket_weight * adopted_in_bucket) / max(1, recommended_count))
```

语义：长尾位次的采信更有信息量（用户翻过了头部才采它），给更高归一权重。
该值只进周评估与源分层建议（§13.2），**不改写** `source_score_snapshots`
的任何字段，每日公式（§10.1）继续用未归一的 adopt_rate。

## 13. 周节拍：feedback_weekly_rollup

### 13.1 job 接入方式（判定，写死）

scheduler（`backend/app/workers/scheduler.py`）现有两种节拍机制：
per-workspace `schedule_policy` 周报节拍（`_dispatch_weekly`）与实例级固定
时刻 job（`_dispatch_feedback_reaggregate`，心跳幂等）。**判定：复用后者**——
反馈回哺是系统级再估计而非用户可配报告节拍，与每日层同族：

```text
job：feedback_weekly_rollup（job_kind 同名，workspace_code=""）
触发：每周一 03:00 Asia/Shanghai（晚于每日 02:00 job，读取其最新快照）
幂等：心跳表按触发点判重（跨实例第一道）；job 内同 (workspace, period_key)
      重跑覆盖同一 rollup 行（unique 约束第二道）
重启语义：与每日层一致——错过触发点不补跑，等下周（手动触发 API 可补，§16.1）
能力门：settings.capability_ingestion 为假（intranet pull-only）不投递
job 内部：遍历 enabled 工作台逐个 rollup，单工作台失败不中断其余
period_key：ISO 周，如 2026-W28；窗口 = 上一个完整 ISO 周（§12.2）
```

### 13.2 产出一：源分层重估（tier 建议，advisory）

对每个 (workspace, data_source) 统计周窗口（并回看 28 天补充样本量）：

```text
insufficient_data：recommended_count < 5      -> 进低数据源清单（ε 探索候选池）
suggest_promote：recommended >= 8 且 normalized_adopt_rate >= 0.25 且 reject_rate <= 0.1
suggest_demote： recommended >= 8 且 adopted_count = 0 且 reject_rate >= 0.5
keep：其余
```

写入 `feedback_rollups.source_breakdown_json`。**只写建议**：不改
`data_sources` 的 tier/enabled、不改 `workspace_source_links.source_weight`、
不写 `source_score_snapshots`。管理员在评估卡上看到建议后自行操作既有源管理
入口。

### 13.3 产出二：topic 权重再平衡（进提案输入，不进分数）

对 `rubric_status=active` 的工作台，汇总周窗口每 topic 的 pos/neg 与每日
`rubric_topic_priors.effective_weight` 序列：

```text
贴边判定：某 topic 连续 7 天 effective_weight >= 1.45 * authored_weight
          （或 <= 0.55 * authored_weight）
-> 列入「authored weight 修订建议」（说明每日乘子已顶住 §10.2 的 [0.5, 1.5]
   clamp，反馈强度超出微调范围，应人工修订 authored 值）
```

写入 `topic_breakdown_json` 并作为 §13.5 提案生成的输入。`rubric_topic_priors`
的唯一写入方仍是每日 job（§10.2 公式不变）；周层零写入。

### 13.4 产出三：评估报告（指标定义写死）

写入 `feedback_rollups.metrics_json`；报告即 rollup 行的投影，**不另建表**：

| 指标 | 定义 | 空样本行为 |
|---|---|---|
| `precision_at_6` / `precision_at_12` | 对窗口内每个已发布日报：`top-K(sort_order) 中 adoption_status=2 的条数 / min(K, 条目数)`，再对日报求均值 | 窗口无已发布日报 -> `null`（不得写 0） |
| `rerank_uplift` | 仅取 `llm_rerank_status ∈ {scored, cached}` 的候选集：按 `final_score` 排序算 precision@6 − 按 `coarse_score` 排序算 precision@6（同一采信事实） | 无 scored 候选 -> `null` |
| `source_coverage` | 被采信条目的 unique 来源数 / 采信条数 | 无采信 -> `null` |
| `topic_entropy` | 被采信条目 `rubric_hits_json` 上的香农熵 / log(topic 数)（归一 0..1；仅 rubric active） | 无 rubric 或无命中 -> `null` |
| `normalized_adopt_rate` | §12.3 位次去偏后的全工作台采信率 | 无推荐 -> `null` |
| `edit_rate` | 被采信条目中 editor_* 非空占比（§12.1 观测列） | 无采信 -> `null` |
| `signal_counts` | §12.1 各信号的窗口内计数原值 | 全 0 计数照写 |
| `low_data_sources` | `insufficient_data` 源的 id/name 清单 | 空数组 |

### 13.5 产出四：rubric 修订提案生成（RLHF-lite，人审硬门）

**触发条件（全部满足才调用 LLM）**：

```text
rubric_status = active
AND recommendation_policy.feedback_workflow.proposal_generation_enabled = true
AND 窗口内强信号事件数（日报采信 + 日报驳回）>= 10
AND 本工作台无 status=pending_review 的存量提案
AND generation provider usable（resolve_generation_config 统一解析链）
AND purpose=feedback_rollup 预算桶余量 >= 1（§17 第 5 条）
```

任一不满足 → `feedback_rollups.proposal_status` 记
`skipped_no_rubric | skipped_disabled | skipped_low_data |
skipped_pending_exists | skipped_provider | skipped_budget`，rollup 本身照常
`succeeded`。

**代表样本选择（确定性，可复现）**：采信样本 = 窗口内被采信条目按
`final_score` 降序 top 8；驳回样本 = 被驳回条目按 `final_score` 降序 top 8
（高分被驳回的最有信息量）。每条截断为
`{title, summary(≤200字), source_name, rubric_hits}`。

**prompt（`revision_prompt_v1`，版本号入库）**：输入 = 当前 active rubric
JSON + 最新 effective weights + §13.4 指标摘要 + 采信/驳回代表样本 +
§13.3 贴边 topic 清单；输出严格 JSON：

```json
{
  "proposed_rubric": { "...": "完整 rubric，必须过 recommendation-scoring-design §5.2 schema" },
  "change_summary": [
    {"op": "adjust_topic_weight", "target_code": "inference_serving",
     "from": 4.0, "to": 4.5, "rationale": "一句话理由（≤60字）"}
  ]
}
```

`op` 枚举：`add_topic | remove_topic | adjust_topic_weight | add_exclusion |
remove_exclusion | adjust_boost | edit_keywords_hint`。`proposed_rubric`
schema 校验失败或 change_summary 与前后 rubric diff 不一致 → 同 prompt 重试
1 次（计预算）；仍失败 → `proposal_status=failed`，rollup 照常 `succeeded`。
成功 → 写入 `rubric_revision_proposals`（status=`pending_review`），同工作台
既存 pending 提案置 `superseded`（新提案生成前置条件已保证无 pending，此规则
兜底手动触发的竞态）。

**人审硬门**：提案入库对现行 rubric 零影响；accept 动作见 §16.2——服务端
原子执行「登记 `recommendation_rubric_compiles` 记录（`model_called=false`、
`prompt_version=revision_proposal_v1`）→ 走既有 activate 链
（fingerprint 门禁、`rubric_version += 1`、审计
`workspace.recommendation_rubric.activate`）」。绝无任何路径绕过人审改写
authored 导向。

## 14. 月节拍：feedback_monthly_review

```text
job：feedback_monthly_review（job_kind 同名，workspace_code=""）
触发：每月 1 日 03:30 Asia/Shanghai；接入方式/幂等/能力门与 §13.1 完全一致
period_key：自然月，如 2026-06；窗口 = 上一个自然月
LLM 调用：0 次（v1 纯聚合，写死）
```

产出（写入 `feedback_rollups(period_type=monthly)`）：

1. **长期漂移检测**：月 `precision_at_6` 对上月相对下降 >20% 且绝对下降
   ≥0.05 → `metrics_json.drift_flag=true`；同时汇总当月推荐 run summary 里
   `drift_alert/low_variance` 计数（WP4-A 已持久化）。只标记不整形，与
   recommendation-scoring-design §4.4 漂移监控口径一致。
2. **失效源清理建议**：enabled 源满足（a）连续 4 个周 rollup
   `recommended_count=0`，或（b）当月 `recommended_count >= 8` 且
   `adopted_count=0` 且 `reject_rate >= 0.5` → 进
   `source_breakdown_json.stale_source_suggestions`
   （`suggest_disable | suggest_review`）。**不自动禁用任何源**。
3. **月度评估汇总**：当月各周 rollup 指标的均值/序列，提案生成与审阅结果
   计数（generated/accepted/rejected），供推荐设置卡与运营评估卡展示。

## 15. 探索保留：ε 探索位（防马太效应，默认关）

存放：`recommendation_policy.feedback_workflow.exploration_epsilon`
（float 0..0.1，**默认 0.0**，建议开启值 0.05；越界 PATCH 422）。

选择层行为（推荐 run 的 selection 阶段，现状算法之后追加）：

```text
前提：epsilon > 0 且最新 weekly rollup 的 low_data_sources 非空
确定性抽签：draw = int(sha256(run_key + ":exploration"), 16) / 2**256
draw < epsilon 时：从未入选候选中挑「低数据源 且 admission ∈ {P1, P2}」里
  coarse_score 最高的 1 条，追加进入选集（每 run 至多 1 条）
约束：不得超过 run limit、source cap、pool cap（冲突则放弃探索位）；
  不改 admission；R/P3 永不因探索入选
可解释：该条 recommendation_reason 追加 "exploration_slot"，前端可见
```

`epsilon=0`（默认）时选择行为与现状**逐位一致**——这是回归红线的延伸：
反馈回哺整层在缺省配置下对排序与选择零影响。

## 16. 数据模型、API 与 UI

### 16.1 数据模型增量（单迁移）

一次 Alembic 迁移完成（revision 由实现期分配，down_revision 指向实现时刻
e/f 链的当前 head——本文定稿日为 `f2b3c4d5e6a7`）：

```text
feedback_rollups（新表，无 SyncMixin——永不进同步 feed）
  id, workspace_code(idx),
  period_type            String(16)   weekly | monthly
  period_key             String(16)   ISO 周 2026-W28 / 月 2026-06
  window_start           DateTime(tz) 窗口起点
  window_end             DateTime(tz) 窗口终点
  status                 String(16)   succeeded | empty | failed
  proposal_status        String(32)   none | generated | failed | skipped_*（§13.5）
  metrics_json           JSON         §13.4 / §14 指标（空样本一律 null 不写 0）
  source_breakdown_json  JSON         per-source 计数 + tier 建议 + 低数据/失效清单
  topic_breakdown_json   JSON         per-topic pos/neg + effective weight 摘要 + 贴边清单
  sample_refs_json       JSON         代表样本 news_item_id 列表
  computed_at, created_at, updated_at
  unique(workspace_code, period_type, period_key)

rubric_revision_proposals（新表，无 SyncMixin）
  id, workspace_code(idx),
  rollup_id              FK feedback_rollups(idx)
  base_rubric_version    Integer      生成时的 rubric_version（stale 防护）
  prompt_version         String(32)   revision_prompt_v1
  proposed_rubric_json   JSON         完整 rubric（recommendation-scoring-design §5.2 schema 已校验）
  change_summary_json    JSON         diff 列表（§13.5 op 枚举）
  sample_refs_json       JSON
  status                 String(24)   pending_review | accepted | rejected
                                      | superseded | expired；idx(workspace_code, status)
  review_comment         Text default ''
  reviewed_by            FK users nullable
  reviewed_at            DateTime(tz) nullable
  compile_fingerprint    String(80) default ''   accept 时回填
  created_at, updated_at

recommendation_policy 增键（JSON policy，无迁移）：
  feedback_workflow: {
    "weekly_rollup_enabled": true,
    "monthly_review_enabled": true,
    "proposal_generation_enabled": true,
    "exploration_epsilon": 0.0
  }

generation_daily_usage：purpose 枚举扩展 feedback_rollup（String 列直接容纳，
  无迁移；固定 4 次/工作台/日，不可配——§17 第 5 条）
```

评估报告存放判定（写死）：**存 rollup**（`metrics_json` 即报告），不独立
建表——报告是周期快照的投影，独立表只会引入第三份事实。

提案过期治理：周 job 顺带把 created_at 超过 30 天仍 pending_review 的提案置
`expired`（防僵尸提案阻塞 §13.5 的 pending 前置条件）。

### 16.2 API（全部 workspace admin+，已随 WP4-G 实现）

```text
GET  /api/workspaces/{code}/feedback-rollups?period_type=weekly|monthly&limit=8
  -> {"items": [{id, period_type, period_key, window_start, window_end, status,
      proposal_status, metrics, computed_at}], "total": n}（按 period_key 降序）

GET  /api/workspaces/{code}/feedback-rollups/{id}
  -> 全量明细（含 source_breakdown / topic_breakdown / sample_refs）

POST /api/workspaces/{code}/feedback-rollups/run
  body {"period_type": "weekly"|"monthly", "period_key": "2026-W28"（缺省=上一完整周期）}
  -> 同步执行并返回 rollup 摘要；幂等覆盖同 period_key 行；审计
     workspace.feedback_rollup.manual_run（detail 记 period_type/period_key/trigger=manual）

GET  /api/workspaces/{code}/rubric-revision-proposals?status=pending_review
  -> {"items": [{id, base_rubric_version, change_summary, sample_refs, status,
      rollup_period_key, created_at}]}

POST /api/workspaces/{code}/rubric-revision-proposals/{id}/review
  body {"action": "accept"|"reject", "comment": ""}
  reject -> status=rejected + 审计 workspace.rubric_revision_proposal.review
  accept -> 服务端原子执行：登记 recommendation_rubric_compiles
     （model_called=false, prompt_version=revision_proposal_v1，fingerprint 按
     既有规则计算）-> 走既有 activate 链（rubric_version += 1、审计
     workspace.recommendation_rubric.activate）-> status=accepted 并回填
     compile_fingerprint + 审计 review
  422：提案非 pending_review；base_rubric_version != 当前 rubric_version
     （stale 提案防护——生成后 rubric 已被人工改版则提案作废，需重新生成）
```

权限判定：评估含源明细与运营数据，全部 admin+（与 compile/activate 同级）；
viewer/member 无读入口。所有写路径过 secret-like 检测（沿用
recommendation-policy 的 422 规则）。

### 16.3 UI 落位（调用形状级规格）

**工作台配置中心（/workspace-settings）推荐设置卡「反馈回哺」区**
（页面规格：`docs/product/page-specs/frontend-page-specs.md` §19.5）：

- 载入：`GET feedback-rollups?period_type=weekly&limit=1` +
  `GET rubric-revision-proposals?status=pending_review`。
- 摘要行：最近周期 `period_key`、precision@6、rerank uplift、低数据源数、
  pending 提案数徽章；指标为 null 时整项隐藏（空指标规则，不渲染 0.0）。
- 提案审阅入口：居中 Modal（md 档）逐条渲染 change_summary diff
  （op/target/from→to/rationale）与代表样本链接；「采纳并生效」二次确认
  （提示 rubric_version 将 +1）后调 `POST review {action: accept}`；「驳回」
  必填 comment 调 reject；成功后刷新卡上 rubric 版本号与提案徽章。
- 手动重估按钮：`POST feedback-rollups/run {period_type: "weekly"}`；loading
  态；成功刷新摘要；失败显示真实错误，不渲染成功（假成功回归）。
- viewer/member 不渲染该区；ε 探索与开关编辑随推荐设置卡的 policy PATCH。

**运营页（/recommendations）「反馈评估」卡**（页面规格同文件 §9）：

- period_type 切换（weekly/monthly）；`GET feedback-rollups?limit=8` 列表 +
  行展开详情（指标表、源 tier 建议、失效源清单、edit_rate）。
- 无 rollup 渲染「尚未生成反馈评估」空态；任何 null 指标不得渲染 0.0 占位。

## 17. 不变式（违反即回退）

1. **authored 导向永不被自动改写**：唯一变更路径是人审 accept → 既有
   compile+activate 版本化链；提案 pending/rejected/expired 对现行 rubric
   零影响。
2. **周/月层零直接改分**：进分数的路径仅每日 job 两快照（§10）；周/月层不写
   `source_score_snapshots` / `rubric_topic_priors` / `recommendation_items`。
3. **幅度限幅全保留**：每日层 `source_prior_delta ∈ [-6,6]`、topic 乘子
   `[0.5w, 1.5w]` 不变；ε ≤ 0.1 且每 run ≤1 探索位、不改准入不绕 caps。
4. **company_sql 与 adoption_status 语义不动**：rollup/提案不进公司 SQL 导出，
   导出字节不变；采信状态枚举与写入路径零变化。
5. **LLM 预算分桶**（判定写死）：提案生成走**新增** `purpose=feedback_rollup`
   桶（固定 4 次/工作台/日，不可配）。不复用 `rubric_compile` 桶——那是
   交互式编译配额（20/日），自动周任务挤占会伤害用户操作；四桶互不挤占，
   `generation_daily_usage` 的 String purpose 列无迁移即容纳新枚举。预算尽 →
   `proposal_status=skipped_budget`，rollup 照常完成。
6. **rollup 不进同步 feed**：两张新表无 SyncMixin、不注册 sync payload；
   评估与提案是本环境运营资产（intranet pull-only 边界沿用 workspace config
   现行规则）。
7. **只读事实**：rollup 只读推荐/日报/反馈事实表，不修改任何历史快照、
   不改源 enabled/tier、不触碰评论/通知/Strategy Loop 状态。
8. **能力门与降级**：无 ingestion 能力的实例不投递 job；provider/预算/数据
   不足全部走 skipped 分支，任何失败不阻塞 scheduler tick 与其他工作台。

## 18. 验收断言（对应契约 `feedback_workflow.acceptance_assertions`）

1. **空跑不报错**：无任何反馈数据时 weekly rollup 正常完成，写入
   `status=empty` 行，`metrics_json` 空样本指标全为 null（无 0.0），零 LLM
   调用、零提案。
2. **幂等覆盖**：同 (workspace, period_type, period_key) 重跑覆盖同一行不
   产生重复；已有本窗口提案（任意状态）时不重复生成。
3. **提案未审阅不影响现行 rubric**：pending_review 提案存在时
   `active_rubric / rubric_version / effective weights` 全部不变，推荐 run
   行为与无提案时逐位一致。
4. **accept 走既有 activate 链**：accept 后 `rubric_version + 1`、
   `recommendation_rubric_compiles` 存在 `model_called=false` 记录、审计同时
   有 `workspace.recommendation_rubric.activate` 与
   `workspace.rubric_revision_proposal.review`；authored 字段从未被 job 写过。
5. **stale 提案防护**：`base_rubric_version != 当前 rubric_version` 的提案
   accept 返回 422；reject 后 policy 不变；新提案生成时存量 pending 置
   superseded；超 30 天 pending 被周 job 置 expired。
6. **预算分桶隔离**：提案生成调用（含重试）只计
   `generation_daily_usage(purpose=feedback_rollup)`，不动
   generation/rerank/rubric_compile 三桶；日上限 4 次耗尽后 rollup 仍
   `succeeded` 且 `proposal_status=skipped_budget`。
7. **ε 探索上限**：`exploration_epsilon` 越界（<0 或 >0.1）PATCH 422；
   每 run 至多 1 条探索位且必须 admission ∈ {P1,P2}、reason 含
   `exploration_slot`；`epsilon=0`（默认）时选择结果与现状逐位一致；同
   run_key 抽签可复现。
8. **指标正确性**：固定 fixture 下 precision@6/@12、rerank_uplift、
   source_coverage、topic_entropy、normalized_adopt_rate 与手工计算一致；
   无已发布日报时 precision 为 null 而非 0。
9. **位次去偏生效**：同一采信事实、不同展示位次的 fixture 下
   normalized_adopt_rate 按 §12.3 bucket 权重（1.0/1.2/1.4）产生差异。
10. **月度漂移与失效源**：构造下滑序列 fixture 产出 `drift_flag=true`；连续
    4 周零推荐源与高驳回零采信源进 `stale_source_suggestions`；
    `data_sources.enabled` 与 tier 在 job 前后逐字段不变（不自动禁用）。
11. **边界不越权**：sync feed payload 与公司 SQL 导出中 grep 不到两张新表
    数据；company_sql 输出逐字节不变；rollup 运行前后历史
    `recommendation_items / source_score_snapshots / rubric_topic_priors`
    行不变。
12. **手动触发**：`POST feedback-rollups/run` 幂等、写审计
    `workspace.feedback_rollup.manual_run`、viewer/member 403。
13. **调度幂等与能力门**：同一触发点跨实例只投递一次（心跳判重）；
    `capability_ingestion=false` 实例零投递；单工作台 rollup 失败不影响其余
    工作台与 scheduler tick。
14. **UI 空态**：无 rollup 时设置卡与评估卡渲染「尚未生成」空态；null 指标
    整项隐藏，页面不出现 `0.0` 占位（前端 spec 断言看护）。
