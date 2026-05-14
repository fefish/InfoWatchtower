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

`POST /api/ingestion/runs` 支持 `concurrency` 和 `source_timeout_seconds`，用于几百个源的并发抓取和慢源隔离；默认值来自 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`。

GET  /api/raw-items
GET  /api/raw-items/{id}

POST /api/news-items/normalize
GET  /api/news-items
GET  /api/news-items/{id}
GET  /api/dedupe-groups
GET  /api/dedupe-groups/{id}

POST /api/pipeline/daily-runs

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

POST /api/exports/company-sql/daily-reports/{daily_report_id}
GET  /api/exports
GET  /api/exports/{id}

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

当前前端设计准则：

- 使用浅色工作台壳和分组导航；导航数据来自 `workspace_sections`，不要在前端默认写死插件页。
- 主内容区用统一的工作区容器，常见桌面宽度下不应出现横向截断；占位页也必须套同一套容器。
- `/sources` 使用信息流式共享源列表，不使用笨重宽表作为第一视图。
- `/sources` 的右侧标签策略是工作台级配置，不是单源配置；一级标签尽量完整露出，不依赖难发现的内部滚动条。窄屏时标签策略可移动到列表上方。
- 按钮和状态文案保持业务直觉：单源开关用“启用/停用”，不要写成“当前工作台启用”这种重复文案。

### 3.1 前端高保真基线

当前前端视觉基线来自用户确认过的高保真方案，后续不要在没有明确设计变更的情况下覆盖：

- 整体：`#f8fafc` 背景、白色侧边栏、白色主内容、slate 中性色、indigo 主色。
- 侧边栏：`IW` 方形 logo、工作台选择器、`Menu/System` 分组导航、active 项使用 indigo 浅底。
- 顶栏：紧凑白色顶栏，包含工作台名称、说明、搜索入口、通知按钮和当前用户。
- 数据源页：上方为 compact stats/action bar；主体是左侧信息流式数据源列表 + 右侧 `380px` 标签策略面板。
- 数据源列表：每个源是一行信息流卡片，显示图标、名称、URL、类型、domain、最近成功/错误；操作按钮只做配置、抓取等源级动作。
- 标签策略：右侧 panel 使用 `一级标签 / 二级标签 / 新闻结构` tab；一级/二级新闻标签属于工作台策略。`planning_intel` 的成品新闻一级标签默认来自 `config/taxonomy/news_categories.json` 的 AI 十分类；`config/taxonomy/source_tags.json` 是数据源侧方向标签，只在数据源列表和后续覆盖分析/评分先验中使用。
- 颜色：业务主按钮使用 indigo；启用状态可以使用绿色，但页面主调不能变成绿色、青色或深色。
- CSS 维护：同一页面布局只允许在一个位置定义最终样式；改 `/sources` 时要清理旧的重复选择器，避免后写规则覆盖高保真。

如果后续要重做视觉风格，必须同时更新本节、`AGENTS.md`、`frontend/src/layouts/AppShell.vue`、`frontend/src/pages/SourcesPage.vue` 和 `frontend/src/styles/base.css`，不要只改 CSS。

## 4. 页面职责

`/dashboard`：

- 展示今日抓取、推荐、待采信、已发布、异常源、热门板块。

`/sources`：

- 数据源列表展示共享源池，以及当前工作台是否启用该源。
- `GET /api/sources?workspace_code=...` 返回共享源池，并附带当前工作台的 `workspace_link_enabled`、`workspace_source_weight`、`workspace_daily_limit` 和抓取状态；标签策略从 `GET /api/workspaces/{workspace_code}/label-policy` 读取。
- `POST /api/sources/{source_id}/fetch` 第一版只做单源手动抓取，调用对应 adapter，把结果幂等写入 `raw_items`，并更新 `data_sources.last_fetch_at/last_success_at/last_error`。
- 数据源配置页支持工作台统一新闻一级/二级标签策略的增删改，并支持单源启停、权重和每日上限；单源可以展示源侧方向标签，但不能把源侧方向标签当成成品新闻 category。`ai_tools` 工作台必须展示独立的 `ai_tools_categories`，不能复用规划部的 `ai_sql_categories`。
- 数据源真实定义只保存一份；多个工作台复用时通过 `workspace_source_links` 配置差异。

