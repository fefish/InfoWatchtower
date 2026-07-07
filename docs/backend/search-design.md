# Search 全局检索设计

> 状态：数据库查询 v1 已实现。本文是全局检索模块事实源。顶部搜索框只有在本模块
> 后端 API、权限过滤、runtime capability、前端结果面板和测试完成后才能显示。
> 机器契约见 `config/contracts/search.json`。

## 1. 模块定位

Search 解决的是“在当前工作台中找情报对象”，不是找页面入口。

左侧导航已经覆盖所有页面，因此顶部搜索不能用于搜索菜单名。它必须检索真实业务对象，
并能跳到对象详情。

## 2. 检索对象

目标态对象：

| 类型 | 来源模块 | 跳转 |
|---|---|---|
| `daily_report` | Reports | `/daily-reports?day_key=...` |
| `daily_report_item` | Reports | 日报详情条目 |
| `weekly_report` | Reports | `/weekly-reports?week_key=...` |
| `weekly_report_item` | Reports | `/weekly-reports?report_id=...&item_id=...` |
| `news_item` | Content Pipeline | `/news?news_item_id=...` |
| `generated_news` | Reports/Generation | 日报或候选详情 |
| `data_source` | Sources | `/sources?source_id=...` |
| `tracked_entity` | Archive | `/entity-milestones?entity_id=...` |
| `entity_milestone` | Archive | `/entity-milestones?milestone_id=...` |
| `historical_report` | Archive | `/historical-reports?id=...` |
| `requirement` | Strategy | `/requirements?id=...` |
| `topic_task` | Strategy | `/tasks?id=...` |
| `comment` | Collaboration | 对应日报/周报条目评论 |
| `export_job` | Export Compliance | `/exports?export_job_id=...` |
| `export_job_item` | Export Compliance | `/exports?export_job_id=...&export_job_item_id=...` |
| `report_rendition` | Reports/Renditions | `/daily-reports?report_id=...&rendition_id=...&format_code=...` 或 `/weekly-reports?...` |
| `sync_run` | Sync Conflict & Distribution | `/sync?sync_run_id=...` |
| `sync_conflict` | Sync Conflict & Distribution | `/sync?conflict_id=...` |

当前 v1 实际路由以现有前端页面为准：

- `daily_report`：`/daily-reports?report_id=...`
- `daily_report_item`：`/daily-reports?item_id=...`
- `weekly_report`：`/weekly-reports?report_id=...`
- `weekly_report_item`：`/weekly-reports?report_id=...&item_id=...`
- `news_item`：`/news?news_item_id=...`
- `data_source`：`/sources/{id}`
- `tracked_entity`：`/entity-milestones?entity_id=...`
- `entity_milestone`：`/entity-milestones?milestone_id=...`
- `historical_report`：`/historical-reports?id=...`
- `requirement`：`/requirements?requirement_id=...`
- `topic_task`：`/tasks?task_id=...`
- `comment`：`/daily-reports?item_id=...&comment_id=...`
- `export_job`：`/exports?export_job_id=...`
- `export_job_item`：`/exports?export_job_id=...&export_job_item_id=...`
- `report_rendition`：日报 `/daily-reports?report_id=...&rendition_id=...&format_code=...`；
  周报 `/weekly-reports?report_id=...&rendition_id=...&format_code=...`
- `sync_run`：`/sync?sync_run_id=...`
- `sync_conflict`：`/sync?conflict_id=...`

## 3. 权限过滤

检索结果必须同时满足：

- 当前用户有 workspace membership。
- object 所属 `workspace_code` 在当前工作台或用户可访问范围内。
- `visibility_scope` 允许当前用户查看。
- 部署形态允许该对象出现。
- 对评论、任务等用户相关对象执行额外权限过滤。
- `sync_run` 和 `sync_conflict` 是实例级运维对象，只允许 `super_admin` 搜索；显式搜索这些类型时
  非管理员返回 403，默认全类型搜索时对非管理员抑制该类型。

Search API 不能返回用户无权访问的标题摘要，再依赖详情页拦截。

## 4. API 设计

目标 API：

```text
GET /api/search
  q=...
  workspace_code=planning_intel
  types=daily_report_item,news_item,data_source
  limit=20
  cursor=...
```

返回：

```json
{
  "query": "agent",
  "workspace_code": "planning_intel",
  "results": [
    {
      "object_type": "daily_report_item",
      "object_id": "123",
      "title": "示例标题",
      "summary": "命中摘要",
      "matched_fields": ["title", "summary"],
      "highlight": "...",
      "route": "/daily-reports?day_key=2026-07-05&item_id=123",
      "score": 0.86,
      "updated_at": "2026-07-05T09:00:00Z"
    }
  ],
  "next_cursor": null
}
```

错误语义：

- 空 `q` 返回 422。
- 无 workspace 权限返回 403。
- 当前部署形态禁用某类型时，该类型不返回。

