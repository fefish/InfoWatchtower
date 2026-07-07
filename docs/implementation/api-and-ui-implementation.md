# API 与前端实现方案

本文是前后端实现专题附录。项目入口仍然是 `docs/00-system-design.md`。

目标：让后端 API、前端页面、业务对象一一对应，避免只写后端模型却没有可用看板。

本文不定义前端产品形态，也不定义后端模块边界。前端页面、顶部栏和用户旅程以
`docs/product/frontend-product-design.md` 为准；逐页 PM 规格、已做/未做和测试看护以
`docs/product/page-specs/frontend-page-specs.md` 为准；后端模块边界以 `docs/backend/backend-module-design.md`
及其专题文档为准；部署同步以 `docs/deployment/deployment-topology.md` 和
`docs/deployment/multi-environment-sync.md` 为准。

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
GET  /api/workspaces/{workspace_code}/feedback-policy
PATCH /api/workspaces/{workspace_code}/feedback-policy

GET  /api/sources?workspace_code={workspace_code}
POST /api/sources
GET  /api/sources/{source_id}
PATCH /api/sources/{source_id}
PATCH /api/sources/{source_id}/workspace-link
POST /api/sources/import-legacy-seeds
POST /api/sources/import-tech-insight-loop
POST /api/sources/{source_id}/fetch

POST /api/ingestion/runs
GET  /api/ingestion/runs
GET  /api/ingestion/runs/{id}
POST /api/ingestion/runs/{id}/retry-failed-sources
POST /api/ingestion/backfill-runs
POST /api/ingestion/manual-import-preview
GET  /api/ingestion/coverage
GET  /api/ingestion/coverage/trends
GET  /api/ingestion/failed-source-retry-summary
GET  /api/ingestion/scheduler

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
POST /api/daily-reports/bulk-adopt-from-candidates
POST /api/daily-reports/bulk-reject-from-candidates
POST /api/daily-reports/{id}/items
PATCH /api/daily-report-items/{id}
DELETE /api/daily-report-items/{id}

POST /api/daily-report-items/{id}/reactions
POST /api/daily-report-items/{id}/ratings
GET  /api/daily-report-items/{id}/comments
POST /api/daily-report-items/{id}/comments
POST /api/comments/{id}/replies

GET  /api/activity-events
GET  /api/notifications
GET  /api/notifications/unread-count
POST /api/notifications/{notification_id}/read
POST /api/notifications/read-all
GET  /api/notification-preferences
PATCH /api/notification-preferences
GET  /api/object-watchers
PATCH /api/object-watchers

GET  /api/weekly-reports
POST /api/weekly-reports
GET  /api/weekly-reports/{id}
POST /api/weekly-reports/{id}/publish
PATCH /api/weekly-report-items/{id}
POST /api/daily-report-items/{id}/insights
POST /api/weekly-report-items/{id}/insights
POST /api/daily-report-items/{id}/entity-milestones
POST /api/weekly-report-items/{id}/entity-milestones
PATCH /api/entity-milestones/{id}
GET  /api/recommendation/scorer-policy
POST /api/recommendation/scorer-preview
GET  /api/insights
POST /api/insights
GET  /api/insights/{id}
PATCH /api/insights/{id}
GET  /api/strategic-implications
POST /api/strategic-implications
GET  /api/strategic-implications/{id}
PATCH /api/strategic-implications/{id}

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
POST /api/requirements/{id}/source-links
GET  /api/topic-tasks
POST /api/topic-tasks
PATCH /api/topic-tasks/{id}

GET  /api/report-formats?workspace_code={workspace_code}
POST /api/report-formats
PATCH /api/report-formats/{id}
DELETE /api/report-formats/{id}
GET  /api/daily-reports/{id}/renditions
POST /api/daily-reports/{id}/renditions/{format_code}/regenerate
GET  /api/daily-reports/{id}/renditions/{format_code}/export?target=md|html
POST /api/weekly-reports/{id}/renditions/{format_code}/regenerate
GET  /api/weekly-reports/{id}/renditions/{format_code}/export?target=md|html
GET  /api/search?types=report_rendition&q=...

POST /api/exports/company-sql/daily-reports/{daily_report_id}/preflight
POST /api/exports/company-sql/daily-reports/{daily_report_id}
GET  /api/exports
GET  /api/exports/{id}
GET  /api/exports/{id}/download
GET  /api/exports/{id}/trace

GET  /api/sync-runs
POST /api/sync-runs
GET  /api/sync/feed/manifest
GET  /api/sync/feed
POST /api/sync/pull-runs
GET  /api/sync/health
POST /api/sync/packages/export
GET  /api/sync/packages/{package_id}/download
POST /api/sync/packages/import
GET  /api/sync/conflicts
GET  /api/sync/conflicts/{id}
POST /api/sync/conflicts/{id}/resolve

GET  /api/users
POST /api/users
PATCH /api/users/{id}
GET  /api/roles
PATCH /api/users/{id}/roles
GET  /api/identity/permission-changes
POST /api/identity/permission-rollbacks
POST /api/workspaces/{workspace_code}/members
DELETE /api/workspaces/{workspace_code}/members/{user_id}
GET  /api/workspaces/{workspace_code}/auth-membership-mapping
PATCH /api/workspaces/{workspace_code}/auth-membership-mapping
GET  /api/audit-logs?workspace_code=...&action=...&object_type=...
```

2026-07-07 设计轮（体验系统轨道 + 自动化/生成轨道）已定稿、**尚未实现**的端点
增量（实现时移入上表）：

```text
# 体验系统轨道
PATCH  /api/auth/me                          # 本地账号资料自助编辑（display_name/department/email；
                                             # 外部身份 400，契约 auth_modes.json profile_self_service）
GET    /api/workspaces/discover?q=...        # 发现列表名称/描述搜索（仍只返回 internal_public）
GET    /api/workspaces/{code}/join-code      # 工作台加入码读取（admin/owner）
POST   /api/workspaces/{code}/join-code      # 生成/轮换加入码
DELETE /api/workspaces/{code}/join-code      # 停用加入码
POST   /api/workspaces/join-by-code          # 已登录用户凭码自助入台（契约 workspace_model.json join_code）

