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

第一版当前 API：

```text
GET  /healthz

POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me

GET  /api/workspaces
POST /api/workspaces
GET  /api/workspaces/{workspace_code}/sections
GET  /api/workspaces/{workspace_code}/label-policy
PATCH /api/workspaces/{workspace_code}/label-policy

GET  /api/sources?workspace_code={workspace_code}
POST /api/sources
PATCH /api/sources/{source_id}
PATCH /api/sources/{source_id}/workspace-link
POST /api/sources/import-legacy-seeds
POST /api/sources/import-tech-insight-loop
POST /api/sources/{source_id}/fetch

POST /api/ingestion/runs
GET  /api/ingestion/runs
GET  /api/ingestion/runs/{id}
POST /api/ingestion/backfill-runs
GET  /api/ingestion/coverage

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
POST /api/daily-reports/{id}/regenerate-generated-news
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
GET  /api/weekly-reports/{id}
POST /api/weekly-reports/{id}/publish
PATCH /api/weekly-report-items/{id}

GET  /api/historical-reports/summary
GET  /api/historical-reports
GET  /api/historical-reports/{id}
GET  /api/legacy-import/summary
GET  /api/legacy-import/gaps
GET  /api/entity-timeline/summary
GET  /api/tracked-entities
GET  /api/entity-milestones
GET  /api/entity-milestones/{id}

GET  /api/requirements
POST /api/requirements
PATCH /api/requirements/{id}
GET  /api/topic-tasks
POST /api/topic-tasks
PATCH /api/topic-tasks/{id}

POST /api/exports/company-sql/daily-reports/{daily_report_id}
GET  /api/exports
GET  /api/exports/{id}
GET  /api/exports/{id}/trace

GET  /api/sync-runs
POST /api/sync-runs
POST /api/sync/packages/export
GET  /api/sync/packages/{package_id}/download
POST /api/sync/packages/import

GET  /api/users
POST /api/users
PATCH /api/users/{id}
GET  /api/roles
PATCH /api/users/{id}/roles
GET  /api/audit-logs
```

