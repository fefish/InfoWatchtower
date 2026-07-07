# 后端功能模块设计

> 状态：目标态整理稿。本文描述后端领域模块、数据归属、API/任务/事件边界；
> 前端页面呈现见 `docs/product/frontend-product-design.md`。

本文是后端模块总图，不承载每个模块的完整细节。模块细节按专题归位：

| 模块 | 细节文档 |
|---|---|
| Identity & Access 身份权限 | `docs/backend/identity-access-design.md` |
| Collaboration / Feedback / Notifications 协作与通知 | `docs/backend/collaboration-notification-design.md` |
| Sources / Ingestion / Content Pipeline / Storage 数据主链 | `docs/backend/data-ingestion-flow-storage-design.md`、`docs/backend/ingestion-adapter-dedup-spec.md`、`docs/backend/data-lineage-and-storage.md` |
| Recommendation & Scoring 推荐评分 | `docs/backend/recommendation-scoring-design.md` |
| Pipeline & Jobs 流水线任务 | `docs/backend/pipeline-jobs-design.md` |
| Reports & Editorial 报告编审发布 | `docs/backend/reports-editorial-design.md`、`docs/backend/report-renditions-design.md` |
| Workspace Configuration 工作台配置 | `docs/backend/workspace-configuration-design.md`、`docs/backend/workspace-module-model.md` |
| Strategy Loop 战略闭环 | `docs/backend/strategy-loop-design.md` |
| Archive / Knowledge 资料库与知识沉淀 | `docs/backend/archive-knowledge-design.md`、`docs/backend/tech-insight-loop-fusion-plan.md` |
| Sync Conflict & Distribution 同步冲突分发 | `docs/backend/sync-conflict-distribution-design.md`、`docs/deployment/multi-environment-sync.md`、`docs/deployment/deployment-topology.md` |
| Export Compliance 导出合规 | `docs/backend/export-compliance-design.md`、`docs/backend/data-format-mapping.md` |
| Audit / Ops / Observability 审计运维可观测 | `docs/backend/audit-ops-observability-design.md`、`docs/deployment/deployment-ops.md` |
| Search 全局检索 | `docs/backend/search-design.md` |
| Security / Secrets / Privacy 安全密钥隐私 | `docs/backend/security-secrets-privacy-design.md`、`docs/deployment/auth-security-roadmap.md` |
| Extension Governance 扩展治理 | `docs/backend/extension-governance-design.md`、`docs/backend/extension-points.md` |
| Contract & Test Governance 契约与测试治理 | `docs/backend/contract-test-governance-design.md` |

如果本文摘要和专题文档冲突，先同步修正文档和 contract，再实现代码。

目录内主次关系见 `docs/backend/README.md`：本文件是总图，各模块 `*-design.md` 是事实源，
`data-format-mapping.md`、`report-renditions-design.md`、`workspace-module-model.md` 等是附录。
附录不能反向覆盖模块事实源。

## 1. 后端设计原则

后端按“能力模块/领域边界”设计，而不是按前端页面拆服务。

原则：

- 每个业务对象只有一个主责模块。
- 每个模块明确拥有的数据表、API、异步任务和事件。
- 前端页面可以组合多个模块，但不能让页面反向定义后端能力。
- 权限、审计、同步、部署形态是横切能力，不散落在页面逻辑里。
- 机器契约在 `config/contracts/*.json` 中维护，代码和测试必须同步。

## 2. 模块总览

| 模块 | 职责 | 主要前端页面 |
|---|---|---|
| Identity & Access 身份权限 | 登录、SSO、用户、角色、工作台 membership、邀请、会话 | `/login`、`/setup`、`/invite`、`/account`、`/users` |
| Workspace 工作台 | 工作台、页面分区、成员关系、标签策略、格式默认值 | 全局壳、`/users`、`/sources` |
| Sources & Ingestion 源与采集 | 共享源、工作台源链接、adapter、抓取 run、补采 | `/sources`、`/ingestion-runs` |
| Content Pipeline 内容主链 | raw、news、标准化、去重、候选池 | `/news` |
| Recommendation & Scoring 推荐评分 | 准入、评分、推荐 run、反馈分反哺 | `/recommendations`、`/news` |
| Pipeline & Jobs 流水线任务 | 日更编排、后台任务、scheduler、重试、状态机 | 今日速览、`/ingestion-runs`、运维视图 |
| Reports & Editorial 报告编审发布 | 日报、周报、采信、编辑覆盖、发布、锁定 | `/daily-reports`、`/weekly-reports` |
| Reports & Renditions 报告成稿 | 格式注册表、成稿投影、MD/HTML | `/daily-reports`、`/weekly-reports` |
| Collaboration & Feedback 协作反馈 | 点赞、评分、评论、回复、活动事件 | 日报/周报详情、`/notifications` |
| Notifications 消息通知 | 未读通知、已读、通知偏好、对象跳转 | 顶部铃铛、`/notifications` |
| Strategy Loop 战略闭环 | insight、requirement、task | `/insights`、`/requirements`、`/tasks` |
| Archive 历史归档 | 历史报告、实体大事记、历史反馈、旧任务 | `/historical-reports`、`/entity-milestones`、`/quality-archive` |
| Sync Conflict & Distribution 同步冲突分发 | feed、pull、sync inbox/outbox、冲突、水位、人工处置 | `/sync` |
| Export Compliance 导出合规 | 公司 SQL、预检、导出任务、追溯、下载权限 | `/exports` |
| Audit & Ops 审计运维 | 审计日志、部署自检、运行状态 | `/audit-logs`、部署脚本 |
| Search 全局检索 | 统一检索真实情报对象、权限过滤、结果跳转 | 顶部搜索 |
| Security / Secrets / Privacy 安全密钥隐私 | secrets、cookie、CSRF、trusted header、同步脱敏 | 无独立业务页，贯穿登录/部署/同步 |
| Extension Governance 扩展治理 | adapter、domain pack、report format、auth provider、可选页面进入规则 | 工作台、数据源、格式管理、部署配置 |
| Contract & Test Governance 契约与测试治理 | contract、schema、测试、假控件拦截、CI 门禁 | 无运行时页面，贯穿开发验收 |