# 自动化 / 调度轨道（docs/backend/pipeline-jobs-design.md §8）
GET    /api/workspaces/{code}/schedule-policy    # 策略 + resolved 生效值 + next_run_at 预览（viewer+）
PATCH  /api/workspaces/{code}/schedule-policy    # admin+，取值域校验 422，审计 workspace.schedule_policy.update
GET    /api/pipeline/scheduler/status            # 调度心跳/下次运行/最近 run/pending retry（登录用户，按 membership 过滤）

# 生成模型 provider 轨道（docs/backend/generation-provider-design.md）
GET    /api/workspaces/{code}/generation-policy  # 策略 + resolved provider/model/key_configured（永不回显 key）
PATCH  /api/workspaces/{code}/generation-policy  # admin+，secret-like 字段 422，审计 workspace.generation_policy.update
POST   /api/generation/ping                      # super_admin/editor_admin 连通性自检，审计 generation.ping

# 模板驱动生成轨道（docs/backend/report-renditions-design.md §10）
POST   /api/report-formats/validate-template     # 模板干跑校验 + 投影/增量字段划分 + preview_item（不落库）
POST   /api/report-formats                       # body 增加 generation_template（locked/builtin 400）
PATCH  /api/report-formats/{id}                  # 同上
```

`POST /api/ingestion/runs` 支持 `concurrency`、`source_timeout_seconds` 和 `max_items_per_source`（单源条数上限，对齐 Tech Insight Loop 的单源上限行为，截断按 feed 新在前顺序）；默认值来自 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`。RSS/页面/论文 API 适配器统一使用浏览器 User-Agent（`app/adapters/base.py` 的 `BROWSER_FETCH_HEADERS`，与旧系统一致），降低站点反爬 403。`POST /api/ingestion/runs/{id}/retry-failed-sources` 只抽取原 run 中失败源，按低并发长超时重跑，并在新 run 的 `params_json.retry_of_run_id/source_ids` 中记录追溯；无失败源或失败源已停用返回 409，不生成 0 源成功记录。已注册但尚未实现的 stub adapter 会返回每源 `status=skipped_unimplemented` 和 run 汇总 `source_skipped_unimplemented`，不计入成功或失败，前端显示“尚未实现”。`POST /api/ingestion/backfill-runs` 支持 `rss_window/paper_api/archive_page/sitemap/manual_import` 模式；其中 `paper_api` 已支持 arXiv v1、OpenAlex Works v1 和 Semantic Scholar v1，历史补采会把目标日期窗口传给 adapter，并分别生成 arXiv submittedDate 查询、OpenAlex `from_publication_date/to_publication_date` filter 或 Semantic Scholar `publicationDateOrYear` filter；`manual_import` 已支持前端上传/粘贴 CSV/SQL、`POST /api/ingestion/manual-import-preview` 后端预览、逐行错误报告和 API `manual_items` 提交，后端拒绝空条目、缺归属源、非本次启用源和空内容行。第一版仍只承诺把补采结果先写入 `raw_items`，后续复用标准化、去重、推荐和日报链路。

`POST /api/workspaces` 是工作台自助扩展入口（super_admin）：按 `code/name/description/workspace_type/default_domain_code` 创建新工作台，自动注册全部核心页面分区、默认标签策略（`ai_sql_categories`，可随后用 label-policy 接口改成工作台自己的口径）和超管 owner 成员。启动 seed 只维护内置 `planning_intel/ai_tools`，不会停用或覆盖自建工作台。契约见 `config/contracts/workspace_model.json` 的 `workspace_creation`。

`GET /api/audit-logs` 遵循 `config/contracts/audit_ops.json`：不带 `workspace_code`
时仅 `super_admin` 可查全局审计；带 `workspace_code` 时仅 `super_admin` 或该工作台 admin
可查。前端 `/audit-logs` 固定传当前工作台和 `limit=80`，避免普通工作台管理员误拉全局审计。

`POST /api/sources` 是自建信息源入口（super_admin）：`workspace_code + name + source_type(rss/paper_rss/paper_api/page_manual/page_monitor) + url` 创建共享池源并自动在该工作台启用；同 URL 源默认复用而不是重复创建（`reuse_existing=false` 时返回 409），响应为 `{source, created}`。`paper_api` 当前支持 arXiv v1、OpenAlex Works v1 和 Semantic Scholar v1，URL 可使用 `https://export.arxiv.org/api/query?search_query=cat:cs.AI`、`https://api.openalex.org/works?search=artificial%20intelligence` 或 `https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence`。`PATCH /api/sources/{source_id}` 编辑源定义（名称/URL/启用/回溯天数）；给 `metadata_only/needs_entry` 治理记录补 URL 会清除待补入口标记并写 `fetch_entry_status=manual_entry_added`。契约见 `config/contracts/source_fields.json` 的 `custom_source_api`。早期文档中的 `/api/data-sources/*` 端点从未实现，已由上述端点取代。

成稿多版（renditions）遵循「一次采信，多版成稿」：`report-formats` 是工作台级格式注册表（内置 `company_sql_v1` 锁定 + `tech_insight_v1`，可注册自定义格式），renditions 端点把已采信条目投影成对应格式并支持 MD/HTML 导出；`PATCH /api/daily-report-items/{id}` 支持 `is_headline` 头条勾选。周报摘要段由后端生成：创建周报草稿和编辑周报条目后刷新 `weekly_reports.summary`，rendition `summary_json` 写入 `summary_text/key_highlights/top_groups/summary_generated_by`，前端只展示该后端摘要，不本地拼文案。设计与边界见 `docs/backend/report-renditions-design.md` 和 `config/contracts/report_renditions.json`；公司 SQL 出口不受任何格式配置影响。

`POST /api/sources/import-tech-insight-loop` 是第一轮融合入口，只导入 `config/seeds/tech_insight_loop/sources_full_zh.csv` 的源治理字段，不导入 Tech Insight Loop 的历史素材、报告或实体大事记。响应按 CSV 行返回 `total/fetchable/metadata_only`，按去重写入返回 `created/updated`；当前 seed 为 386 行、355 行有入口、31 行待补入口，去重后 363 个共享源。`GET /api/sources` 会额外返回 `source_tier/source_channel_type/expert_routes/metadata_only/needs_entry` 等治理字段。