`/sources/:id`：

- 数据源配置、抓取规则、最近 raw items、错误日志、评分趋势。

`/ingestion-runs`：

- 展示工作台级抓取 run 历史、状态、处理源数量、成功/失败源、raw 新增/更新数量。
- 当前后端已提供 `POST /api/ingestion/runs`、`GET /api/ingestion/runs`、`GET /api/ingestion/runs/{id}`；scheduler/worker 已接入每日完整流水线，默认关闭自动任务，开启后执行抓取、标准化/去重、按日期推荐和日报草稿。
- 页面上线前可以通过 `limit=0` 验收 API 与权限链路，不触发真实外网抓取。
- 当前前端已提供 `/ingestion-runs` 抓取覆盖率页面，接入 run 历史和安全运行入口；下一阶段要补每源覆盖详情：按日期展示启用源数、尝试抓取源数、成功源数、失败源数、每源贡献 raw 数、候选数、active winner 数和失败原因。这个页面用于解释“为什么 294 个源全启用但当天只有少量候选”，避免把抓取覆盖问题误判为推荐器漏选。

`/news`：

- 统一候选池，展示 `dedupe_groups` 的 winner，不直接展示未去重 raw 流。
- 支持按 workspace、domain、source_type、标签、推荐状态、采信状态、日期、关键词筛选。
- 候选项必须能展开同组来源、重复项、标签、推荐分、热度分和追溯链路。
- 候选池第一屏必须按编辑阅读顺序呈现：标题、brief 摘要、代表来源、发布时间、重复来源数量和候选判断；`dedupe_key`、group id、rank score 等工程信息收进展开区，避免把候选池做成中间表调试页。
- 当前后端已提供阶段 4 API：`POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups`。前端 `/news` 已替换占位页，第一版已能以新闻卡片展示 winner、摘要、代表来源、重复来源和来源排序；后续增强应把推荐分、标签、日报采信状态和追溯链路继续并入页面。

`/recommendations`：

- 推荐 run、分数、推荐原因、去重组、是否进入日报。
- `POST /api/pipeline/daily-runs` 是面向 UI 和运维的完整流水线入口；`POST /api/recommendation/runs` 保留为只重跑推荐层的入口。
- 当前前端 `/recommendations` 已接入推荐 run 历史、创建推荐 run、详情分数拆解和是否进入日报；默认不勾选“同时生成日报草稿”，避免误触发报告层写入。

`/daily-reports/:id`：

- 日报时间线、点赞、评分、评论、楼中楼。
- 当前后端已提供 `GET /api/daily-reports`、`GET /api/daily-reports/{id}`、`POST /api/daily-reports/{id}/publish`、`PATCH /api/daily-report-items/{id}` 以及日报条目的点赞/评分/评论 API；前端 `/daily-reports` 已能选择日期并触发完整流水线生成日报草稿，支持正文展示、采信切换、条目编辑、点赞、评分、评论和追溯查看。

`/daily-reports/:id/edit`：

- 管理员采信、剔除、排序、编辑标题/摘要/正文、发布、锁定。

`/weekly-reports`：

- 周报候选、采信、排序、草稿生成、发布。

`/requirements` 和 `/tasks`：

- 从洞察转出的内部需求和指派任务，必须可追溯到 news/raw/source。

`/exports`：

- 公司 SQL 生成、导出历史、导出追溯。第一版 API 直接返回 SQL 文本；后续如果文件很大，再补下载文件。
- 页面必须能清楚显示：导出范围是已发布日报且 `adoption_status = 2` 的条目；每条新闻生成 4 类 SQL；标准模式下 SQL category 使用 `generated_news.category` 的 AI 十分类；`content_json` 只包含 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 五段旧字段；从任意 SQL 条目能追溯回 daily item、generated news、news item、raw item 和 data source。
- 当前前端 `/exports` 已接入已发布日报选择、导出历史、SQL 生成、预览和下载；后续补复制、字段校验和逐条追溯 UI。

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
- 可以按日期触发完整流水线并生成日报草稿。
- 管理员可以编辑并发布日报。
- 用户可以点赞、评分、评论和回复。
- 管理员可以导出公司 SQL。
- 可以生成公网到内网同步包，并在内网导入。
- 所有关键操作能在 audit logs 查到。