### 2.1 模块状态索引

状态口径：

- `可验收 v1`：已有真实代码路径、API 或任务链路，并有自动化测试或归档证据支撑第一版使用。
- `部分完成`：核心路径存在，但目标态仍缺关键策略、UI 承接、生产证据或跨对象闭环。
- `目标态未实现`：只完成设计，不应在前端显示运行时入口。

| 模块 | 当前标记 | 已做 | 未做/下一步 | 证据入口 |
|---|---|---|---|---|
| Identity & Access | 部分完成 | public password、setup 首管、邀请建号、`/invite` 状态体验、改密/重置、登录限流、`must_change_password`、`intranet_header`、OIDC code flow + PKCE、OIDC claim 配置映射、OIDC/local redirect 回跳、OIDC start/callback 错误安全回跳、默认/部门 membership 自动映射、DB 部门 membership 规则编辑、owner 移出/降权二次确认、runtime 自动开通规则只读下发、工作台 membership gate、登录页按 `AUTH_MODE=oidc` 显示 SSO 入口，`/users` 已有用户/邀请/成员/策略四块入口、邀请状态展示、自动开通规则展示/编辑、权限审计摘要、成员角色影响提示、最后 owner 前后端守护、viewer 反馈策略影响确认、权限变更 diff 解释和批量回滚 | 真实 provider/内网门户实机证据 | `backend/tests/test_auth.py`、`backend/tests/test_account_lifecycle.py`、`backend/tests/test_deployment_modes.py`、`backend/tests/test_workspaces_api.py`、`frontend/src/pages/LoginPage.spec.ts`、`frontend/src/pages/InvitePage.spec.ts`、`frontend/src/pages/UsersPage.spec.ts` |
| Workspace Configuration | 可验收 v1 | 工作台创建、sections、成员、默认标签策略、默认反馈策略、反馈策略 API、共享源链接、格式默认值、`/users` 可视化编辑 feedback_policy、影响确认、配置差异解释和回滚；`/sources` 标签策略保存失败会显示错误而非假成功 | 更多反馈对象联动 | `backend/tests/test_workspaces_api.py`、`frontend/src/pages/SourcesPage.spec.ts`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/UsersPage.spec.ts` |
| Sources & Ingestion | 可验收 v1，P1/P2 仍有增强 | 旧种子源和 Tech 源导入、导入预览、自建源、补入口、RSS/paper RSS/arXiv paper API/OpenAlex paper API/Semantic Scholar paper API/page manual 抓取、工作台 run、backfill、manual_import CSV/SQL 上传或粘贴、后端预览、逐行校验、错误报告下载、覆盖率、近 14 日覆盖趋势、Top 失败源、scheduler snapshot、失败源手动重试 v1、失败源自动重试队列 v1、失败源站内告警投递 v1、stub adapter `skipped_unimplemented` 显式语义、安全源详情 API/页面（最近 raw、run 错误、raw 趋势、只读部署隐藏抓取） | `wx://` bridge、深度历史补采更多 provider（OpenReview 等）、邮件/外部告警通道、复杂 SQL dialect/大文件分片、评分/采信贡献趋势深化 | `backend/tests/test_sources_api.py`、`backend/tests/test_source_seeds.py`、`backend/tests/test_adapters.py`、`backend/tests/test_ingestion_runs.py`、`backend/tests/test_ingestion_fetch.py`、`frontend/src/pages/SourcesPage.spec.ts`、`frontend/src/pages/SourceDetailPage.spec.ts`、`frontend/src/pages/IngestionRunsPage.spec.ts` |
| Content Pipeline | 可验收 v1 | raw 完整保存、news 标准化、工作台隔离去重、winner/loser、候选池 `lineage.nodes` 完整安全追溯链和 `review_note` 业务解释 | 页面监控源深度抽取和增量差异识别 | `backend/tests/test_stage1_models.py`、`backend/tests/test_news_normalization.py`、`backend/tests/test_news_api.py`、`frontend/src/pages/NewsPage.spec.ts` |
| Recommendation & Scoring | 可验收 v1 | P0-P3/R 准入、噪声降权、Tech Insight Loop 评分配置、评分策略只读运营摘要、单条 scorer preview、P2/P3 观察池复核写入日报草稿、推荐 item 日报 trace 回显、反馈分读取、需求结论 feedback action 进入推荐分、推荐 run 和日报草稿生成 | 评分器策略编辑/批量重算、观察池排序/备注/抽检队列、生产抽检流程 | `backend/tests/test_recommendations.py`、`frontend/src/pages/RecommendationsPage.spec.ts`、`config/scoring/content_scorer_v2.json`、`config/contracts/adapter_pipeline.json` |
| Pipeline & Jobs | 部分完成 | 日更 pipeline、RQ worker/scheduler 入口、部署形态禁采集门禁、scheduler 配置快照 | 通用任务状态机统一、step 级重试、长计算移出 API event loop 的工程化证据 | `backend/tests/test_daily_pipeline.py`、`backend/tests/test_deployment_modes.py` |
| Reports & Editorial / Renditions | 可验收 v1 | 日报/周报 CRUD、候选池批量采信到日报草稿、候选池服务端筛选排序、候选池批量剔除、候选池完整 trace 复核与业务解释、候选采信/剔除通知、采信、发布、编辑覆盖、头条、生成稿重跑、双版成稿、MD/HTML 导出、周报摘要段规则投影 v1 | LLM 周报摘要模型、富文本/差异对比、候选池跨页联动继续增强 | `backend/tests/test_daily_pipeline.py`、`backend/tests/test_news_api.py`、`backend/tests/test_weekly_reports.py`、`backend/tests/test_report_renditions.py`、`frontend/src/pages/NewsPage.spec.ts` |
| Collaboration & Feedback | 部分完成 | 日报条目 reaction/rating/comment/reply 最小 API，日报评论 `@username` 提及解析，`feedback_policy` 控制 viewer 反馈，推荐可读取反馈分，日报反馈和同步冲突写 activity event | 周报/候选/需求/任务统一反馈对象、更多对象提及、采信/编辑/任务活动事件 | `backend/tests/test_recommendations.py`、`backend/tests/test_account_lifecycle.py`、`backend/tests/test_stage1_models.py`、`frontend/src/pages/DailyReportsPage.spec.ts` |
| Notifications | 部分完成 | `activity_events`、`notifications`、`notification_preferences`、`object_watchers` 表和迁移，日报评论生成 unread in-app notification，日报评论提及生成 important notification，日报/周报/候选关注 API，日报条目关注者评论通知，同步冲突生成管理员 important 通知，失败源自动重试到期/阻塞生成 important 通知并跳回 `/ingestion-runs?run_id=...`，日报/周报发布通知按 `notify_on_publish` 生成，周报条目 PATCH 变更生成 `weekly_report_item.updated` 通知并通知周报条目关注者，候选批量采信/剔除生成 `dedupe_group.adoption_changed` 通知并跳回 `/news?dedupe_group_id=...`，任务指派通知给被指派人，需求状态变化通知 owner，未读/列表/已读/归档/全部已读 API，偏好 API，`NotificationRead.target_label/target_path` 后端目标解析，`/notifications` 页面、顶部真实未读数、日报条目级锚点、评论高亮、日报/周报报告级锚点、周报 item 锚点、候选池锚点、同步冲突锚点、抓取 run 锚点、任务锚点、需求锚点、归档筛选、站内偏好开关和协作/通知对象不进 sync feed 的负向测试 | 邮件投递、更多对象通知生成/提及 | `backend/tests/test_account_lifecycle.py`、`backend/tests/test_operations_api.py`、`backend/tests/test_stage1_models.py`、`backend/tests/test_news_api.py`、`backend/tests/test_ingestion_runs.py`、`backend/tests/test_deployment_modes.py::test_extranet_sync_feed_excludes_local_collaboration_notifications`、`frontend/src/layouts/AppShell.spec.ts`、`frontend/src/pages/NotificationsPage.spec.ts`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`frontend/src/pages/NewsPage.spec.ts`、`frontend/src/pages/IngestionRunsPage.spec.ts`、`frontend/src/pages/SyncRunsPage.spec.ts`、`frontend/src/pages/TopicTasksPage.spec.ts`、`frontend/src/pages/RequirementsPage.spec.ts`、`config/contracts/notifications.json` |
| Strategy Loop | 可验收 v1 | insights/strategic implications 已有独立列表、创建、编辑、确认/归档 API 和 `/insights` 页面，保留 news/raw/source 追溯；requirements/topic tasks 列表、创建、owner/负责人、状态更新、需求状态通知、任务指派通知、审计和页面已接入；requirement source links v1 已支持 daily/weekly report item、entity milestone、historical report、historical feedback、news、raw 追溯并在 `/requirements` 展示；日报/周报条目一键沉淀 v1 已可创建 insight、implication、requirement 和可选 task，任务列表可展示 requirement/source links；任务负责人视图 v1 已支持 assigned_to_me、overdue、blocked 筛选和 blocked reason；任务批量处理 v1 已支持 `POST /api/topic-tasks/batch` 更新 `status/blocked_reason`；任务详情 v1 已支持 `GET /api/topic-tasks/{id}` 和 `/tasks` 只读详情抽屉，展示任务、需求和来源追溯；Strategy Loop sync boundary v1 已验证 requirements/topic_tasks 不进入 extranet feed；需求结论反哺推荐 v1 已通过 `EditorialAction(requirement.feedback_to_recommendation)` 进入 `feedback_score`；列表/详情按 workspace viewer gate，洞察/战略影响按 workspace member gate，需求/指派按 workspace admin gate，被指派人可更新自己的任务状态和 blocked reason | 跨对象联动体验和更多协作对象解释关系深化 | `backend/tests/test_operations_api.py`、`backend/tests/test_deployment_modes.py`、`backend/tests/test_recommendations.py`、`frontend/src/pages/InsightsPage.spec.ts`、`frontend/src/pages/RequirementsPage.spec.ts`、`frontend/src/pages/TopicTasksPage.spec.ts`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`config/contracts/strategic_loop.json`、`config/contracts/sync_strategy.json` |
| Archive / Knowledge | 可验收 v1，生产证据待补 | 历史报告、实体大事记、质量归档、旧任务归档、历史资产只读 API/UI、导入 dry-run/execute/verify、隔离 PostgreSQL 全量验收、日报/周报条目登记当前实体事件 v1、当前实体事件编辑/确认/撤销和 requirement 来源引用 v1、历史报告到 requirement 来源引用 v1、历史反馈/质量反馈到 requirement 来源引用 v1 | 生产主库同套 check-only/accepted-gaps 证据、更多跨对象体验和 E2E | `backend/tests/test_tech_insight_loop_*.py`、`backend/tests/test_operations_api.py`、`frontend/src/pages/HistoricalReportsPage.spec.ts`、`frontend/src/pages/EntityMilestonesPage.spec.ts`、`frontend/src/pages/QualityArchivePage.spec.ts`、`frontend/src/pages/RequirementsPage.spec.ts`、`frontend/src/pages/TopicTasksPage.spec.ts`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`outputs/tech_insight_loop/postgres_full_import_20260703T050653Z/` |
| Sync Conflict & Distribution | 部分完成 | 同步包导出/下载/导入、六类对象 apply、feed/manifest、intranet pull、水位、`sync_inbox.record_json/error_message/attempt_count/last_attempt_at` 失败重放状态、`POST /api/sync/inbox/retry-failed` 本地重试、scheduler `inbox_auto_retry` 自动 backoff、`GET /api/sync/health` 水位/failed inbox 到期/阻塞/失败 run/open conflict 告警、conflict 写入、open conflict 查询、`keep_local/ignored/retry_after_dependency/use_incoming/manual_merge` 人工处置 UI、`/sync` role capability 分流和健康卡 | extranet->intranet 实机证据、生产监控告警投递、更多对象 manual_merge | `backend/tests/test_sync_feed_pull.py`、`backend/tests/test_deployment_modes.py`、`backend/tests/test_operations_api.py`、`frontend/src/pages/SyncRunsPage.spec.ts` |
| Export Compliance | 可验收 v1 | 公司 SQL 4 表导出、validator、preflight、batch manifest、trace、trace item ID、trace 字段来源详情、trace 字段差异预览、导入回执、失败语句反馈、service token importer 回调、服务端流式下载、viewer 下载禁用、预览复制、截断预览保护、HTML 清洗和前端预检摘要 | 真实内网平台生产联调证据 | `backend/tests/test_company_sql_export.py`、`frontend/src/pages/ExportsPage.spec.ts`、`scripts/validate_company_sql.py` |
| Audit / Ops / Observability | 部分完成 | audit logs、显式 `workspace_code`、工作台/全局查询权限、`/audit-logs` 工作台过滤页、healthz、部署自检、备份/恢复脚本、全量验收脚本 | action taxonomy 稳定化、用户筛选/详情/导出、失败趋势/告警、生产备份恢复演练证据 | `config/contracts/audit_ops.json`、`backend/tests/test_operations_api.py::test_audit_logs_are_workspace_scoped_for_workspace_admin`、`frontend/src/pages/AuditLogsPage.spec.ts`、`backend/tests/test_backup_restore_scripts.py`、`backend/tests/test_full_acceptance_script.py` |
| Search | 部分完成 | `/api/search` 数据库查询 v1、workspace viewer gate、工作台对象过滤、数据源按 workspace_source_link 过滤、评论回溯日报工作台、周报 item、导出任务/trace 条目、report rendition 成稿锚点、super_admin 同步运行/冲突检索、runtime `capabilities.search`、顶部搜索结果分组、键盘选择、本地近期结果、intranet 禁采集对象专项测试和组件跳转测试 | 索引表/专用搜索引擎和 E2E | `docs/backend/search-design.md`、`config/contracts/search.json`、`backend/tests/test_search_api.py`、`frontend/src/layouts/AppShell.spec.ts`、`frontend/src/pages/DailyReportsPage.spec.ts`、`frontend/src/pages/WeeklyReportsPage.spec.ts`、`frontend/src/pages/ExportsPage.spec.ts`、`frontend/src/pages/SyncRunsPage.spec.ts` |
| Security / Secrets / Privacy | 部分完成 | cookie/session、CSRF 设计、trusted header 设计、deploy checks、sync token 鉴权、secret 不进同步包的约束、`app.core.privacy` 统一 secret-like 检测/审计脱敏、sync feed/package/apply 统一拒绝 secret-like payload | session rotation/管理页、真实 OIDC provider 安全验收、生产备份权限/加密证据、后续结构化日志 redactor 接入 | `backend/tests/test_deployment_modes.py`、`backend/tests/test_sync_feed_pull.py`、`backend/tests/test_operations_api.py::test_audit_details_redact_secret_like_values`、`backend/tests/test_operations_api.py::test_sync_package_export_download_and_import_are_auditable`、`docs/backend/security-secrets-privacy-design.md` |
| Extension Governance | 部分完成 | adapter/domain pack/report format/auth provider 扩展边界、hardware domain pack 样例、report format registry | 更多 domain pack 样例、adapter 未实现语义统一、扩展启停版本/审计 | `backend/tests/test_workspaces_api.py`、`backend/tests/test_report_renditions.py` |
| Contract & Test Governance | 部分完成 | contract 分层、后端/前端测试基线、假控件规则、AppShell 和数据源 0 结果组件测试 | contract-schema 漂移检测、Playwright 关键旅程、假控件自动扫描、证据索引自动化 | `docs/backend/contract-test-governance-design.md`、`frontend/src/layouts/AppShell.spec.ts`、`frontend/src/pages/SourcesPage.spec.ts` |