`GET /api/sources/import-preview?catalog=legacy|tech` 是数据源导入预览入口（super_admin，只读），返回 `total/would_create/would_update/samples`。前端必须先展示预览，再由用户确认后调用 `POST /api/sources/import-legacy-seeds` 或 `POST /api/sources/import-tech-insight-loop`；`created=0` 但 `updated>0` 应显示信息态，`total=0` 应显示警告态，不得渲染成绿色成功。

`GET /api/ingestion/scheduler` 返回自动调度配置只读快照（enabled/daily_time/timezone/job_mode/day_offset/单源上限），供抓取页「自动调度」卡展示；修改需调整部署 env 的 `INGESTION_SCHEDULER_*` 并重启 scheduler。抓取页运行参数中「本次运行源数上限」留空 = 按当前工作台全部启用源真实抓取，填入值必须大于 0；`limit=0` 现在是 422 负向验收，不再代表空跑成功。发起前端 run 前必须检查当前工作台在所选源类型下是否存在启用源，没有则本地警告且不发请求；后端兜底状态为 `no_sources`。源类型为胶囊多选。`RSSHUB_BASE_URL` 配置自建 RSSHub 实例后，`rsshub.app` 前缀源 URL 在抓取时自动改走自建实例（X 等路由可用的前提）；微信公众号直连依赖旧系统同款 wx-cli 外部工具桥接，方案见能力地图 A 块。

`GET /api/ingestion/coverage` 按 `workspace_code + day_key + 可选 run_id` 返回目标日覆盖漏斗：启用源、本次运行源、成功/失败源、目标日 raw、news、dedupe winner、recommendation candidate/selected、generated ready 和日报采信项；每源明细同时返回 fetched、created/updated、in/out target、missing published_at、news、winner、推荐和采信计数。

`GET /api/ingestion/coverage/trends` 按 `workspace_code + days` 返回最近 N 天覆盖趋势：每日 run 数、最新 run、尝试/成功/失败/未实现源、fetched、raw created/updated、成功率和 Top 失败源；该接口只读，workspace viewer 可见，供 `/ingestion-runs` 诊断“最近是否持续失败或持续 0 产出”。

`GET /api/ingestion/failed-source-retry-summary` 返回失败源自动重试策略、到期 run 数、阻塞 run 数、下一次重试时间和最近待处理 run。scheduler 在 `INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED=true` 且部署形态允许采集时投递自动重试 job；job 复用现有失败源重试语义，不会绕过 adapter、workspace link 或 manual_import 限制。自动重试 job 对到期或达到最大尝试次数的 base run 生成 `ingestion.failed_source_retry_due/blocked` 站内通知，通知目标由后端解析为 `/ingestion-runs?run_id=...`。

`GET/PATCH /api/workspaces/{workspace_code}/feedback-policy` 是工作台反馈策略入口。策略保存在
`workspaces.config_json.feedback_policy`，当前控制 viewer 是否可对日报条目点赞、评分和评论；
member 及以上仍可协作。前端 `/daily-reports` 会读取该策略，当前用户只有 viewer 且策略关闭时禁用对应反馈入口；
`/users` 策略页提供该策略的可视化编辑，保存前必须确认影响范围，`viewer_can_edit` 固定发送 false。

`POST /api/workspaces/{workspace_code}/members` 和
`DELETE /api/workspaces/{workspace_code}/members/{user_id}` 是工作台成员角色维护入口；
owner 降权或移出必须传入 `confirm_dangerous_change=true`，最后一个 owner 仍由后端硬拦截。
`GET/PATCH /api/workspaces/{workspace_code}/auth-membership-mapping` 是当前工作台部门自动开通规则入口，
仅 `super_admin` 可编辑，保存到 `workspaces.config_json.auth_membership_mapping.department_workspaces`。
OIDC/header 自动建号时后端会合并部署 env 规则和该 DB 规则，同工作台取更高角色且不降级人工角色。
`GET /api/identity/permission-changes` 读取权限相关审计，把全局角色、工作台成员、
viewer 反馈策略和部门自动开通规则的 before/after 转成可读 diff；`POST /api/identity/permission-rollbacks`
按审计记录批量恢复上一版，并写 `identity.permission_rollback` 审计，最后 `super_admin` 和最后
workspace `owner` 仍由后端保护。

