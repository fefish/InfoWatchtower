# 数据库存储与追溯链路

## 1. 存储方式

InfoWatchtower 以数据库为主存储。正式环境建议 PostgreSQL。

原因：

- 业务对象之间需要稳定外键追溯。
- 日报/周报/评论/评分/任务/权限都需要事务。
- 原始 payload 和审计快照适合用 PostgreSQL `jsonb`。
- 未来查询来源质量、推荐效果、用户反馈，需要结构化索引。

SQLite 只建议用于本地开发或轻量 demo。

## 2. raw_items 怎么存

`raw_items` 是“列化关键字段 + JSONB 保存完整原始数据”。

不是只存 JSON，也不是只存抽取后的字段。

建议字段：

```text
id
data_source_id
domain_code
visibility_scope
sync_policy
source_type
source_name
entry_key
source_url
canonical_url
source_title
raw_summary
raw_content
published_at
fetched_at
raw_payload_json        jsonb
source_specific_json    jsonb
extract_status
extract_error
created_at
updated_at
```

字段含义：

- 顶层列用于查询、去重、排序、索引。
- `raw_payload_json` 保存 adapter 拿到的完整原始对象。
- `source_specific_json` 保存某类源额外字段，比如 RSS tags、论文作者、DOI、PDF URL、wiseflow 扩展字段。
- `domain_code` 支撑 AI、硬件、半导体等板块扩展。
- `visibility_scope` 和 `sync_policy` 支撑公网/内网同步边界。

唯一约束：

```text
unique(data_source_id, entry_key)
```

再次抓取同一条时更新可变字段，不重复插入。

## 3. 追溯链路

一条已发布日报新闻的完整追溯路径：

```text
daily_report_items
-> generated_news
-> recommendation_items
-> dedupe_group_items
-> news_items
-> raw_items
-> data_sources
```

最重要的外键：

```text
daily_report_items.news_item_id -> news_items.id
daily_report_items.generated_news_id -> generated_news.id
daily_report_items.recommendation_item_id -> recommendation_items.id
generated_news.news_item_id -> news_items.id
recommendation_items.news_item_id -> news_items.id
dedupe_group_items.news_item_id -> news_items.id
news_items.raw_item_id -> raw_items.id
raw_items.data_source_id -> data_sources.id
```

这条链路保证：

- 被推荐后，可以查回原始抓取内容。
- 被采纳进日报后，可以查回推荐分数和推荐原因。
- 被编辑后，可以查回模型原稿、编辑版本和原始 payload。
- 导出 SQL 后，可以查回是哪条日报条目触发导出。

## 4. 编辑不覆盖原始数据

编辑层只做覆盖，不改原始数据。

建议：

- `raw_items` 永不因编辑而变化。
- `news_items` 保存标准化候选，不因日报编辑而变化。
- `generated_news` 保存模型生成稿。
- `daily_report_items` 保存日报层编辑覆盖，例如 `editor_title`、`editor_summary`、`editor_content_json`。
- 复杂版本管理使用 `content_versions`。

## 5. 版本表

```text
content_versions
id
object_type
object_id
version_number
source_type              model / editor / import
title
summary
key_points
content_json             jsonb
edited_by
created_at
change_reason
```

## 6. 审计日志

关键行为都写 `audit_logs`：

```text
audit_logs
id
actor_user_id
action
object_type
object_id
before_json              jsonb
after_json               jsonb
source_raw_item_id
source_news_item_id
created_at
```

典型动作：

- 推荐生成
- 日报采纳
- 日报剔除
- 编辑标题/摘要/正文
- 发布日报
- 导出公司 SQL
- 修改数据源配置

## 7. SQL 导出追溯

导出也要有任务表：

```text
export_jobs
id
export_type              daily / weekly / topic / manual
status
created_by
created_at

export_job_items
id
export_job_id
daily_report_item_id
news_item_id
generated_news_id
source_raw_item_id
sql_block_hash
created_at
```

这样内网 SQL 文件里的每一块，都能查回系统里的日报条目和原始 payload。
