# Recommendation & Scoring 推荐与评分设计

> 状态：目标态设计稿。本文是推荐准入、评分、推荐 run、分数解释和反馈反哺的后端
> 模块事实源。反馈数据本身见 `docs/backend/collaboration-notification-design.md`，
> 热度/来源评分细节见 `docs/backend/feedback-heat-scoring.md`。

## 1. 模块定位

Recommendation & Scoring 负责从去重后的候选中选出值得进入日报/周报/成稿流程的内容。

输入：

```text
dedupe_groups active winner
news_items
data_sources / workspace_source_links
workspace label policy
content_scorer config
feedback aggregates
```

输出：

```text
recommendation_runs
recommendation_items
selected candidates for generated_news / reports
explainable scoring fields
```

它不负责：

- 抓取 raw 和标准化 news，见 `docs/backend/data-ingestion-flow-storage-design.md`。
- 用户评论、点赞、评分的原始写入，见 `docs/backend/collaboration-notification-design.md`。
- 日报/周报采信和成稿，见 `docs/backend/report-renditions-design.md`。

## 2. 推荐链路

```text
dedupe winner
-> eligibility filter
-> admission classification P0/P1/P2/P3/R
-> score components
-> diversity and source caps
-> recommendation_items
-> selected items
-> generated_news / daily_report_items
```

推荐只处理 active winner，不直接处理 raw，也不直接处理重复 loser。

## 3. 核心对象

### recommendation_runs

```text
id
workspace_code
domain_code
day_key
status
parameters_json
candidate_count
selected_count
started_at
finished_at
created_by
summary_json
```

### recommendation_items

```text
id
recommendation_run_id
news_item_id
dedupe_group_id
workspace_code
domain_code
admission_level          P0 / P1 / P2 / P3 / R
admission_score
admission_pool
quality_score
topic_score
freshness_score
source_score
heat_score
feedback_score
diversity_score
final_score
noise_types_json
reject_reasons_json
scorer_breakdown_json
expert_routes_json
recommendation_reason
selected
rank
```

## 4. 准入层

准入层先回答“这条是否值得进入候选池/推荐池”，再计算排序分。

建议口径：

| 等级 | 含义 | 默认处理 |
|---|---|---|
| P0 | 强相关、强时效、强价值 | 优先推荐 |
| P1 | 明确相关、有日报价值 | 可推荐 |
| P2 | 有价值但需观察 | 观察池 |
| P3 | 弱相关或信息不完整 | 默认不选 |
| R | 噪声、重复低质、不符合范围 | 拒绝 |

准入结果必须持久化，不能只在日志里。

## 5. 分数组成

推荐分必须可解释，至少拆成：

```text
quality_score
topic_score
freshness_score
source_score
heat_score
feedback_score
diversity_score
final_score
```

建议第一版公式：

```text
final_score =
  quality_score * 0.25
  + topic_score * 0.25
  + freshness_score * 0.15
  + source_score * 0.15
  + heat_score * 0.10
  + feedback_score * 0.10
  + diversity_score
```

`diversity_score` 是修正项，可以为负，不强制归一到 0-100。

## 6. 评分配置

评分配置是推荐模块的重要 contract-like 配置。

当前主要来源：

```text
config/scoring/content_scorer_v2.json
```

配置应覆盖：

- 主题关键词和负向噪声词。
- source tier / channel type 加权。
- 专家路由。
- admission 阈值。
- 噪声类型。
- 拒绝原因。
- 工作台/领域差异。

新增评分字段时必须同步：

- `recommendation_items` schema。
- API response。
- 前端推荐页和候选池解释字段。
- 测试 fixture。

## 7. 工作台与标签策略

推荐必须读取当前工作台策略：

```text
workspaces.config_json.label_policy
workspace_source_links.source_weight
workspace_source_links.daily_limit
```

规则：

- `planning_intel` 使用 AI 十分类和公司 SQL 兼容格式。
- 新工作台可以使用自己的标签策略。
- 数据源方向标签只作为先验，不写入 `generated_news.category`。
- 推荐不能把工作台 A 的策略污染到工作台 B。

## 8. 反馈反哺