`GET /api/activity-events`、`GET/POST /api/notifications*` 和 `GET/PATCH /api/object-watchers`
是协作通知最小闭环入口。
日报条目点赞/评分写 activity event 但不产生逐条通知；日报条目评论写
`comment.created/comment.replied` event，并为同条目既有评论参与者、被回复人和日报条目关注者生成当前用户收件箱通知。
同步冲突创建写 `sync_conflict.created` event，并为 active super_admin 和目标工作台 owner/admin
生成 `important` 站内通知。
失败源自动重试队列到期或阻塞时会写 `ingestion.failed_source_retry_due/blocked` event，并给
`super_admin` 和目标工作台 owner/admin 生成 `important` 站内通知；同一 base run、事件类型和
attempt_count 只生成一次。
日报/周报发布在 `feedback_policy.notify_on_publish=true` 时写
`daily_report.published/weekly_report.published` event，并通知同工作台除操作者外的活跃成员；
重复发布已发布报告不会重复推送。
前端顶部铃铛只显示 `GET /api/notifications/unread-count` 返回的真实未读数；`/notifications`
页面提供未读/全部/已读、单条已读和全部已读。`GET /api/notifications` 返回
`target_label/target_path`，后端统一解析日报条目、评论、日报/周报报告、周报 item、同步冲突、抓取 run、
任务和需求目标；消息页只渲染这两个字段，不在前端本地猜路由。日报条目通知会跳转到
`/daily-reports?item_id=...&comment_id=...` 并打开对应条目、给命中评论加高亮；日报/周报发布通知会跳转到
`/daily-reports?report_id=...` 和 `/weekly-reports?report_id=...`；周报 item 通知会跳转到
`/weekly-reports?item_id=...` 并高亮条目；`PATCH /api/weekly-report-items/{id}` 发生真实采信或编辑快照变化时会生成
`weekly_report_item.updated` 通知，并通知工作台成员和周报条目关注者，消息页偏好显示为“周报条目更新提醒”；
失败源自动重试通知会跳转到 `/ingestion-runs?run_id=...` 并选中命中抓取 run；
任务指派通知会跳转到 `/tasks?task_id=...` 并高亮命中任务。日报详情抽屉和周报条目动作区已接入
`GET/PATCH /api/object-watchers`，展示真实关注状态和关注人数，不用前端本地状态模拟。
`POST /api/notifications/{id}/archive`
支持单条归档，`status=all` 列表排除归档项，`status=archived` 可单独查看。`GET/PATCH /api/notification-preferences`
按当前用户、工作台和事件类型保存站内偏好，后端生成通知前会检查 `in_app_enabled`；
`email_enabled` 当前只存储不投递。日报评论中的 `@username` 已生成 `comment.mentioned`
important 通知；需求状态变化会生成 `requirement.status_changed` 通知并跳转到
`/requirements?requirement_id=...`。协作/通知对象不进入 sync feed 已由
`backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_local_collaboration_notifications`
看护；邮件投递和更多对象通知生成/提及仍按
`docs/backend/collaboration-notification-design.md` 继续推进。

业务页面和 API 客户端必须从当前工作台状态显式传递 `workspace_code`；候选池、日报/周报、
抓取覆盖、历史报告库、实体大事记、质量归档、需求、任务和导出等页面不得依赖后端或前端
默认租户。`backend/tests/test_blueprint_page_audit.py` 会检查工作台页面在
`workspace.currentCode` 变化时重载，并拒绝裸“暂无”式空态。

同步能力已分成两条路线：主路径是 extranet `GET /api/sync/feed/manifest`/`GET /api/sync/feed`
下发、intranet `POST /api/sync/pull-runs` 或 scheduler 定时拉取；人工 fallback 是
`POST /api/sync/packages/export`、`GET /api/sync/packages/{package_id}/download` 和
`POST /api/sync/packages/import`。feed 端点只接受 `SYNC_SERVICE_TOKENS` Bearer，不走 cookie；
同步包下载已收紧为 super_admin。导入 apply handler 已覆盖
`data_sources/raw_items/news_items/generated_news/daily_reports/weekly_reports`，幂等记录在
`sync_inbox`，revision/hash 冲突写 `sync_conflicts`，`visibility_scope=restricted` 和
secret-like payload 不落库。secret-like 检测统一使用 `backend/app/core/privacy.py`，feed、
手工同步包导出、apply/import 和审计入口共享同一组字段规则；`write_audit` 写入 `detail_json`
前会把同类字段值替换为 `[REDACTED]`，避免 API/UI 对照文档只记录“不同步”而遗漏审计边界。
`GET /api/sync/health` 已提供同步健康摘要，基于 `sync_cursors`、最近 `sync_runs`
和 open `sync_conflicts` 返回缺失水位、失败水位、滞后水位、最近失败 run、open conflict
和 `ok/warning/critical/inactive` 状态；`/sync` 页面只展示该摘要，不在前端自行判断同步健康。
`GET /api/sync/conflicts` 和 `POST /api/sync/conflicts/{id}/resolve` 已提供第一版人工处置：
管理员可查看 open/resolved/ignored/retry_after_dependency 冲突、本地/传入 JSON、revision/hash 原因，
并记录 `keep_local`、`ignored`、`retry_after_dependency`、`use_incoming` 或 `manual_merge`
决策。`use_incoming` 复用对象 apply handler 接受传入版本；`manual_merge` 当前开放给
`data_sources/daily_reports/weekly_reports`，需要提交合并 JSON 并写新 revision。

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
/notifications
/historical-reports
/entity-milestones
/requirements
/tasks
/exports
/sync
/users
/audit-logs
```

`/login` 读取 `GET /api/meta/runtime.auth_mode` 后分流入口：`local/public_password`
显示本地账号密码表单，`oidc` 显示 SSO 按钮并跳转 `/api/auth/oidc/start`，
`intranet_header` 隐藏本地密码表单并提示由门户登录态接入。OIDC start/callback 失败会回跳
`/login?auth_error=<code>`，登录页展示固定友好文案。

导航按「工作角色的动作垂直」分为六组，组信息来自 `workspace_sections.config_json.group`，前端不做硬编码分组：

| 组 | 分区 | 回答的问题 |
|---|---|---|
| today 今日 | 今日速览 | 系统今天跑得怎么样、有什么等我处理 |
| collect 情报采集 | 数据源管理、抓取与覆盖 | 信息从哪来、抓没抓到 |
| curate 编审工作流 | 候选池、日报编审、周报编审 | 读什么、采信什么、发布什么 |
| library 资料库 | 历史报告库、实体大事记、质量归档 | 过去沉淀了什么（历史只读，当前事件可治理） |
| collab 协作 | 内部需求、指派任务 | 团队协作事项 |
| system 系统 | 同步、SQL导出、用户权限、审计 | 管理与运维 |

当前前端设计准则：

- 布局强约束（2026-07 定稿）：全站页面必须落位 `docs/product/frontend-product-design.md`
  §9 的四个布局模板（list/detail/dashboard/settings）与 spacing tokens，页面外边距只由
  统一页面容器提供，业务模块不得自由漂浮；逐页模板归属见
  `docs/product/page-specs/frontend-page-specs.md` §3。
- 弹窗强约束（2026-07 定稿）：只允许居中 Modal（sm/md/lg）与受限上下文面板两种弹层形态，
  规范与迁移清单见 `docs/product/frontend-product-design.md` §10 和
  `config/contracts/frontend_control_governance.json` `modal_rule`；新建工作台向导、
  发现工作台、新增信息源、导入预览待迁居中 Modal。
- 使用浅色工作台壳和分组导航；导航数据来自 `workspace_sections`，不要在前端默认写死插件页。
- 顶部搜索已恢复为真实 `/api/search` 结果面板；只检索当前工作台业务对象，不搜索左侧页面名；已覆盖类型分组、键盘选择、本地近期结果、周报条目、report rendition、导出任务/trace 条目、同步运行和同步冲突等主要对象锚点。顶部通知铃铛已恢复，但只能显示真实后端未读数。
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

- 已完成真实页面：`/sources`、`/ingestion-runs`、`/news`、`/recommendations`、`/daily-reports`、`/weekly-reports`、`/notifications`、`/historical-reports`、`/entity-milestones`、`/quality-archive`、`/requirements`、`/tasks`、`/exports`、`/sync`、`/users`、`/audit-logs`。
- `/sources` 已接入 Tech Insight Loop 源治理导入和展示：源等级、渠道类型、质量分、专家路由、待补入口状态会显示在信息流卡片中；`wx://` 公众号等当前没有抓取 adapter 的记录不进入默认调度。
- `/sources` 支持自建信息源：stats bar 的“新增源”打开滑出面板（名称/类型/URL/主题域/回溯天数），创建后自动在当前工作台启用；同 URL 源自动复用共享池已有定义。单源配置面板下半部分可编辑源定义（名称/URL/回溯天数），待补入口源补 URL 后即可抓取。
- 侧边栏工作台切换器下方提供“新建工作台”入口（仅 super_admin 可见）：填 code/name/描述/默认主题域即创建，自动带全部核心页面和默认标签策略，创建后切换到新工作台并跳转数据源管理页配置信息源。
- `/recommendations` 和 `/news` 已展示 `ContentScorer` 结构化准入结果：`admission_level`、`admission_score`、`admission_pool`、噪声标签、限制原因和专家路由。
- `/news` 已消费 `news_item_id` 搜索锚点并高亮命中候选组；`/historical-reports` 已消费 `id`
  搜索锚点；`/entity-milestones` 已消费 `entity_id` / `milestone_id` 搜索锚点。