## 5. 实现阶段

### 阶段 1：数据库查询

状态：已实现。

使用 PostgreSQL full-text 或受控 ILIKE 查询，覆盖：

- reports。
- report items。
- data sources。
- requirements/tasks。
- historical reports/entities。

适合第一版，不引入额外服务。

当前 v1 使用受控 ILIKE 查询，覆盖：

- `daily_reports`、`daily_report_items`、`weekly_reports`、`weekly_report_items`。
- `news_items`、`generated_news`。
- 当前工作台启用的 `data_sources`。
- `tracked_entities`、`entity_milestones`、`historical_reports`。
- `requirements`、`topic_tasks`。
- 日报条目评论 `comments`。
- `export_jobs`、`export_job_items`。
- `report_renditions`。
- `sync_runs`、`sync_conflicts`（仅 super_admin）。

权限门禁：

- API 入口先执行 workspace viewer membership 检查。
- 每类对象查询前限定 `workspace_code`；数据源通过 `workspace_source_links`
  限定当前工作台已启用源；评论通过日报条目回到当前工作台。
- `DEPLOY_MODE=intranet` 或其他关闭采集能力的形态不返回 `data_source` 结果。
- `sync_run` 和 `sync_conflict` 沿用同步运维页面的全局管理员权限，不按 workspace viewer 放开。

### 阶段 2：索引表

新增 `search_documents`：

```text
object_type
object_id
workspace_code
visibility_scope
title
body
tags_json
route
updated_at
content_hash
```

由业务事件更新索引，避免每次跨表扫描。

### 阶段 3：专用搜索引擎

如数据量明显增大，可接 OpenSearch/Meilisearch。此阶段仍要保留权限后过滤和索引脱敏。

## 6. 前端体验

顶部搜索恢复条件：

- `GET /api/meta/runtime` 表明 search capability 可用。
- `GET /api/search` 完成权限过滤。
- 有搜索结果面板或 `/search` 页面承接。
- 有空态、错误态、加载态。
- 有组件测试；后续补 Playwright 关键旅程 E2E。

搜索行为：

- 输入 2 个以上字符才触发。
- v1 结果按对象类型分组，展示对象类型 badge。
- 输入框支持上下键移动、回车打开当前选中结果、ESC 关闭面板。
- 空搜索框聚焦时展示最近打开的搜索结果；该记录只存在浏览器本地，并按 `user_id + workspace_code`
  隔离，不调用后端搜索 API。
- 每条结果显示对象类型、标题、摘要、日期。
- 点击跳转到真实对象。
- 空结果说明搜索范围和下一步。

## 7. 审计与隐私

默认不记录完整用户搜索词到审计，除非开启安全审计模式。

可以记录：

- user_id。
- workspace_code。
- result_count。
- object_types。
- latency。

不能记录敏感查询内容到普通日志。

## 8. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 索引表未做 | `search_documents` 按业务事件更新，避免跨表扫描 |
| 专用搜索引擎未做 | 数据规模上来后接 OpenSearch/Meilisearch，并保留权限后过滤 |
| E2E 证据缺失 | Playwright 覆盖搜索日报条目、数据源、权限过滤和 intranet 禁采集对象 |

## 9. 验收标准

- 搜索日报条目标题能跳到日报详情：`backend/tests/test_search_api.py`、
  `frontend/src/layouts/AppShell.spec.ts` 已覆盖。
- 搜索数据源名称能跳到数据源详情：`backend/tests/test_search_api.py` 已覆盖。
- 搜索历史报告、实体事件、候选新闻能落到页面目标对象：
  `frontend/src/pages/HistoricalReportsPage.spec.ts`、
  `frontend/src/pages/EntityMilestonesPage.spec.ts`、
  `frontend/src/pages/NewsPage.spec.ts` 已覆盖。
- 搜索周报条目、导出任务、导出 trace 条目、同步运行和同步冲突能落到页面目标对象：
  `backend/tests/test_search_api.py`、`frontend/src/pages/ExportsPage.spec.ts`、
  `frontend/src/pages/WeeklyReportsPage.spec.ts`、`frontend/src/pages/SyncRunsPage.spec.ts` 已覆盖；
  同步运行/冲突非 `super_admin` 显式搜索返回 403。
- 搜索 report rendition 能落到日报/周报成稿格式锚点：`backend/tests/test_search_api.py`、
  `frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts` 已覆盖。
- viewer 搜不到无权工作台的数据：非成员 403 已覆盖。
- intranet 搜索不到被禁用的外网采集操作对象：后端按 `capability_ingestion=false`
  抑制 `data_source` 结果；默认搜索和显式 `types=data_source` 都已由
  `backend/tests/test_search_api.py` 覆盖。
- 顶部搜索不再出现点击无效、只搜页面名的情况：AppShell 只调用 `/api/search`，
  不搜索导航菜单名。