## 3. Identity & Access 身份权限模块

详细设计见 `docs/backend/identity-access-design.md`。本节只保留后端模块归属和摘要。

### 3.1 模块边界

后端用户模块属于 Identity & Access，不属于前端顶部栏。

它负责：

- 本地用户 `users`。
- 全局角色 `roles`、`permissions`、`user_roles`。
- 工作台成员 `workspace_memberships`。
- 登录方式：`local`、`public_password`、`oidc`、`intranet_header`。
- 邀请、改密、忘记密码、管理员代重置。
- 会话 cookie、CSRF、登录限流。
- 登录、登出、权限变更审计。

它不负责：

- 顶部栏怎么排版。
- 用户胶囊是否下拉。
- 通知铃铛怎么展示。

### 3.2 当前状态

已实现：

- public password 登录。
- 登录限流。
- 邀请建号。
- 改密、忘记密码恒定响应、管理员代重置。
- `must_change_password`。
- `intranet_header`。
- 通用 OIDC authorization code flow + PKCE。
- OIDC claims 配置化映射，支持 `OIDC_CLAIM_*` 和简单嵌套路径。
- OIDC/local 登录后按 redirect query 回到原页面。
- OIDC provider error、state 缺失/不匹配、token/claims/membership 失败会安全回跳
  `/login?auth_error=...`，登录页显示固定友好文案，不暴露 provider/backend 细节。