- `/daily-reports` 和 `/weekly-reports` 已消费 `report_id + rendition_id + format_code` 搜索锚点，
  可定位到对应日报/周报成稿格式；日报页高亮成稿视图，周报页高亮成稿导出入口。
- `/exports` 已消费 `export_job_id` 搜索锚点并自动加载导出追溯；`/sync` 已消费
  `conflict_id` 锚点并高亮 open conflict。
- 仍是 v1 能力：周报可生成后端摘要段和管理采信项/板块，但不自动生成整篇周报长文；历史归档页只读展示 `historical_reports` 和导入验收摘要，导入验收摘要覆盖历史 raw、报告、实体、事件、历史反馈和旧任务记录，不编辑、不采信、不导出 SQL、不执行导入脚本；实体大事记页对旧导入实体和事件保持只读，对 `legacy_system=current` 的当前事件支持编辑、确认、撤销和转需求，但不触发导入、推荐或采信；质量归档页只读展示旧反馈、质量反馈和旧任务统计，并允许管理员把单条历史反馈转成 requirement 来源，不创建当前评论/评分/抓取任务；同步页已接 runtime role capability，外网发布者可导出手工同步包，内网消费者可触发立即拉取，open conflict 可人工处置；SQL 导出页已接预检、生成/预览/复制、截断预览保护、服务端流式下载、trace 锚点和 trace 字段来源详情。
- `/dashboard` 已重做为晨报式「今日速览」：流水线漏斗 hero、头条候选、报告/趋势侧栏、源健康和快捷入口；导航按 today/collect/curate/library/collab/system 六组垂直分组渲染。
- 响应式基线：≥1440 舒适布局；≤1120 侧栏坍缩为 76px 图标栏（图标带 title 提示），顶栏出现工作台切换下拉；≤860 主内容单列堆叠。顶部搜索在 `capabilities.search=true` 时渲染真实搜索面板。字号与间距用 clamp 流式收缩。
- 设计保护线：不要把已确认的液态玻璃壳、信息流式数据源列表和右侧 tab 化标签策略面板回退成深色壳、宽表格、绿色/青色主调或单源标签配置。

## 4. 页面职责

`/dashboard`（今日速览，晨报式首页）：

- 只读速览页，不做任何写操作；10 秒内回答「系统今天跑得怎么样、有什么等我处理、最近产出了什么」。
- Hero 区：日期 + 今日情报流水线漏斗（启用源 → 抓取成功 → 今日新增 → 去重代表 → 推荐候选 → 已采信 → 日报状态），数据来自 `GET /api/ingestion/coverage?day_key=今天`。
- 主区左：今日头条候选 Top6（去重代表 + 准入等级彩色徽章 + 推荐分 + 多源报道数），来自 `GET /api/dedupe-groups` 按 `final_score` 排序；点击去候选池。
- 主区右：最新日报卡（日期、状态、采信数、分类分布、进入编审）、最新周报卡、近七日采信趋势条（来自日报列表逐日条目数，已发布高亮）。
- 底部：源健康（失败源 Top3 + 待补入口提醒，链接数据源管理）与快捷入口（抓取与覆盖 / 新增信息源 / SQL 导出）。
- 空状态给动作引导（例如「先跑一次抓取 →」），不出现无信息的大数字卡。

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
- 历史报告详情页的“转需求”只写当前 `requirements` 与
  `requirement_source_links.historical_report_id`；`POST /api/requirements` 支持
  `source_historical_report_id`，需求/任务来源可跳回 `/historical-reports?id=...`。

`/entity-milestones`：

- `GET /api/entity-timeline/summary` 返回实体数、事件数、未解析引用数、重要等级分布和时间范围。
- `GET /api/tracked-entities` 支持按 `workspace_code/domain_code/entity_type/q` 只读筛选实体列表。
- `GET /api/entity-milestones` 支持按 `workspace_code/entity_id/event_type/importance_level/board/start_date/end_date/q/has_unresolved_refs` 只读筛选事件时间线。
- `GET /api/entity-milestones/{id}` 返回事件详情、旧 `metadata_json.legacy_refs`、旧素材/报告引用解析状态和完整来源 URL。
- `PATCH /api/entity-milestones/{id}` 只允许 workspace admin 编辑 `legacy_system=current` 的当前事件；
  可更新标题、摘要、影响、来源、板块、重要性、精选状态和 `curation_status=draft|confirmed|revoked`。
  旧系统导入事件不可编辑。
