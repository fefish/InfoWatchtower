# Reports & Editorial 报告编审发布设计

> 状态：目标态设计稿。本文是日报、周报、采信、编辑覆盖、发布、版本和编审权限的后端
> 模块事实源。多版成稿和格式注册表细节见 `docs/backend/report-renditions-design.md`。

## 1. 模块定位

Reports & Editorial 负责把推荐候选转成可发布、可编辑、可追溯的日报/周报事实。

它回答：

- 哪些条目被采信、剔除、待观察。
- 编辑修改写到哪里。
- 发布后什么能改、什么不能改。
- 日报、周报如何从同一采信事实生成多版成稿。
- 评论、评分、通知如何挂到报告对象上。

它不负责：

- 推荐分计算。
- raw/news 标准化。
- SQL 字段映射。
- 前端排版。

## 2. 分层原则

```text
raw_items                  原始事实层，不因编辑变化
news_items                 标准化候选层，不因日报编辑变化
recommendation_items       推荐快照层，不因日报编辑变化
generated_news             模型生成稿层，不因日报编辑覆盖
daily_report_items         采信事实 + 编辑覆盖层
report_renditions          成稿投影层，可重生成
export_jobs                导出任务层
```

核心不变式：

- 日报编辑不覆盖 `raw_items`。
- 日报编辑不覆盖 `generated_news`。
- `adoption_status` 属于日报/周报采信层，不属于 `news_items`。
- rendition 是投影，不是报告事实源。
- 公司 SQL 只从已发布日报采信项导出。

## 3. 领域对象

### daily_reports

```text
id
workspace_code
domain_code
day_key
status             draft / published / archived / locked
title
summary
created_by
published_by
published_at
locked_at
metadata_json
```

### daily_report_items

```text
id
daily_report_id
news_item_id
recommendation_item_id
generated_news_id
adoption_status    pending / adopted / rejected / watch
sort_order
is_headline
editor_title
editor_summary
editor_key_points
editor_content_json
editor_notes
status_reason
edited_by
edited_at
```

### weekly_reports / weekly_report_items

周报从已发布日报采信项或指定候选池聚合，保留来源日报条目链路：

```text
weekly_reports
  week_key
  status
  title
  summary                 后端生成的周报摘要段；规则投影 v1 已实现，可被后续模型摘要覆盖
  published_at/published_by
  metadata_json

weekly_report_items
  weekly_report_id
  daily_report_item_id
  generated_news_id
  adoption_status
  section_key
  sort_order
  editor overrides
```

## 4. 状态机

日报状态：

```text
draft -> published -> locked
draft -> archived
published -> archived(optional)
```

条目采信状态：

```text
pending
-> adopted
-> rejected
-> watch
```

规则：

- `draft` 可增删条目、改采信、编辑覆盖字段。
- `published` 可允许轻量修订，但必须记录版本和审计。
- `locked` 不允许改采信和编辑覆盖，只允许查看、导出和追溯。
- 已发布日报不可被 pipeline 自动覆盖。

## 5. 编辑覆盖

编辑覆盖只写报告条目：

```text
editor_title
editor_summary
editor_key_points
editor_content_json
editor_notes
```

展示优先级：

```text
editor override
-> generated_news
-> news_items
-> raw_items
```

如果需要完整版本历史，使用：

```text
content_versions
  object_type = daily_report_item / weekly_report_item / rendition
  source_type = model / editor / import
```

## 6. 采信与推荐的关系

推荐只是输入，采信是编辑决策。

```text
recommendation_items.selected
-> daily_report_items.pending/adopted
-> editorial_actions
-> feedback/source/recommendation future signals
```

规则：

- 推荐 run 不直接等于日报。
- 管理员采信/剔除应写 `editorial_actions`。
- 周报默认从已发布日报 adopted 项聚合。
- 候选池批量采信属于 Reports & Editorial，不属于 Recommendation。

## 7. 发布语义

发布时必须：