- OIDC 和 `intranet_header` 自动建号后按默认工作台与部门映射写入 membership。
- `/login` 已按 runtime `auth_mode` 显示 public password、OIDC SSO 或 intranet header 入口。
- `/users` 已形成用户、邀请、工作台成员、策略四块入口；策略页展示角色矩阵、部署认证上下文、
  部署层自动开通规则、当前工作台部门映射规则、身份审计摘要，并提供 viewer 反馈策略、部门映射编辑、
  权限变更 diff 解释和批量回滚。
- owner 移出和 owner 降权属于危险权限变更：后端要求 `confirm_dangerous_change`，最后 owner
  仍由后端硬拦截；前端同步要求二次确认。
- 主要业务 API 的 workspace membership gate。

未完整闭环：

- 真实 provider 的端到端验收证据仍缺失。
- 真实 OIDC provider 和真实内网门户验收仍未闭环。

### 3.3 OIDC 目标态

通用 OIDC flow 是基础能力，完整产品态还需要：

```text
前端 /login
  根据 runtime.auth_mode 显示 SSO 按钮
  -> GET /api/auth/oidc/start
  -> Provider 登录
  -> GET /api/auth/oidc/callback
  -> 本地 users/session
  -> 根据自动开通策略加入工作台
  -> 返回原始 redirect 或 /dashboard
```