- `POST /api/daily-report-items/{id}/entity-milestones` 和
  `POST /api/weekly-report-items/{id}/entity-milestones` 可从当前日报/周报条目登记实体事件；
  后端复用或创建 `legacy_system=current` 的 tracked entity，并在
  `entity_milestones.metadata_json.current_refs` 保存 report item、generated news、news、raw 和 data source 追溯。
- `/entity-milestones` 页面只读取 `tracked_entities/entity_milestones`，不触发
  `scripts/tech_insight_loop_entity_import.py --execute`，不写推荐、日报、周报采信或公司 SQL。
  旧导入事件保持只读；当前事件登记入口在 `/daily-reports` 和 `/weekly-reports`，治理入口在
  `/entity-milestones`。

`/quality-archive`：

- `GET /api/quality-archive/summary` 返回旧反馈、旧质量反馈、旧任务记录、旧任务失败源和反馈未解析引用数量。
- `GET /api/historical-feedback-items` 支持按 `workspace_code/feedback_kind/feedback_type/q/has_unresolved_refs` 只读筛选旧反馈和旧质量反馈。
- `GET /api/historical-job-runs` 支持按 `workspace_code/job_type/status/q` 只读筛选旧任务记录。
- 页面只读取 `historical_feedback_items/historical_job_runs` 和反馈引用缺口，不执行 `scripts/tech_insight_loop_quality_import.py --execute`，不创建当前 `comments/ratings/ingestion_runs`，不写推荐、日报、周报采信或公司 SQL。
- 管理员“转需求”只调用 `POST /api/requirements`，写入 `source_historical_feedback_item_id`
  和 `requirement_source_links.historical_feedback_item_id`；需求/任务来源可跳回
  `/quality-archive?feedback_id=...`，该动作不修改历史反馈原文。

`/sources/:id`：

- `GET /api/sources/{id}?workspace_code=...` 返回单源安全详情投影：`source`、raw/news 累计、
  最近 raw、最近 run、错误日志和 raw 趋势；不返回 `raw_payload_json`、`fetch_config`、
  `paper_config` 或 `credential_ref`。
- 前端展示工作台启用关系、权重、日限、抓取状态、raw/news 累计、raw 趋势、错误日志和最近 raw；
  read-only 部署隐藏抓取按钮，抓取动作使用 workspace-scoped `POST /api/sources/{id}/fetch`。
- 后续再补推荐评分贡献和采信贡献趋势。

`/ingestion-runs`：

- 展示工作台级抓取 run 历史、状态、处理源数量、成功/失败源、raw 新增/更新数量。
- 当前后端已提供 `POST /api/ingestion/runs`、`GET /api/ingestion/runs`、`GET /api/ingestion/runs/{id}` 和 `POST /api/ingestion/runs/{id}/retry-failed-sources`；scheduler/worker 已接入每日完整流水线，默认关闭自动任务，开启后执行抓取、标准化/去重、按日期推荐和日报草稿。
- 页面上线前应通过 `limit=0` 负向用例验收 422，通过“所选源类型无启用源”验收 `no_sources` 警告，不再把空跑当成功。
- 当前前端已提供 `/ingestion-runs` 抓取覆盖率页面，接入常规抓取、RSS 窗口历史补采、arXiv paper API 补采、manual_import 上传/粘贴 CSV/SQL、后端预览、错误报告下载、run 历史、目标日覆盖漏斗、近 14 日覆盖趋势、Top 失败源、每源详情、失败源手动重试、自动重试策略摘要和通知 run 锚点。每次运行可查看尝试源数、成功源数、失败源数、fetched、raw created/updated；有失败源的 run 可只重试失败源，重试后自动选中新 run；自动重试开启后由 scheduler 按退避策略处理到期 run，并在到期/阻塞时生成站内告警。`historical_backfill` 运行额外展示目标日期窗口、in-range、out-of-range、missing published_at 和失败原因。目标日漏斗和长期趋势会继续串起 raw、news、dedupe winner、推荐候选、推荐选中和日报采信，用于解释“为什么 294 个源全启用但当天仍只有少量候选”，避免把抓取覆盖问题误判为推荐器漏选。
- `POST /api/ingestion/backfill-runs` 已支持 `rss_window/paper_api/archive_page/sitemap/manual_import`。`rss_window` 只能补回当前 RSS/paper RSS feed 窗口里仍存在的历史条目，不等同全站归档抓取；`paper_api` 当前支持 arXiv API submittedDate 日期窗口查询、OpenAlex Works API publication_date 日期窗口查询和 Semantic Scholar publicationDateOrYear 日期窗口查询，OpenReview 等 provider 仍待补；`archive_page/sitemap/manual_import` 是轻量历史恢复入口，`manual_import` v1 要求预览 accepted row 归属到已启用源并保留原始 payload，仍需把 raw 标准化后再进入候选和日报。

`/news`：

