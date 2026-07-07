# 用户反馈、热度评分与来源评分

本文档定义点赞、评论、用户评分、新闻热度、来源评分如何存储和进入推荐闭环。

当前推荐准入、推荐 run、分数解释和候选选择的目标态事实源是
`docs/backend/recommendation-scoring-design.md`。本文保留为反馈聚合、热度评分和来源评分
的细节附录；评论/通知原始协作流见 `docs/backend/collaboration-notification-design.md`。

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