新增配置建议：

```text
OIDC_CLAIM_EXTERNAL_ID=sub
OIDC_CLAIM_EMPLOYEE_NO=employee_no
OIDC_CLAIM_USERNAME=preferred_username
OIDC_CLAIM_DISPLAY_NAME=name
OIDC_CLAIM_DEPARTMENT=department
OIDC_CLAIM_EMAIL=email
AUTH_DEFAULT_WORKSPACE_CODES=
AUTH_DEPARTMENT_WORKSPACE_MAP=
```

### 3.4 权限模型

权限是两层：

```text
global role      实例级能力
workspace role   工作台内能力
```

全局角色：

| 角色 | 后端含义 |
|---|---|
| `super_admin` | 实例级管理，用户、部署、同步 token、全局配置 |
| `editor_admin` | 内容生产管理者，默认可参与多个工作台采编 |
| `analyst` | 分析成员 |
| `viewer` | 浏览者 |

工作台角色：

| 角色 | 后端含义 |
|---|---|
| `owner` | 工作台最高权限 |
| `admin` | 工作台配置和运行权限 |
| `member` | 内容采编协作权限 |
| `viewer` | 只读或按策略开放反馈 |

## 4. Collaboration & Feedback 协作反馈模块

详细设计见 `docs/backend/collaboration-notification-design.md`。本节只保留后端模块归属和摘要。