- 统一候选池，展示 `dedupe_groups` 的 winner，不直接展示未去重 raw 流。
- 支持按 workspace、domain、source_type、标签、推荐状态、采信状态、日期、关键词筛选。
- 候选项必须能展开同组来源、重复项、标签、推荐分、热度分和追溯链路。
- 候选池第一屏必须按编辑阅读顺序呈现：标题、brief 摘要、代表来源、发布时间、重复来源数量和候选判断；`dedupe_key`、group id、rank score 等工程信息收进展开区，避免把候选池做成中间表调试页。
- 当前后端已提供阶段 4 API：`POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups`。`GET /api/dedupe-groups` 已把 winner 对应的最近一次 recommendation trace、daily report trace 和安全 `lineage.nodes` 一起返回；lineage 以 `data_source -> raw_item -> news_item -> dedupe_group -> recommendation_item -> generated_news -> daily_report_item` 串起候选追溯，每个节点带 `review_note` 说明复核含义，raw 层只返回 payload keys、entry key、source URL、时间和内容长度，不返回完整 `raw_payload_json`、credential 或 fetch config。接口支持关键词、推荐状态、日报状态、准入等级、来源类型筛选和推荐分/发布时间/来源数排序。`POST /api/daily-reports/bulk-adopt-from-candidates` 支持把已有推荐链的 dedupe winner 批量加入或恢复采信到目标日报草稿，`POST /api/daily-reports/bulk-reject-from-candidates` 支持把已有推荐链候选写入或更新为 `adoption_status=0`；缺少推荐链的候选会返回 skipped，不绕过推荐直接进日报。`GET/PATCH /api/object-watchers` 已支持 `dedupe_group`，候选被批量采信/剔除后会生成 `dedupe_group.adoption_changed` 站内通知并跳回 `/news?dedupe_group_id=...`。前端 `/news` 已替换占位页，第一版已能以新闻卡片展示 winner、摘要、代表来源、重复来源、推荐分、推荐状态、日报采信状态和带业务解释的完整 trace 链，并支持筛选/排序、选择候选后批量采信或剔除到指定日报日期、候选关注、`news_item_id/raw_item_id/dedupe_group_id` 锚点和通知锚点；工程字段仍在展开区，不作为第一屏噪声。

`/recommendations`：

- 推荐 run、分数、推荐原因、去重组、是否进入日报。
- `recommendation_items` 会持久化 `admission_level/admission_score/admission_pool/noise_types_json/reject_reasons_json/scorer_breakdown_json/expert_routes_json`，用于解释为什么某条进入日报、留在观察池或被降级。
- `GET /api/recommendation/scorer-policy` 提供只读评分策略摘要，前端展示配置版本、阈值、日报/周报准入层、权重、主题和噪声规则摘要，不在前端硬编码评分规则。
- `POST /api/recommendation/scorer-preview` 提供管理员单条候选评分预览，复用后端 content admission scorer，返回准入等级、噪声、专家路由和分数拆解，标记 `persistence=not_persisted`，不创建 recommendation run 或日报草稿。
- `GET /api/recommendation/runs/{id}` 返回每条 recommendation item 的最新 `daily_report` trace；`/recommendations` 的观察池复核面板从当前 run 筛出未入选 P2/P3，并调用 `POST /api/daily-reports/bulk-adopt-from-candidates` 或 `POST /api/daily-reports/bulk-reject-from-candidates` 写入日报草稿后回显已采信/已剔除。
- `POST /api/pipeline/daily-runs` 是面向 UI 和运维的完整流水线入口；`POST /api/recommendation/runs` 保留为只重跑推荐层的入口。
- 当前前端 `/recommendations` 已接入推荐 run 历史、创建推荐 run、评分策略摘要、单条评分预览、P2/P3 观察池复核、详情分数拆解和是否进入日报；默认不勾选“同时生成日报草稿”，避免误触发报告层写入。

`/daily-reports/:id`：

- 日报时间线、点赞、评分、评论、楼中楼。
- 当前后端已提供 `GET /api/daily-reports`、`GET /api/daily-reports/{id}`、`POST /api/daily-reports/{id}/publish`、`PATCH /api/daily-report-items/{id}` 以及日报条目的点赞/评分/评论 API；前端 `/daily-reports` 已能选择日期并触发完整流水线生成日报草稿，支持正文展示、采信切换、条目编辑、点赞、评分、评论和追溯查看。
- viewer 点赞、评分、评论由当前工作台 `feedback_policy` 控制；策略关闭时前端禁用入口，后端仍以 403 兜底。
- 日报草稿支持 `POST /api/daily-reports/{id}/regenerate-generated-news` 重跑结构化生成稿。MiniMax 单条默认 45 秒超时，失败项显示 `fallback_needs_review`，可在页面上重跑，不阻塞整日报。
- 本地恢复和演示补齐可以使用 `scripts/import_company_sql_preview_to_reports.py`。脚本只接受已通过 `scripts/validate_company_sql.py` 的单日公司 SQL 预览文件，默认 dry-run，显式 `--execute` 后才把预览回填为 `raw_items/news_items/recommendation_items/generated_news/daily_report_items` 的完整追溯链路；可选 `--create-weekly --publish-weekly` 从这些已发布日报采信项生成周报。该脚本不改变公司 SQL 导出契约，也不把回填用的追溯字段写回公司 SQL。

`/daily-reports/:id/edit`：

- 管理员采信、剔除、排序、编辑标题/摘要/正文、发布、锁定。

`/weekly-reports`：

- 周报候选、采信、排序、草稿生成、发布。
- 当前后端已提供 `GET/POST /api/weekly-reports`、`GET /api/weekly-reports/{id}`、`POST /api/weekly-reports/{id}/publish` 和 `PATCH /api/weekly-report-items/{id}`。前端 `/weekly-reports` 已接入真实业务页：可按 ISO `week_key` 从已发布日报采信条目生成周报候选草稿，并按成品新闻一级标签形成周报板块。第一屏只展示板块数量、采信/候选/剔除统计、来源日期、标题、短摘要和来源域名；五段正文不在列表中展开，只在管理员点击编辑时出现，避免把周报页做成日报明细堆叠页。
- 创建周报草稿和编辑周报条目后，后端刷新 `weekly_reports.summary`；前端详情区展示该摘要段，成稿导出在 Markdown/HTML 头部展示摘要、板块分布和关键亮点。
- 当前周报草稿生成上限是 200 条；如果一周日报采信项超过 200 条，日报仍完整保留，周报 v1 只取前 200 条进入管理草稿，后续再补热度/反馈排序和分页/分批生成。
- 周报板块第一版直接使用 `generated_news.category`，也就是规划部 AI 十分类。后续如果需要更业务化的周报板块名称，可以在不改公司 SQL category 的前提下增加 `weekly_section_code/weekly_section_name` 映射层。
- 第一版周报只管理周报采信项并生成摘要段，不自动生成整篇周报长文；后续再接热度/反馈排序、LLM 周报摘要模型和自动周报正文。