- 校验至少有 adopted 条目或允许空发布的明确策略。
- 固化 `published_at`、`published_by`。
- 生成或刷新必要 `report_renditions`。
- 写审计。
- 触发 activity event，供通知模块消费。

发布时禁止：

- 修改 raw/news。
- 修改推荐 run 快照。
- 自动把 fallback 生成稿标记为 ready。
- 自动导出公司 SQL。

## 8. 多版成稿关系

Reports & Editorial 拥有采信事实。Report Renditions 拥有成稿投影。

```text
daily_report_items
-> report_renditions(format_code=company_sql_v1 / tech_insight_v1 / custom)
```

规则：

- 删除 rendition 不影响采信。
- 重生成 rendition 不影响 `adoption_status`。
- `company_sql_v1` 成稿视图不等于 SQL 导出任务；SQL 仍走 Export Compliance。
- 周报摘要段属于后端报告事实和成稿投影，不由前端拼装。当前 v1 在创建周报草稿和编辑
  周报条目后刷新 `weekly_reports.summary`；成稿投影在 `summary_json` 写入
  `summary_text`、`key_highlights`、`top_groups` 和
  `summary_generated_by=rule_weekly_summary_v1`。后续 LLM 周报摘要模型必须复用同一字段结构。

## 9. 权限

| 操作 | 最低工作台角色 |
|---|---|
| 查看报告 | viewer |
| 评论/点赞/评分 | 按 `feedback_policy` |
| 改采信状态 | member |
| 编辑标题/摘要/正文 | member |
| 发布日报/周报 | member 或 admin，按工作台策略 |
| 管理 report format | admin |
| 锁定/归档报告 | admin/owner |
| 强制修改已发布报告 | admin/owner + 审计 |

`super_admin` 可绕过 membership，但仍写审计。

## 10. API 目标态

```text
GET  /api/daily-reports
POST /api/daily-reports
GET  /api/daily-reports/{id}
PATCH /api/daily-reports/{id}
POST /api/daily-reports/{id}/publish
POST /api/daily-reports/{id}/lock
POST /api/daily-reports/{id}/archive
POST /api/daily-reports/bulk-adopt-from-candidates
POST /api/daily-reports/bulk-reject-from-candidates

POST /api/daily-reports/{id}/items
PATCH /api/daily-report-items/{id}
DELETE /api/daily-report-items/{id}
POST /api/daily-report-items/bulk-adopt

GET  /api/weekly-reports
POST /api/weekly-reports
GET  /api/weekly-reports/{id}
POST /api/weekly-reports/{id}/publish
PATCH /api/weekly-report-items/{id}
```

## 11. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 编审状态机不完整 | draft/published/locked/archived 有明确规则 |
| 已发布后修订规则不清 | 修订写版本和审计，不静默覆盖 |
| 候选池批量操作仍需深化 | 批量采信到日报草稿、服务端筛选排序、批量剔除 v1 已完成；后续补 watch 和更完整 trace |
| 周报正文生成不足 | 周报摘要段规则投影 v1 已完成；后续补 LLM 摘要模型和整篇周报长文生成 |
| 发布通知继续深化 | 已按 `feedback_policy.notify_on_publish` 写 activity event 并通知同工作台成员；后续与归档、邮件和更多对象关注者联动 |
| 报告锁定和导出关系不清 | locked 报告可导出不可编辑 |

## 12. 验收设计

- 编辑日报条目不修改 `generated_news` 和 `raw_items`。
- 发布日报后 pipeline 重跑不会覆盖该日报。
- 采信/剔除写 `editorial_actions` 和 audit。
- 候选池批量剔除只写或更新 `daily_report_items.adoption_status=0`；如果没有已生成稿，只能创建
  `generation_status=rejected_candidate` 的 trace 占位稿，该占位稿不得进入标准公司 SQL。
- report rendition 重生成不改变采信状态。
- 已发布报告修订产生 content version。
- viewer 默认不能编辑，member/admin 按矩阵通过。
- publish 触发 activity event。