### 4.1 当前状态

已实现最小 API：

```text
POST /api/daily-report-items/{id}/reactions
POST /api/daily-report-items/{id}/ratings
GET  /api/daily-report-items/{id}/comments
POST /api/daily-report-items/{id}/comments
```

当前用途：

- 用户在日报条目上表达判断。
- 后续推荐 run 读取反馈进入 `heat_score/feedback_score`。
- 工作台 `feedback_policy` 已控制 viewer 能否点赞、评分、评论；策略关闭后后端返回 403，前端日报页禁用对应入口。

### 4.2 目标态边界

协作反馈模块负责：

- 点赞/收藏类轻反馈。
- 评分。
- 评论与回复。
- @ 提及解析。
- 与 report item/news item 的挂接。
- 产生 activity event，供通知模块消费。

它不负责：

- 通知收件箱的已读状态。
- 顶部铃铛 UI。
- 审计日志查询页面。

### 4.3 viewer 反馈策略

普通浏览用户能否评论、点赞、评分，不应写死在角色里。

建议放入工作台策略：

```text
feedback_policy:
  viewer_can_react: true
  viewer_can_rate: true
  viewer_can_comment: true
  viewer_can_edit: false
```

默认建议：

| 部署形态 | viewer 反馈 |
|---|---|
| standalone | 由管理员配置 |
| cloud | 可点赞/评分/评论，不可编辑 |
| extranet | 默认只读，可由管理员打开反馈 |
| intranet | 可点赞/评分/评论，反馈留内网本地 |

## 5. Notifications 消息通知模块

详细设计见 `docs/backend/collaboration-notification-design.md`。通知模块是 Collaboration
模块消费 activity event 后形成的用户收件箱，不是前端铃铛本身。

### 5.1 模块边界

通知模块是后端模块，不是前端铃铛。

后端负责：

- 记录活动事实。
- 判断哪些用户应该收到通知。
- 维护未读/已读/归档状态。
- 提供查询和标记 API。
- 保证内网本地通知不回流公网。

前端负责：

- 顶部铃铛展示未读数。
- 消息列表页展示通知。
- 点击通知跳转到对象。

### 5.2 建议数据模型

待用户确认后再写 contract：

```text
activity_events
  id
  workspace_code
  domain_code
  actor_user_id
  event_type
  object_type
  object_id
  target_object_type
  target_object_id
  summary
  metadata_json
  sync_policy
  created_at

notifications
  id
  user_id
  workspace_code
  activity_event_id
  status        unread/read/archived
  priority      normal/important
  read_at
  created_at

notification_preferences
  user_id
  workspace_code
  event_type
  in_app_enabled
  email_enabled

object_watchers
  user_id
  workspace_code
  object_type
  object_id
  active
```

### 5.3 事件到通知规则

| 事件 | 后端处理 |
|---|---|
| 一级评论 | 生成 activity event；通知被 @ 用户、既有评论参与者和日报条目关注者 |
| 回复评论 | 通知被回复人、楼主、被 @ 用户 |
| @ 提及 | 强通知被提及用户 |
| 点赞 | 默认只记 activity，不生成逐条通知 |
| 评分 | 默认只记 activity，不生成逐条通知 |
| 采信状态变更 | 通知条目相关协作者 |
| 编辑覆盖字段变更 | 通知条目相关协作者 |
| 周报条目更新 | 通知工作台成员和周报条目关注者 |
| 日报/周报发布 | 可配置通知工作台成员 |
| 任务指派 | 通知被指派人 |
| 同步冲突 | 通知 super_admin / workspace owner |
| 失败源自动重试到期/阻塞 | 通知 super_admin / workspace owner/admin，并跳转对应抓取 run |

## 6. Search 全局检索模块

详细设计见 `docs/backend/search-design.md`，机器契约见 `config/contracts/search.json`。
顶部搜索只有在后端 Search 模块、权限过滤、runtime capability、前端承接和测试完成后才出现；
当前数据库查询 v1 已满足最小恢复条件。