`/insights`、`/requirements` 和 `/tasks`：

- 从洞察转出的内部需求和指派任务，必须可追溯到 news/raw/source。
- 当前 `/insights` 已接入真实 insight/strategic implication 独立管理：可列表、创建、编辑、
  确认/归档洞察，创建/编辑战略影响，并展示 source title、source URL 和 data source name。
  viewer 可读，member+ 可编辑。
- 当前已提供真实页面和 API：`GET/POST/PATCH /api/requirements`、
  `POST /api/requirements/{id}/source-links`、`GET/POST/PATCH /api/topic-tasks`。
  第一版支持列表、创建、owner/负责人、状态切换、审计、任务指派通知和需求状态通知；
  requirement source links v1 已能从 daily/weekly report item、entity milestone、historical report、
  news 或 raw 追加证据，并在 `/requirements` 展示 source title、source URL、data source name
  和可定位对象链接。report item strategy
  loop v1 已接入 `POST /api/daily-report-items/{id}/insights` 和
  `POST /api/weekly-report-items/{id}/insights`，日报/周报页管理员可从条目沉淀 insight、
  implication 和 requirement，后端支持 `create_task=true` 同步创建 task；`/tasks` 已展示
  requirement/source trace 链接，并支持全部/我的/逾期/阻塞视图、`is_overdue` 提示、
  `blocked_reason` 提交和批量任务处理；批量处理调用 `POST /api/topic-tasks/batch`，只更新
  `status/blocked_reason`，workspace admin 可处理当前工作台任务，被指派人只能处理自己名下任务。
  任务详情 v1 已接入 `GET /api/topic-tasks/{id}` 和 `/tasks` 只读详情抽屉，可展示任务、
  需求和来源证据，并跳回 report item/news/raw 锚点。实体事件登记 v1 已接入
  `POST /api/daily-report-items/{id}/entity-milestones` 和
  `POST /api/weekly-report-items/{id}/entity-milestones`，日报/周报页 workspace member
  可输入实体名，从条目登记 `entity_milestones` 并保留 current refs。实体事件治理 v1 已接入：
  `/entity-milestones` 对当前事件支持编辑、确认、撤销和转需求；`POST /api/requirements`
  支持 `source_entity_milestone_id`；`/historical-reports` 支持从旧报告创建 requirement，并通过
  `source_historical_report_id` 保留来源；`/quality-archive` 支持从旧反馈/质量反馈创建 requirement，并通过
  `source_historical_feedback_item_id` 保留来源；任务/需求来源可跳回实体事件、历史报告或历史反馈。需求结论反哺推荐 v1 已接入：`/requirements` 可提交
  `metadata_json.recommendation_feedback`，后端写
  `EditorialAction(requirement.feedback_to_recommendation)`，推荐 run 后续读入
  `feedback_score/recommendation_reason`。后续再补跨对象联动体验和更多协作对象解释关系。

`/exports`：

- 公司 SQL 生成、导出历史、服务端流式下载和导出追溯。生成 API 返回有大小上限的 SQL 预览；
  历史和生成后下载统一走 `GET /api/exports/{id}/download`，workspace viewer 不能下载 SQL 文件。
- 页面必须能清楚显示：导出范围是已发布日报且 `adoption_status = 2` 的条目；每条新闻生成 4 类 SQL；标准模式下 SQL category 使用 `generated_news.category` 的 AI 十分类；`content_json` 只包含 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 五段旧字段；从任意 SQL 条目能追溯回 daily item、generated news、news item、raw item 和 data source。
- 当前前端 `/exports` 已接入已发布日报选择、导出历史、导出前 preflight 摘要、SQL 生成、预览、复制、服务端流式下载、批量 manifest、trace 锚点和导入回执；preflight 会展示 report/item 级错误与提醒，覆盖未发布、fallback、缺字段、URL、HTML 清洗/污染和 created_at 渲染。生成响应会展示完整 SQL 文件大小和预览大小，`sql_text_truncated=true` 时禁用复制预览并提示使用下载端点。批量入口可勾选多份已发布日报，展示 manifest 汇总、逐日成功/失败和成功日下载入口。trace 行可展示 SQL 片段、标题/摘要/关键点来源、五段正文来源、编辑覆盖字段，以及导出/编辑/生成/raw 字段差异预览。导入回执区可查看最新导入状态，登记 `pending/imported/failed/partial`、目标系统、导入/失败语句数、失败 SQL 序号/表、错误码和错误原因，并展示 `POST /api/exports/{id}/import-receipts/callback` 给内网 importer 配置；回调接口走 `SYNC_SERVICE_TOKENS` Bearer token，不展示 token。后续补真实内网平台生产联调证据。

`/sync`：

- 公网/内网同步包导出、导入、同步历史、冲突处理。
- 当前页面已接入同步包导出/下载/导入、feed/pull 运行记录、runtime role capability 分流、同步健康、
  水位/failed inbox/失败告警、failed inbox 本地重放、自动 backoff 状态、立即拉取、open conflict 查询和
  `keep_local/ignored/retry_after_dependency/use_incoming/manual_merge` 人工处置。端到端实机证据、
  生产告警投递/runbook 和更多对象 manual_merge 范围仍按 `docs/deployment/multi-environment-sync.md`
  继续实现。

`/users`：

- 用户、邀请、工作台成员和权限策略视图。全局用户/邀请/角色操作只对 `super_admin`
  显示；非 `super_admin` 只能进入当前工作台成员和策略上下文。OIDC/header 自动 membership
  已有后端配置和测试，并通过 runtime 下发到策略页做部署层只读展示；工作台成员页已展示角色影响、
  owner 数量、owner 降权/移出二次确认和最后 owner 禁用态；策略页已展示身份权限审计摘要，
  并可编辑 viewer 反馈策略和当前工作台部门自动开通规则；策略页已展示权限变更 diff，
  可选择多条权限变更调用 `/api/identity/permission-rollbacks` 回滚。真实 provider/内网门户验收仍归
  Identity & Access 后续实现。

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
