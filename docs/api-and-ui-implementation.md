# API 与前端实现方案

本文是前后端实现专题附录。项目入口仍然是 `docs/00-system-design.md`。

目标：让后端 API、前端页面、业务对象一一对应，避免只写后端模型却没有可用看板。

## 1. API 原则

- 后端使用 FastAPI。
- 前端通过 OpenAPI 生成或维护类型安全客户端。
- 业务接口只认本地 `user_id`、角色和权限，不直接信任外部身份。
- 所有列表接口支持分页、筛选、排序。
- 所有管理操作写 `audit_logs`。
- 返回新闻、日报、需求时必须带追溯 ID，方便查回 raw/source。
- 不返回 token、cookie、password、secret、`.env` 等敏感字段。

## 2. API 分组

第一版建议 API：

```text
GET  /healthz

POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me

GET  /api/workspaces
GET  /api/workspaces/{workspace_code}/sections

GET  /api/sources?workspace_code={workspace_code}
POST /api/sources/import-legacy-seeds
POST /api/sources/{source_id}/fetch
GET  /api/data-sources/{id}
PATCH /api/data-sources/{id}
POST /api/data-sources/{id}/enable
POST /api/data-sources/{id}/disable

POST /api/ingestion/runs
GET  /api/ingestion/runs
GET  /api/ingestion/runs/{id}

GET  /api/raw-items
GET  /api/raw-items/{id}

GET  /api/news-items
GET  /api/news-items/{id}
GET  /api/dedupe-groups
GET  /api/dedupe-groups/{id}

POST /api/recommendation/runs
GET  /api/recommendation/runs
GET  /api/recommendation/runs/{id}

POST /api/daily-reports
GET  /api/daily-reports
GET  /api/daily-reports/{id}
PATCH /api/daily-reports/{id}
POST /api/daily-reports/{id}/publish
POST /api/daily-reports/{id}/items
PATCH /api/daily-report-items/{id}
DELETE /api/daily-report-items/{id}

POST /api/news-items/{id}/reactions
POST /api/news-items/{id}/ratings
GET  /api/news-items/{id}/comments
POST /api/news-items/{id}/comments
POST /api/comments/{id}/replies

GET  /api/weekly-reports
POST /api/weekly-reports
GET  /api/requirements
POST /api/requirements
PATCH /api/requirements/{id}
GET  /api/tasks
POST /api/tasks
PATCH /api/tasks/{id}

POST /api/exports/company-sql
GET  /api/exports
GET  /api/exports/{id}/download

POST /api/sync/packages/export
GET  /api/sync/packages/{package_id}/download
POST /api/sync/packages/import
GET  /api/sync/runs
GET  /api/sync/conflicts
POST /api/sync/conflicts/{id}/resolve

GET  /api/users
POST /api/users
PATCH /api/users/{id}
GET  /api/roles
PATCH /api/users/{id}/roles
GET  /api/audit-logs
```

## 3. 页面地图

第一版打开后就是工作台，不做营销首页。

第一版导航必须从后端工作台配置读取：

```text
workspaces             工作台列表
workspace_sections     当前工作台启用的页面
```

前端可以保留短期静态 fallback，但不能把工具目录、工具任务、独立专题等页面硬编码为默认可见。

```text
/login
/dashboard
/sources
/sources/:id
/ingestion-runs
/news
/recommendations
/daily-reports
/daily-reports/:id
/daily-reports/:id/edit
/weekly-reports
/requirements
/tasks
/exports
/sync
/users
/audit-logs
```

## 4. 页面职责

`/dashboard`：

- 展示今日抓取、推荐、待采信、已发布、异常源、热门板块。

`/sources`：

- 数据源列表展示共享源池，以及当前工作台是否启用该源。
- `GET /api/sources?workspace_code=...` 返回共享源池，并附带当前工作台的 `workspace_link_enabled`、`workspace_source_weight`、`workspace_daily_limit` 和抓取状态；标签策略从 `GET /api/workspaces/{workspace_code}/label-policy` 读取。
- `POST /api/sources/{source_id}/fetch` 第一版只做单源手动抓取，调用对应 adapter，把结果幂等写入 `raw_items`，并更新 `data_sources.last_fetch_at/last_success_at/last_error`。
- 数据源配置页支持工作台统一标签策略的增删改，并支持单源启停、权重和每日上限；不要在单源配置里维护标签。
- 数据源真实定义只保存一份；多个工作台复用时通过 `workspace_source_links` 配置差异。

`/sources/:id`：

- 数据源配置、抓取规则、最近 raw items、错误日志、评分趋势。

`/news`：

- 统一候选池，展示 `dedupe_groups` 的 winner，不直接展示未去重 raw 流。
- 支持按 workspace、domain、source_type、标签、推荐状态、采信状态、日期、关键词筛选。
- 候选项必须能展开同组来源、重复项、标签、推荐分、热度分和追溯链路。

`/recommendations`：

- 推荐 run、分数、推荐原因、去重组、是否进入日报。

`/daily-reports/:id`：

- 日报时间线、点赞、评分、评论、楼中楼。

`/daily-reports/:id/edit`：

- 管理员采信、剔除、排序、编辑标题/摘要/正文、发布、锁定。

`/weekly-reports`：

- 周报候选、采信、排序、草稿生成、发布。

`/requirements` 和 `/tasks`：

- 从洞察转出的内部需求和指派任务，必须可追溯到 news/raw/source。

`/exports`：

- 公司 SQL 生成、下载、导出历史、导出追溯。

`/sync`：

- 公网/内网同步包导出、导入、同步历史、冲突处理。

`/users`：

- 用户、角色、权限。

## 5. 前端状态

建议前端状态分三类：

- session store：当前用户、角色、权限。
- dictionary store：source types、domain、taxonomy、roles。
- page query state：每个列表自己的筛选、分页、排序。

不要把日报编辑草稿只存在浏览器状态。编辑动作要及时保存到后端，或者显式保存草稿。

## 6. 权限

前端可以隐藏按钮，但最终权限以后端判断为准。

第一版角色：

```text
super_admin
editor_admin
analyst
viewer
```

关键权限：

- 数据源管理。
- 日报/周报编辑发布。
- SQL 导出。
- 用户和角色管理。
- 同步包导入导出。
- 审计查看。

## 7. 第一版验收

前后端第一版验收：

- 登录后进入工作台。
- 可以导入旧种子源并在数据源页看到。
- 可以触发一次 RSS 抓取。
- 可以看到 raw_items 和 news_items。
- 可以看到去重 winner/loser。
- 可以生成推荐 run。
- 可以生成日报草稿。
- 管理员可以编辑并发布日报。
- 用户可以点赞、评分、评论和回复。
- 管理员可以导出公司 SQL。
- 可以生成公网到内网同步包，并在内网导入。
- 所有关键操作能在 audit logs 查到。