本模块负责统一检索日报、周报、候选新闻、数据源、实体、需求、任务和评论，并按
workspace membership 与 `visibility_scope` 做权限过滤。如果只是搜页面名，不建设
Search 模块。

当前 v1：

- `GET /api/search` 返回统一结果结构和真实业务 route，覆盖周报条目、导出 trace 条目和同步运行等主要对象锚点。
- 非工作台成员 403；数据源只返回当前工作台已启用源。
- `DEPLOY_MODE=intranet` 等关闭采集能力的形态不返回 `data_source` 结果。
- 顶部搜索只调用 `/api/search`，不搜索导航菜单。

后续深化：

- `search_documents` 索引表。
- Playwright E2E。
- 后续新增对象锚点必须先进入 Search contract 和对应页面 query 承接测试；report rendition 已完成。

## 7. Strategy Loop 战略闭环模块

详细设计见 `docs/backend/strategy-loop-design.md`，机器契约见
`config/contracts/strategic_loop.json`。

本模块负责：

- `insights`
- `strategic_implications`
- `requirements`
- `requirement_source_links`
- `topic_tasks`
- 从日报/周报采信项到内部需求和任务的外部信号追溯。

它不负责日报/周报正文生成，也不替代通用项目管理系统。

## 8. Archive / Knowledge 资料库与知识沉淀模块

详细设计见 `docs/backend/archive-knowledge-design.md`。Tech Insight Loop 旧资产导入细节附录见
`docs/backend/tech-insight-loop-fusion-plan.md`，机器契约见
`config/contracts/tech_insight_loop_legacy_import.json`。

本模块负责：

- `historical_reports`
- `tracked_entities`
- `entity_milestones`
- `historical_feedback_items`
- `historical_job_runs`
- 旧系统资产导入验收和引用缺口归档。

历史资产默认只读，不进入当前推荐、日报/周报采信或标准公司 SQL。当前系统新登记的
`legacy_system=current` 实体事件属于持续沉淀资产，可由 workspace admin 治理，并可作为
requirement 来源证据。旧反馈/质量反馈仍保持归档只读，但 workspace admin 可把单条历史反馈登记为
requirement 来源证据，用于源质量复盘；该写入只进入 `requirements/requirement_source_links`，
不创建当前 comments/ratings，也不触发推荐、采信或 SQL 导出。

## 9. Audit / Ops / Observability 审计运维可观测模块

详细设计见 `docs/backend/audit-ops-observability-design.md`，机器契约见
`config/contracts/audit_ops.json`。

本模块负责：

- `audit_logs`
- 登录、权限、采集、发布、导出、同步等关键 action taxonomy。
- 运行健康、任务状态、失败趋势、告警和备份恢复证据。

它不负责业务字段合同，也不替代部署执行手册。

## 10. Security / Secrets / Privacy 安全密钥隐私模块

详细设计见 `docs/backend/security-secrets-privacy-design.md`。

本模块负责：

- secret-like 字段脱敏和拒绝规则。
- cookie、CSRF、OIDC、trusted header 和 iframe 安全边界。
- sync package/feed 不携带密钥。
- 备份和日志不泄露敏感信息。

身份建模和权限仍归 Identity & Access。

## 11. Extension Governance 扩展治理模块

详细设计见 `docs/backend/extension-governance-design.md`，接口细节见
`docs/backend/extension-points.md` 和 `config/contracts/extension_points.json`。

本模块负责新增 adapter、domain pack、report format、exporter、auth provider 和可选页面
进入系统前的治理流程。扩展必须通过注册表接入，不能分叉主链路。

## 12. Contract & Test Governance 契约与测试治理模块

详细设计见 `docs/backend/contract-test-governance-design.md`。

本模块负责 contract、API schema、前后端测试、假控件拦截和 CI/验收门禁。它是防止
“前端显示成功、后端没有闭环”的横切治理层。

## 13. 其他后端模块边界

### 13.1 Workspace

详细设计见 `docs/backend/workspace-configuration-design.md`。

拥有：

- `workspaces`
- `workspace_sections`
- `workspace_memberships`
- 工作台标签策略
- 默认页面和格式注册

### 13.2 Sources & Ingestion

详细设计见 `docs/backend/data-ingestion-flow-storage-design.md`。

拥有：

- `data_sources`
- `workspace_source_links`
- adapters
- `ingestion_runs`
- historical backfill

### 13.3 Content Pipeline

详细设计见 `docs/backend/data-ingestion-flow-storage-design.md` 和
`docs/backend/data-lineage-and-storage.md`。

拥有：

- `raw_items`
- `news_items`
- `dedupe_groups/items`
- normalize/dedupe 服务

### 13.4 Recommendation & Scoring

详细设计见 `docs/backend/recommendation-scoring-design.md`。

拥有：

- `recommendation_runs`
- `recommendation_items`
- content scorer 配置和执行
- feedback/heat score 读取