`POST /api/ingestion/runs` 支持 `concurrency` 和 `source_timeout_seconds`，用于几百个源的并发抓取和慢源隔离；默认值来自 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`。`POST /api/ingestion/backfill-runs` 支持 `rss_window/paper_api/archive_page/sitemap/manual_import` 模式；第一版仍只承诺把补采结果先写入 `raw_items`，后续复用标准化、去重、推荐和日报链路。

`POST /api/workspaces` 是工作台自助扩展入口（super_admin）：按 `code/name/description/workspace_type/default_domain_code` 创建新工作台，自动注册全部核心页面分区、默认标签策略（`ai_sql_categories`，可随后用 label-policy 接口改成工作台自己的口径）和超管 owner 成员。启动 seed 只维护内置 `planning_intel/ai_tools`，不会停用或覆盖自建工作台。契约见 `config/contracts/workspace_model.json` 的 `workspace_creation`。

`POST /api/sources` 是自建信息源入口（super_admin）：`workspace_code + name + source_type(rss/paper_rss/page_manual/page_monitor) + url` 创建共享池源并自动在该工作台启用；同 URL 源默认复用而不是重复创建（`reuse_existing=false` 时返回 409），响应为 `{source, created}`。`PATCH /api/sources/{source_id}` 编辑源定义（名称/URL/启用/回溯天数）；给 `metadata_only/needs_entry` 治理记录补 URL 会清除待补入口标记并写 `fetch_entry_status=manual_entry_added`。契约见 `config/contracts/source_fields.json` 的 `custom_source_api`。早期文档中的 `/api/data-sources/*` 端点从未实现，已由上述端点取代。

`POST /api/sources/import-tech-insight-loop` 是第一轮融合入口，只导入 `config/seeds/tech_insight_loop/sources_full_zh.csv` 的源治理字段，不导入 Tech Insight Loop 的历史素材、报告或实体大事记。响应按 CSV 行返回 `total/fetchable/metadata_only`，按去重写入返回 `created/updated`；当前 seed 为 386 行、355 行有入口、31 行待补入口，去重后 363 个共享源。`GET /api/sources` 会额外返回 `source_tier/source_channel_type/expert_routes/metadata_only/needs_entry` 等治理字段。

`GET /api/ingestion/coverage` 按 `workspace_code + day_key + 可选 run_id` 返回目标日覆盖漏斗：启用源、本次运行源、成功/失败源、目标日 raw、news、dedupe winner、recommendation candidate/selected、generated ready 和日报采信项；每源明细同时返回 fetched、created/updated、in/out target、missing published_at、news、winner、推荐和采信计数。

同步包 v1 已实现导出、zip 下载和导入幂等骨架：`POST /api/sync/packages/export` 读取
`sync_outbox` 并写入 `sync_runs` 审计，`GET /api/sync/packages/{package_id}/download` 返回
包含 `manifest.json` 和 `records.jsonl` 的 zip，`POST /api/sync/packages/import` 写入
`sync_inbox` 做重复导入跳过和导入审计。当前导入侧不直接 upsert 业务对象，后续再补
`object_type` apply handler 和 `sync_conflicts` 处理。

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
/historical-reports
/entity-milestones
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

当前视觉基线是用户 2026-07 审批的 Apple 液态玻璃（Liquid Glass）方案，元素清单如下，后续不要在没有明确设计变更的情况下覆盖：

- 底色：多层柔光渐变（白→淡蓝灰，带蓝/紫/青彩色光晕，`background-attachment: fixed`），内容区透出底色。
- 材质：侧边栏、顶栏、滑出面板、弹窗为磨砂玻璃（`backdrop-filter: blur(28px) saturate(1.7)`）；内容卡片为半透明白（不加 blur，控制性能），统一 1px 半透明白内描边高光 + 多层柔和阴影。
- 圆角：卡片 `--radius-card: 18px`，控件 `--radius-control: 11px`，导航项/按钮/徽章胶囊化（999px）。
- 色彩：灰白中性底 + 单一强调蓝 `#0A84FF`（`--color-primary`），文本 `#1d1d1f`/`#6e6e73` 苹果灰阶；开关激活用 iOS 绿 `#34c759`；状态色克制。
- 字体：`-apple-system/SF Pro` 优先字体栈，大标题重字重 + 负字距，正文细，靠字重分层。
- 控件：胶囊按钮（主按钮蓝渐变+蓝色投影）、iOS 式开关（appearance:none 自绘）、焦点 3px 蓝色光环。
- 动效：150-250ms 缓动；卡片/按钮悬停上浮 1px + 阴影加深。
- 实现约束：主题表面样式集中在 `frontend/src/styles/base.css` 末尾的「Liquid Glass 主题层」，该层只覆盖表面属性（背景/边框/圆角/阴影/滤镜/过渡），不改布局；设计 token 全部定义在 `:root`。
- 数据源页结构保持：上方 compact stats/action bar，左侧信息流式源列表 + 右侧标签策略面板（`一级标签 / 二级标签 / 新闻结构` tab）。
- CSS 维护：同一页面布局只允许在一个位置定义最终样式；表面主题只允许在主题层覆盖一次。

如果后续要重做视觉风格，必须同时更新本节、`AGENTS.md` 和 `frontend/src/styles/base.css` 的 token 与主题层，不要只改零散 CSS。

### 3.2 当前页面实现快照

- 已完成真实页面：`/sources`、`/ingestion-runs`、`/news`、`/recommendations`、`/daily-reports`、`/weekly-reports`、`/historical-reports`、`/entity-milestones`、`/quality-archive`、`/requirements`、`/tasks`、`/exports`、`/sync`、`/users`、`/audit-logs`。
- `/sources` 已接入 Tech Insight Loop 源治理导入和展示：源等级、渠道类型、质量分、专家路由、待补入口状态会显示在信息流卡片中；`wx://` 公众号等当前没有抓取 adapter 的记录不进入默认调度。
- `/sources` 支持自建信息源：stats bar 的“新增源”打开滑出面板（名称/类型/URL/主题域/回溯天数），创建后自动在当前工作台启用；同 URL 源自动复用共享池已有定义。单源配置面板下半部分可编辑源定义（名称/URL/回溯天数），待补入口源补 URL 后即可抓取。
- 侧边栏工作台切换器下方提供“新建工作台”入口（仅 super_admin 可见）：填 code/name/描述/默认主题域即创建，自动带全部核心页面和默认标签策略，创建后切换到新工作台并跳转数据源管理页配置信息源。
- `/recommendations` 和 `/news` 已展示 `ContentScorer` 结构化准入结果：`admission_level`、`admission_score`、`admission_pool`、噪声标签、限制原因和专家路由。
- 仍是 v1 能力：周报只管理采信项和板块，不自动生成整篇周报；历史归档页只读展示 `historical_reports` 和导入验收摘要，导入验收摘要覆盖历史 raw、报告、实体、事件、历史反馈和旧任务记录，不编辑、不采信、不导出 SQL、不执行导入脚本；实体大事记页只读展示旧实体和事件时间线，不触发导入、推荐或采信；质量归档页只读展示旧反馈、质量反馈和旧任务统计，不创建当前评论/评分/抓取任务；同步页只记录同步 run，不生成同步包；SQL 导出页可生成/预览/下载，但条目级追溯和导出前字段校验还要补。
- 设计保护线：不要把已确认的浅色 indigo/slate 工作台壳、信息流式数据源列表和右侧 tab 化标签策略面板回退成深色壳、宽表格、绿色/青色主调或单源标签配置。

## 4. 页面职责

`/dashboard`：

- 展示今日抓取、推荐、待采信、已发布、异常源、热门板块。

`/sources`：

- 数据源列表展示共享源池，以及当前工作台是否启用该源。
- `GET /api/sources?workspace_code=...` 返回共享源池，并附带当前工作台的 `workspace_link_enabled`、`workspace_source_weight`、`workspace_daily_limit` 和抓取状态；标签策略从 `GET /api/workspaces/{workspace_code}/label-policy` 读取。
- `POST /api/sources/{source_id}/fetch` 第一版只做单源手动抓取，调用对应 adapter，把结果幂等写入 `raw_items`，并更新 `data_sources.last_fetch_at/last_success_at/last_error`。
- 数据源配置页支持工作台统一新闻一级/二级标签策略的增删改，并支持单源启停、权重和每日上限；单源可以展示源侧方向标签，但不能把源侧方向标签当成成品新闻 category。`ai_tools` 工作台必须展示独立的 `ai_tools_categories`，不能复用规划部的 `ai_sql_categories`。
- 数据源真实定义只保存一份；多个工作台复用时通过 `workspace_source_links` 配置差异。
- `POST /api/sources` 自建源进入共享池（`workspace_code=shared`、metadata 标记 `origin=custom`），并自动在发起工作台建立启用的 `workspace_source_links`；同 URL 源复用已有定义。`PATCH /api/sources/{source_id}` 编辑源定义，补 URL 可解除 `metadata_only/needs_entry`。
- Tech Insight Loop 源导入不会覆盖已有源的人工启用关系；同 RSS/URL 去重合并，治理字段写入 `metadata_json`，质量分写入 `source_score`。

`/historical-reports`：

- `GET /api/historical-reports/summary` 返回历史归档总数、日报/周报计数、状态计数、时间范围和未解析引用数量。
- `GET /api/historical-reports` 支持按 `workspace_code/report_type/status/start_date/end_date/q/has_unresolved_refs` 只读筛选，列表不返回完整正文。
- `GET /api/historical-reports/{id}` 返回旧报告正文、`source_refs_json` 和 `metadata_json`，用于核对旧 SQLite 原行与引用映射。
- `GET /api/legacy-import/summary` 返回历史 raw、历史日报/周报、实体、实体大事记、历史反馈、旧质量反馈和旧任务记录的实际导入数、冻结基线、引用解析缺口和覆盖率状态。
- `GET /api/legacy-import/gaps` 汇总 `historical_reports.source_refs_json.unresolved`、`entity_milestones.metadata_json.legacy_refs` 与 `historical_feedback_items.metadata_json.legacy_refs` 中未解析的旧素材/报告引用，支持按类型和数量截断查看。
- 页面只读取 `historical_reports`、`tracked_entities/entity_milestones`、`historical_feedback_items/historical_job_runs` 和导入验收统计，不触发 `scripts/tech_insight_loop_legacy_import.py --execute`、`scripts/tech_insight_loop_entity_import.py --execute` 或 `scripts/tech_insight_loop_quality_import.py --execute`，不写推荐、日报、周报采信或公司 SQL。

`/entity-milestones`：

- `GET /api/entity-timeline/summary` 返回实体数、事件数、未解析引用数、重要等级分布和时间范围。
- `GET /api/tracked-entities` 支持按 `workspace_code/domain_code/entity_type/q` 只读筛选实体列表。
- `GET /api/entity-milestones` 支持按 `workspace_code/entity_id/event_type/importance_level/board/start_date/end_date/q/has_unresolved_refs` 只读筛选事件时间线。
- `GET /api/entity-milestones/{id}` 返回事件详情、旧 `metadata_json.legacy_refs`、旧素材/报告引用解析状态和完整来源 URL。
- 页面只读取 `tracked_entities/entity_milestones`，不触发 `scripts/tech_insight_loop_entity_import.py --execute`，不写推荐、日报、周报采信或公司 SQL。当前第一版不提供事件编辑；后续如要从日报/周报沉淀实体事件，必须保留旧行和当前条目的双向追溯。

`/quality-archive`：

- `GET /api/quality-archive/summary` 返回旧反馈、旧质量反馈、旧任务记录、旧任务失败源和反馈未解析引用数量。
- `GET /api/historical-feedback-items` 支持按 `workspace_code/feedback_kind/feedback_type/q/has_unresolved_refs` 只读筛选旧反馈和旧质量反馈。
- `GET /api/historical-job-runs` 支持按 `workspace_code/job_type/status/q` 只读筛选旧任务记录。
- 页面只读取 `historical_feedback_items/historical_job_runs` 和反馈引用缺口，不执行 `scripts/tech_insight_loop_quality_import.py --execute`，不创建当前 `comments/ratings/ingestion_runs`，不写推荐、日报、周报采信或公司 SQL。

`/sources/:id`：

- 数据源配置、抓取规则、最近 raw items、错误日志、评分趋势。

`/ingestion-runs`：

- 展示工作台级抓取 run 历史、状态、处理源数量、成功/失败源、raw 新增/更新数量。
- 当前后端已提供 `POST /api/ingestion/runs`、`GET /api/ingestion/runs`、`GET /api/ingestion/runs/{id}`；scheduler/worker 已接入每日完整流水线，默认关闭自动任务，开启后执行抓取、标准化/去重、按日期推荐和日报草稿。
- 页面上线前可以通过 `limit=0` 验收 API 与权限链路，不触发真实外网抓取。
- 当前前端已提供 `/ingestion-runs` 抓取覆盖率页面，接入常规抓取、RSS 窗口历史补采、run 历史、目标日覆盖漏斗和每源详情。每次运行可查看尝试源数、成功源数、失败源数、fetched、raw created/updated；`historical_backfill` 运行额外展示目标日期窗口、in-range、out-of-range、missing published_at 和失败原因。目标日漏斗会继续串起 raw、news、dedupe winner、推荐候选、推荐选中和日报采信，用于解释“为什么 294 个源全启用但当天仍只有少量候选”，避免把抓取覆盖问题误判为推荐器漏选。
- `POST /api/ingestion/backfill-runs` 已支持 `rss_window/paper_api/archive_page/sitemap/manual_import`。`rss_window` 只能补回当前 RSS/paper RSS feed 窗口里仍存在的历史条目，不等同全站归档抓取；`paper_api` 依赖已注册 adapter；`archive_page/sitemap/manual_import` 是轻量历史恢复入口，仍需把 raw 标准化后再进入候选和日报。

`/news`：

- 统一候选池，展示 `dedupe_groups` 的 winner，不直接展示未去重 raw 流。
- 支持按 workspace、domain、source_type、标签、推荐状态、采信状态、日期、关键词筛选。
- 候选项必须能展开同组来源、重复项、标签、推荐分、热度分和追溯链路。
- 候选池第一屏必须按编辑阅读顺序呈现：标题、brief 摘要、代表来源、发布时间、重复来源数量和候选判断；`dedupe_key`、group id、rank score 等工程信息收进展开区，避免把候选池做成中间表调试页。
- 当前后端已提供阶段 4 API：`POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups`。`GET /api/dedupe-groups` 已把 winner 对应的最近一次 recommendation trace 和 daily report trace 一起返回。前端 `/news` 已替换占位页，第一版已能以新闻卡片展示 winner、摘要、代表来源、重复来源、推荐分、推荐状态、日报采信状态和追溯 ID；工程字段仍在展开区，不作为第一屏噪声。

`/recommendations`：

- 推荐 run、分数、推荐原因、去重组、是否进入日报。
- `recommendation_items` 会持久化 `admission_level/admission_score/admission_pool/noise_types_json/reject_reasons_json/scorer_breakdown_json/expert_routes_json`，用于解释为什么某条进入日报、留在观察池或被降级。
- `POST /api/pipeline/daily-runs` 是面向 UI 和运维的完整流水线入口；`POST /api/recommendation/runs` 保留为只重跑推荐层的入口。
- 当前前端 `/recommendations` 已接入推荐 run 历史、创建推荐 run、详情分数拆解和是否进入日报；默认不勾选“同时生成日报草稿”，避免误触发报告层写入。

`/daily-reports/:id`：

- 日报时间线、点赞、评分、评论、楼中楼。
- 当前后端已提供 `GET /api/daily-reports`、`GET /api/daily-reports/{id}`、`POST /api/daily-reports/{id}/publish`、`PATCH /api/daily-report-items/{id}` 以及日报条目的点赞/评分/评论 API；前端 `/daily-reports` 已能选择日期并触发完整流水线生成日报草稿，支持正文展示、采信切换、条目编辑、点赞、评分、评论和追溯查看。
- 日报草稿支持 `POST /api/daily-reports/{id}/regenerate-generated-news` 重跑结构化生成稿。MiniMax 单条默认 45 秒超时，失败项显示 `fallback_needs_review`，可在页面上重跑，不阻塞整日报。
- 本地恢复和演示补齐可以使用 `scripts/import_company_sql_preview_to_reports.py`。脚本只接受已通过 `scripts/validate_company_sql.py` 的单日公司 SQL 预览文件，默认 dry-run，显式 `--execute` 后才把预览回填为 `raw_items/news_items/recommendation_items/generated_news/daily_report_items` 的完整追溯链路；可选 `--create-weekly --publish-weekly` 从这些已发布日报采信项生成周报。该脚本不改变公司 SQL 导出契约，也不把回填用的追溯字段写回公司 SQL。

`/daily-reports/:id/edit`：

- 管理员采信、剔除、排序、编辑标题/摘要/正文、发布、锁定。

`/weekly-reports`：

- 周报候选、采信、排序、草稿生成、发布。
- 当前后端已提供 `GET/POST /api/weekly-reports`、`GET /api/weekly-reports/{id}`、`POST /api/weekly-reports/{id}/publish` 和 `PATCH /api/weekly-report-items/{id}`。前端 `/weekly-reports` 已接入真实业务页：可按 ISO `week_key` 从已发布日报采信条目生成周报候选草稿，并按成品新闻一级标签形成周报板块。第一屏只展示板块数量、采信/候选/剔除统计、来源日期、标题、短摘要和来源域名；五段正文不在列表中展开，只在管理员点击编辑时出现，避免把周报页做成日报明细堆叠页。
- 当前周报草稿生成上限是 200 条；如果一周日报采信项超过 200 条，日报仍完整保留，周报 v1 只取前 200 条进入管理草稿，后续再补热度/反馈排序和分页/分批生成。
- 周报板块第一版直接使用 `generated_news.category`，也就是规划部 AI 十分类。后续如果需要更业务化的周报板块名称，可以在不改公司 SQL category 的前提下增加 `weekly_section_code/weekly_section_name` 映射层。
- 第一版周报只管理周报采信项，不自动生成整篇周报长文；后续再接热度/反馈排序、自动周报正文和周报导出。

`/requirements` 和 `/tasks`：

- 从洞察转出的内部需求和指派任务，必须可追溯到 news/raw/source。
- 当前已提供真实页面和 API：`GET/POST/PATCH /api/requirements`、`GET/POST/PATCH /api/topic-tasks`。第一版支持列表、创建、状态切换和审计；后续再补从日报/周报条目一键沉淀需求、任务与来源追溯。

`/exports`：

- 公司 SQL 生成、导出历史、导出追溯。第一版 API 直接返回 SQL 文本；后续如果文件很大，再补下载文件。
- 页面必须能清楚显示：导出范围是已发布日报且 `adoption_status = 2` 的条目；每条新闻生成 4 类 SQL；标准模式下 SQL category 使用 `generated_news.category` 的 AI 十分类；`content_json` 只包含 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 五段旧字段；从任意 SQL 条目能追溯回 daily item、generated news、news item、raw item 和 data source。
- 当前前端 `/exports` 已接入已发布日报选择、导出历史、SQL 生成、预览和下载；后续补复制、字段校验和逐条追溯 UI。

`/sync`：

- 公网/内网同步包导出、导入、同步历史、冲突处理。
- 当前第一版页面已接入 `GET/POST /api/sync-runs`，可以记录一次同步运行和 pending outbox 统计，用于审计与流程占位；完整同步包导出、下载、导入和冲突处理仍按 `docs/multi-environment-sync.md` 继续实现。

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
- 可以记录一次公网到内网同步 run；完整同步包生成和内网导入是下一阶段验收项。
- 所有关键操作能在 audit logs 查到。