原始反馈来自 Collaboration 模块：

```text
reactions
ratings
comments
editorial_actions
```

推荐模块只读取聚合特征：

```text
news_heat_snapshots
source_score_snapshots
feedback aggregates
```

当前 v1 还读取需求结论反馈动作：

```text
editorial_actions.action_type = requirement.feedback_to_recommendation
after_json.outcome = positive | negative | neutral
after_json.score_delta
```

该动作由 Strategy Loop 在 requirement 更新时写入，目标对象是 `news_item`。推荐层只把
`score_delta` 汇入 `feedback_score`，并在 `recommendation_reason` 中追加
`requirement_feedback_positive` 或 `requirement_feedback_negative`，不修改 requirement、
评论、raw 或 news 原始记录。`feedback_score` 最终仍保持有界，避免单个需求结论无限放大。

禁止：

- 推荐模块修改原始评论。
- 推荐模块修改通知状态。
- 推荐模块直接把点赞逐条当作通知。
- 推荐模块反向修改 Strategy Loop 的 requirement/task 状态。

## 9. source cap 与多样性

推荐不能被单一来源或单一主题刷屏。

应支持：

```text
source_daily_limit
source_type caps
primary_label diversity
secondary_label diversity
duplicate group winner only
```

当一个高分候选因多样性或日限被压下，`recommendation_items` 必须记录原因，便于前端解释。

## 10. API 目标态

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

- run 状态。
- 候选数、选中数。
- 每条 item 的分数拆解。
- 被拒或未选原因。
- 最新关联日报 trace：`day_key`、`report_status`、`adoption_status`、`daily_report_item_id`。

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
`recommendation_item.daily_report` trace，前端据此显示“已采信/已剔除/未处理”。

## 11. 与流水线的关系

完整日更流水线：

```text
ingestion
-> normalize
-> dedupe
-> recommendation
-> generation
-> daily report draft
```

推荐层必须可单独重跑，也必须能被 `POST /api/pipeline/daily-runs` 编排调用。

约束：

- 已发布日报不可被重跑覆盖。
- 推荐 run 不应修改 raw/news/dedupe 事实。
- 推荐 run 可以读取最新 feedback aggregate，但结果要快照化保存。

## 12. 当前设计缺口

| 缺口 | 判定标准 |
|---|---|
| 推荐设计过去分散在反馈文档和能力地图 | 本文成为 Recommendation & Scoring 事实源 |
| 评分配置运营视图仍需深化 | 只读策略摘要 v1、单条 scorer preview v1、P2/P3 观察池复核 v1 已完成；后续补策略编辑、批量重算影响和配置变更审计 |
| P2/P3 观察池运营仍需深化 | 当前已有 P2/P3 筛选、复核、采信/剔除入口；后续补观察池排序策略、复核备注、抽检队列和批量重算联动 |
| 多样性和 source cap 解释不足 | 未选原因持久化并前端展示 |
| 反馈聚合运营化不足 | heat/source 快照、需求结论 action 和用户反馈聚合都能进入下一轮推荐，并有可解释的运营视图 |
| 生产抽检机制不足 | 推荐 run 抽样验收分数、拒绝原因和最终采信结果 |

## 13. 验收设计

- 推荐 run 只处理目标日 active winner。
- `recommendation_items` 持久化准入等级、分数拆解和拒绝原因。
- 评分策略 API 返回当前配置版本、阈值、准入层、权重和噪声摘要，并由前端推荐页展示。
- 评分预览 API 对单条临时候选返回准入等级、噪声、专家路由和分数拆解，且不创建推荐 run 或日报草稿。
- P2/P3 观察池复核通过日报批量采信/剔除 API 写入日报草稿，并在推荐 run 详情回显 `daily_report.adoption_status`。
- 同一候选可追溯到 `news_items -> raw_items -> data_sources`。
- source daily limit 生效，并记录未选原因。
- P0/P1 候选优先进入 selected，P2/P3/R 默认不进入日报。
- 反馈聚合变化后新 run 的 `feedback_score` 可变化，旧 run 快照不被覆盖。
- 不同工作台使用各自 label policy 和 source link 权重。