### 13.5 Reports & Renditions

报告编审发布详细设计见 `docs/backend/reports-editorial-design.md`；多版成稿投影详细设计见
`docs/backend/report-renditions-design.md`。

拥有：

- `daily_reports/items`
- `weekly_reports/items`
- `generated_news`
- `report_formats`
- `report_renditions`

### 13.6 Sync

同步冲突和分发详细设计见 `docs/backend/sync-conflict-distribution-design.md`；部署同步边界见
`docs/deployment/deployment-topology.md` 和 `docs/deployment/multi-environment-sync.md`。

拥有：

- feed / pull
- `sync_runs`
- `sync_cursors`
- `sync_inbox/outbox`
- `sync_conflicts`

### 13.7 Exports

导出合规详细设计见 `docs/backend/export-compliance-design.md`；SQL 字段映射见
`docs/backend/data-format-mapping.md`。

拥有：

- `export_jobs/items`
- company SQL 导出
- SQL trace

### 13.8 Pipeline & Jobs

详细设计见 `docs/backend/pipeline-jobs-design.md`。

拥有：

- pipeline run 编排
- worker / scheduler 任务投递和执行
- 通用任务状态机
- step 级重试和失败恢复
- 部署形态能力门禁

## 14. 后端设计缺口

| 缺口 | 模块 | 说明 |
|---|---|---|
| OIDC 产品闭环不完整 | Identity & Access | 后端 flow、前端 SSO、claim 映射、自动 membership、redirect 和 provider/callback 错误承接已有；仍缺真实 provider 验收 |
| viewer 反馈策略管理深化 | Workspace + Collaboration | feedback_policy API/后端检查、日报页禁用、`/users` 可视化编辑、影响确认、权限差异解释和回滚已补；仍需更多对象联动 |
| 通知模块深化 | Notifications | 已有日报评论站内通知、日报评论 @ 提及通知、日报/周报条目关注者通知、候选采信/剔除通知、同步冲突管理员通知、失败源自动重试到期/阻塞通知、日报/周报发布通知、周报条目更新通知、任务指派通知、需求状态通知、顶部真实未读数、后端 target_path、日报条目级锚点、评论高亮、报告级锚点、周报 item 锚点、候选池锚点、同步冲突锚点、抓取 run 锚点、任务锚点、需求锚点、归档筛选、object watcher API 和站内偏好；仍缺邮件投递、更多对象通知生成/提及 |
| 全局搜索深化 | Search | 数据库查询 v1 和顶部搜索已恢复，类型分组、键盘选择、本地近期结果、周报 item、export item、report rendition、sync run 锚点和 intranet 禁采集对象专项测试已补；仍缺索引表和 E2E |
| Strategy Loop 体验深化 | Strategy Loop | insight/implication 独立管理、report item strategy loop v1、负责人任务视图、逾期/blocked 处理、任务批量处理、任务详情抽屉、sync feed 负向边界、需求结论反哺推荐、实体事件/历史报告/历史反馈来源追溯已完成；仍需补跨对象联动体验和更多协作对象解释关系 |
| 生产主库历史资产导入验收缺证据 | Archive / Knowledge | 本地隔离库通过，生产仍需 check-only 和 accepted gaps 证据 |
| 同步生产监控深化 | Sync Conflict & Distribution | failed inbox 本地重放状态、手动重试 API、自动 backoff、健康告警和 `/sync` 重试入口已补；仍需 extranet->intranet 实机证据、生产监控告警投递和 runbook |
| 审计和告警 taxonomy 不统一 | Audit / Ops / Observability | 需要稳定 action 命名、失败趋势、备份恢复证据 |
| 运行时结构化日志 redactor 待接入 | Security / Secrets / Privacy | sync feed/package/apply 和 audit 已共用 `app.core.privacy`；当前没有业务 payload 日志 sink，后续新增结构化日志必须复用同一 redactor |
| 扩展启停和注册表治理不足 | Extension Governance | domain pack、adapter、report format 启停需要版本、审计和测试 |
| 前端假控件与假成功测试不足 | Contract & Test Governance | 用户指出的问题必须进入前端组件/E2E 和后端语义测试 |
| 用户管理页策略运营深化 | Identity & Access | 用户、邀请状态、成员、自动开通规则展示/编辑、权限审计摘要、角色影响提示、最后 owner 前后端守护、owner 危险变更确认、viewer 反馈策略编辑、权限变更 diff 解释和批量回滚已补；仍需真实 provider/内网门户验收 |
| 内网部门到工作台策略运营深化 | Identity & Access | intranet header 自动开通后已能按 env 和 DB 部门规则配置 membership，runtime 已只读下发部署层规则，`/users` 策略页可编辑当前工作台 DB 部门映射并写审计；后续补真实内网门户验收证据 |

## 15. 后端验收原则

- 每个模块有 owner 表和 API。
- 每个写操作有权限断言。
- 每个关键操作有审计或 activity event。
- 每个部署形态有能力开关测试。
- 新增前端控件前必须先有后端模块和契约。
