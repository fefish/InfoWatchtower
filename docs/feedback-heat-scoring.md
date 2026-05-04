# 用户反馈、热度评分与来源评分

本文档定义点赞、评论、用户评分、新闻热度、来源评分如何存储和进入推荐闭环。

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
final_score
recommendation_reason
```

建议第一阶段总分：

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

这样系统不是只按抓取内容推荐，而是逐步学习“哪些新闻真的被用户和管理员认为有价值”。

