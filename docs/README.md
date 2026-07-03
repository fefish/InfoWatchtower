# 文档地图

本文档说明 InfoWatchtower 文档如何阅读、如何维护，避免出现“总纲一套实现、模块文档另一套实现”。

## 1. 阅读顺序

开发者或 AI 接手时：

1. 先读 `AGENTS.md`。
2. 再读 `docs/00-system-design.md`。
3. 要全量实现或重写系统（含每个页面的元素规格、修改指南、用户扩展模型），读 `docs/system-blueprint.md`。
4. 想快速掌握"有哪些能力、分布在哪、还差什么"，读 `docs/architecture-capability-map.md`。
5. 要实施「账户登录 / 可扩展桌面 / 开箱部署」三个增量工作包，读 `docs/target-state-spec.md`（实现级规格与验收标准）。
6. 再读 `docs/implementation-handoff.md`。
7. 再读 `docs/01-implementation-plan.md`。
8. 先读 `config/contracts/README.md`，理解 contracts 是什么。
9. 写代码时查相关 `config/contracts/*.json` 和 `config/taxonomy/*.json`。
10. 只在需要模块细节时阅读对应专题附录。
11. 旧系统事实从私有参考仓查询；主仓说明见 `references/README.md`，不从旧代码直接继承新架构。

当前进度：阶段 0-6 标准日报链路已完成可回填闭环。阶段 3 已完成旧种子源导入、共享数据源池、默认工作台源链接、工作台统一标签/新闻结构策略、adapter 框架、RSS/paper RSS/页面源抓取到 `raw_items`、工作台级 ingestion run API 和 Redis/RQ worker + scheduler 调度入口；规划部工作台 v1 默认 294 个共享源全部启用，CSV 状态/纳入建议只作为评分先验。阶段 4 已完成 raw 到 news 标准化、canonical URL、dedupe key、工作台隔离硬去重、winner/loser 回写和查询 API；阶段 5 已完成完整流水线 API、按 `day_key` 推荐 run、可解释推荐分、可选 MiniMax 中国区 OpenAI-compatible `generated_news`、日报草稿、发布、条目编辑和点赞/评分/评论最小 API；阶段 6 已实现已发布日报的公司 SQL 标准导出，`POST /api/exports/company-sql/daily-reports/{daily_report_id}` 只导出 `adoption_status = 2`、`generated_news.generation_status = ready` 且 `generated_by` 非 `rule_v1` 的采信项；`GET /api/exports/{export_job_id}/trace` 可按 SQL 语句追到日报条目、生成稿、news、raw 和数据源；MiniMax 未启用、超时或失败时只生成 `fallback_needs_review` 草稿，不直接写入标准 SQL。`planning_intel` 的成品新闻一级分类使用 `config/taxonomy/news_categories.json` 里的 AI 十分类，SQL category 默认使用同一个 `generated_news.category`；`config/taxonomy/source_tags.json` 是数据源侧方向标签，只用于源管理、覆盖分析和评分先验。`planning_intel/company_sql_v1` 生成稿必须带 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact`；导出时 `content_json` 只保留这五个旧内网字段，`created_at` 必须严格对齐旧脚本和已验证合集 SQL 的列顺序与字面量样式，使用 `'YYYY-MM-DD HH:MM:SS'`，来源缺失发布时间时兜底为日报 `day_key 09:00:00`。所有 SQL 预览统一 `InfoWatchtower Company SQL Preview` 标题，且导入内网前必须通过 `python3 scripts/validate_company_sql.py` 逐字段校验。scheduler 开启后可按固定北京时间执行每日完整流水线：抓取、标准化/去重、推荐和日报草稿；生产推荐 `INGESTION_SCHEDULER_DAILY_TIME=09:00`、`INGESTION_SCHEDULER_TIMEZONE=Asia/Shanghai`、`DAILY_PIPELINE_DAY_OFFSET_DAYS=-1`，每天早上生成昨天日报。前端首页必须显示动态工作台状态；工作台壳和导航必须来自后端工作台配置；数据源页采用信息流式共享源列表和右侧标签/新闻结构 tab 面板；候选池页已接入 `dedupe_groups/news_items` 展示 winner/loser、重复来源、推荐分、日报采信状态和追溯 ID；推荐运行页已接入 recommendation runs 和分数拆解；抓取覆盖率页已接入 ingestion runs、RSS 窗口补采、sitemap/归档页/手工导入补采模式、目标日覆盖漏斗和每源链路详情；周报页已接入周报草稿、按一级标签形成板块、条目采信/剔除、板块内排序、编辑和发布；SQL 导出页已接入已发布日报、导出历史和条目追溯；日报页可按日期生成日报草稿，支持生成超时兜底、ready/fallback 状态展示和草稿生成稿重跑，并通过 brief 列表 + 详情弹窗完成正文查看、采信、编辑、点赞、评分、评论和追溯；本地恢复和演示补齐可用 `scripts/import_company_sql_preview_to_reports.py` 把已校验单日 SQL 预览回填为日报/周报工作台数据，且不改变公司 SQL 导出契约；需求、任务、同步、审计页已从路线图占位升级为真实 API 页面，同步页支持导出 zip 同步包、下载、导入幂等和核心对象 apply。`2026-05-21` 到 `2026-05-27` 的规划部日报已发布并导出 SQL；其中 5/27 通过当天 RSS/paper RSS 窗口补采新增 72 条 raw/news 后生成 6 条采信项。`planning_intel` 与 `ai_tools` 的默认标签策略必须保持后端隔离。

MiniMax 真实 key 验收命令已补齐并通过：`scripts/validate_minimax_generation_acceptance.py` 会调用同一条生成链路，检查十分类、五段 `content_json`、短关键词、技术洞察 `insight_json`、HTML 污染和来源未给出的百分比/P95/P99/倍数/延迟/显存数值；pytest 使用 `--fixture-response-json` 走同一套门禁，不需要提交密钥或模型输出。最新 live 证据为 `outputs/minimax/minimax_generation_acceptance.json`，原始模型响应保存在 `outputs/minimax/minimax_live_acceptance_20260703.response.txt`。

Tech Insight Loop 第一轮融合补充：当前只迁入源治理和内容评分配置，不运行旧 `app.py`，不迁移旧 SQLite 的 articles/reports/entity_milestones。`POST /api/sources/import-tech-insight-loop` 从 `config/seeds/tech_insight_loop/sources_full_zh.csv` 导入 386 行源治理记录，其中 355 行有 RSS/URL/RSSHub 入口、31 行作为 `metadata_only/needs_entry` 待补入口；按 URL/RSS 去重后形成 363 个共享源，并保留源等级、渠道类型、专家路由、板块相关度和评分拆解。推荐层已接入 `config/scoring/content_scorer_v2.json`，在 `recommendation_items` 中保存 `admission_level/admission_score/admission_pool/noise_types/reject_reasons/scorer_breakdown/expert_routes`。这些字段只用于源治理、评分和前端解释，不改变 `generated_news.category`、公司 SQL category、五段 `content_json` 和导出筛选。

Tech Insight Loop 第二轮阶段 0 已完成只读资产盘点和历史素材/报告 dry-run：`scripts/tech_insight_loop_inventory.py` 只读读取 `references/参考工具/data/insight_loop.sqlite3`，本地输出 `outputs/tech_insight_loop/tech_insight_loop_inventory.{json,md}`，并用 `config/contracts/tech_insight_loop_legacy_import.json` 固化历史导入边界；`scripts/tech_insight_loop_legacy_dry_run.py` 输出 `outputs/tech_insight_loop/tech_insight_loop_legacy_dry_run.{json,md}`，确认 14834 条旧素材可作为历史 raw 归档候选，58 份 daily/weekly 报告可作为 `historical_reports` 归档候选，8 份 brief/brief_ppt 暂不进入本批归档。当前仍不写主库，不运行旧 `app.py`，不让历史资产进入当前推荐或公司 SQL。

Tech Insight Loop 历史素材/报告真实导入脚本已实现：`scripts/tech_insight_loop_legacy_import.py` 默认不写库，只有显式 `--execute` 且配置 `DATABASE_URL` 后才写入；文章进入禁用的 `legacy_tech_insight_loop` 归档源和 `raw_items.raw_payload_json.legacy_tech_insight_loop`，报告进入 `historical_reports`，不直接写当前 `daily_reports/weekly_reports`，以避免旧库同一天/同周多报告和现有唯一键冲突。

Tech Insight Loop 历史归档只读 API/UI 已实现：`GET /api/historical-reports/summary`、`GET /api/historical-reports`、`GET /api/historical-reports/{id}` 和前端 `/historical-reports` 可查看旧日报/周报归档、正文和引用解析/缺口。该页面只读，不触发导入、推荐或公司 SQL 导出。

Tech Insight Loop 实体大事记归档模型和导入脚本已实现：`tracked_entities/entity_milestones` 保存旧 `ai_entities/entity_milestones`，`scripts/tech_insight_loop_entity_import.py` 默认不写库，显式 `--execute` 且配置 `DATABASE_URL` 后才写入。事件会尽量解析到已导入的 `raw_items/historical_reports`；未解析旧引用保留在 `metadata_json.legacy_refs`。实体事件仍是历史/时间线资产，不进入当前推荐、日报或标准公司 SQL。

Tech Insight Loop 实体大事记只读 API/UI 已实现：`GET /api/entity-timeline/summary`、`GET /api/tracked-entities`、`GET /api/entity-milestones`、`GET /api/entity-milestones/{id}` 和前端 `/entity-milestones` 可查看旧实体、事件时间线、重要等级和旧引用解析缺口。该页面只读，不触发导入、采信、推荐或公司 SQL 导出。

Tech Insight Loop 历史反馈和旧任务归档模型已实现：`historical_feedback_items/historical_job_runs` 保存旧 `feedback/article_quality_feedback/jobs`，`scripts/tech_insight_loop_quality_import.py` 默认不写库，显式 `--execute` 且配置 `DATABASE_URL` 后才写入。反馈会尽量解析到已导入的历史 `raw_items`；未解析旧引用保留在 `metadata_json.legacy_refs`。旧任务只保存统计、消息、失败原因和 details，不创建当前 `ingestion_runs`，也不迁移旧任务状态机。

Tech Insight Loop 质量归档只读 API/UI 已实现：`GET /api/quality-archive/summary`、`GET /api/historical-feedback-items`、`GET /api/historical-job-runs` 和前端 `/quality-archive` 可查看旧反馈、旧质量反馈、旧任务记录、失败源统计和反馈引用缺口。该页面只读，不触发导入，不创建当前评论/评分/抓取任务，不进入推荐、采信或公司 SQL。

Tech Insight Loop 导入验收 API/UI 已实现：`GET /api/legacy-import/summary` 和 `GET /api/legacy-import/gaps` 可按当前主库统计历史素材 raw、历史日报/周报、实体、实体大事记、历史反馈和旧任务导入覆盖率，并集中查看报告、实体事件和历史反馈的未解析引用。前端 `/historical-reports` 顶部展示导入验收面板。该入口只读，不执行导入脚本，不触发推荐、采信或公司 SQL。命令行执行验收脚本已补齐：`scripts/tech_insight_loop_import_verify.py --check-only` 只读核对当前库；小批量执行使用 `--execute --article-limit 20 --report-limit 5 --entity-limit 5 --milestone-limit 20`；如需同时导入历史反馈和旧任务归档，加 `--include-quality-archive --feedback-limit 4 --quality-feedback-limit 4 --job-limit 10`；全量执行必须显式加 `--confirm-full-import`。报告输出到 `outputs/tech_insight_loop/tech_insight_loop_import_execution_report.{json,md}`。本地隔离 PostgreSQL 全量验收已归档到 `outputs/tech_insight_loop/postgres_full_import_20260703T050653Z/`，7 项覆盖率 complete，30 个旧库断链引用已用 `outputs/tech_insight_loop/tech_insight_loop_import_accepted_gaps.json` 逐项归档并通过 validator；旧 PDF/二进制文本中的 NUL byte 会转义为 `\u0000` 标记并记录到 `legacy_import.nul_sanitized_fields`，避免 PostgreSQL text/JSONB 写入失败。生产全量导入后，仍需用同一条 `scripts/validate_tech_import_acceptance.py outputs/tech_insight_loop/tech_insight_loop_import_execution_report.json --accepted-gaps-json outputs/tech_insight_loop/tech_insight_loop_import_accepted_gaps.json` 做机器验收。

第三轮平台化与成稿融合补充（2026-07-02）：工作台自助扩展（`POST /api/workspaces` 自动配齐核心分区/标签策略/内置格式/成员，seed 不覆盖自建台）、自建信息源（`POST /api/sources` 入共享池并自动启用、同 URL 复用、`PATCH` 补入口）、抓取对齐旧系统（浏览器 UA + `max_items_per_source`）、「一次采信，多版成稿」P1-P4（`report_formats` 注册表、`report_renditions` 投影、`insight_json`、头条 Top6 可调、日报/周报双版视图与 MD/HTML 导出、日报页默认技术洞察版成品）、Apple Liquid Glass 视觉基线、六组垂直导航与晨报式今日速览。能力分块、分布架构与差距清单见 `docs/architecture-capability-map.md`。

SQL 时间口径补充：`created_at` 字面量按北京时间 `Asia/Shanghai` 渲染，和日报 `day_key` 的归属判断一致；字段格式仍为内网兼容的 `'YYYY-MM-DD HH:MM:SS'`，不得改成函数表达式或空值。

最近已验证：本地已生成 `2026-04-30` 单日日报 SQL 预览，`2026-05-01` 到 `2026-05-08` 批量日报和合并 SQL 预览，`2026-05-09` 到 `2026-05-14` 合并 SQL 预览，`2026-05-15` 到 `2026-05-20` 单日/合并 SQL 预览，以及 `2026-05-21` 到 `2026-05-27` 单日/合并 SQL 预览。当前还额外保留 `2026-05-09` 到 `2026-05-19`、`2026-05-09` 到 `2026-05-20` 总合集预览。预览文件放在 `outputs/sql/previews/`，该目录不进 Git。全部 SQL 预览已通过 `scripts/validate_company_sql.py`，0505 预览是字段校验基准。最近一次今天补采验证：`2026-05-27` RSS/paper RSS 当前窗口 289 个源中 221 个成功、68 个失败，抓取 10636 条，命中目标日 72 条并新增 raw/news，最终生成并发布 6 条采信项。演示/恢复库可用 `scripts/import_company_sql_preview_to_reports.py` 从已校验单日 SQL 预览回填日报和周报；本地已用 `2026-05-28` 到 `2026-06-12` 的 14 个单日预览回填 512 条日报采信项，并生成 3 个已发布周报草稿。当前已补历史补采前后端二期：`POST /api/ingestion/backfill-runs` 创建 `historical_backfill` run，支持 `rss_window/paper_api/archive_page/sitemap/manual_import` 模式，按目标日期窗口过滤 raw 入库，并在前端展示每源覆盖统计；`GET /api/ingestion/coverage` 已补目标日 raw/news/winner/recommendation/daily 漏斗。候选池已展示推荐分、日报采信状态和追溯 ID。周报前后端已提供草稿生成、条目采信编辑、排序和发布。需求、任务、同步和审计已提供真实列表/创建/状态更新页面；同步页已支持同步包导出、zip 下载、导入幂等和核心对象 apply；SQL 导出页已支持导出 trace。下一步优先深度历史补采、周报正文生成、部署登录硬化和真实环境备份恢复演练。

给新工程师或 AI 的当前实现快照：

- 已完成：本地可运行 monorepo、登录/RBAC、账户邀请/改密/重置/限流、首次运行 Setup、工作台 membership gate、一键部署脚本、启动自动迁移、生产自检、备份/恢复脚本、共享数据源池、Tech Insight Loop 源治理导入、Tech Insight Loop 旧资产只读盘点、历史导入 dry-run 和真实导入脚本、历史反馈/旧任务归档脚本、工作台统一标签策略、adapter 框架、抓取入 raw、标准化入 news、去重组、结构化内容准入评分、推荐、MiniMax 结构化生成、日报发布、公司 SQL 导出、周报采信项管理、需求/任务/同步/审计 v1。
- 已可验收：`/sources` 管理共享源、Tech 源导入和工作台标签策略；`/ingestion-runs` 查看抓取/补采覆盖；`/news` 查看去重 winner、准入字段和推荐/日报追溯；`/daily-reports` 生成、编辑、发布日报；`/weekly-reports` 生成并管理周报候选；`/exports` 生成和下载 SQL。
- 当前设计边界：成品新闻 category 仍使用规划部 AI 十分类；数据源方向标签只做源管理和评分先验；`adoption_status` 只属于日报/周报采信层；标准公司 SQL 只导出已发布日报中已采信且 MiniMax ready 的条目。
- 当前主要缺口：更多同步 object_type 与冲突解决 UI、导出前字段长度/URL 长度/HTML 污染摘要、WP2 后的干净环境 §9 全量业务验收证据、超出 RSS 当前窗口的深度历史补采、Tech Insight Loop 生产库实机全量导入验收、周报自动正文、从日报/周报沉淀 insight/requirement/task 的完整追溯、硬件/半导体 domain pack 样例。

## 2. 单一事实源

- 总体目标、主链路、第一版边界：`docs/00-system-design.md`
- 开发顺序和验收：`docs/implementation-handoff.md`
- 阶段施工计划和验收命令：`docs/01-implementation-plan.md`
- 开发准则和修改同步规则：`AGENTS.md`
- 机器可读字段和流程：`config/contracts/*.json`
- contracts 目录说明：`config/contracts/README.md`
- AI 兼容标签和长期板块：`config/taxonomy/*.json`
- 旧系统事实：`docs/legacy-system-spec.md` 与私有参考仓 `InfoWatchtower-References`

如果模块文档和总纲冲突，以总纲为准；如果自然语言文档和 JSON 契约冲突，开发前必须同时更新两者。

## 3. 模块文档

- `docs/data-examples.md`：数据流样例。
- `docs/software-design-description.md`：AI情报官 SDD 总装版，覆盖设计方法、架构、模块、DFX、时序和测试设计。
- `docs/01-implementation-plan.md`：第一版施工顺序、阶段交付物和验收命令。
- `docs/ingestion-adapter-dedup-spec.md`：采集、标准化和去重。
- `docs/data-format-mapping.md`：信息源、业务字段、公司 SQL 三层映射。
- `docs/data-lineage-and-storage.md`：存储、追溯、审计。
- `docs/feedback-heat-scoring.md`：点赞、评论、评分、热度和来源评分。
- `docs/api-and-ui-implementation.md`：后端 API、前端页面和验收。
- `docs/auth-unified-login.md`：公网/内网统一登录。
- `docs/auth-security-roadmap.md`：公网登录安全、Google SSO、公司 IDaaS 接入计划。
- `docs/workspace-module-model.md`：工作台、共享数据源、候选池、标签和情报板块设计。
- `docs/deployment-ops.md`：部署、备份、自动发布。
- `docs/development-quickstart.md`：当前工程骨架的本地启动说明。
- `docs/multi-environment-sync.md`：公网/内网多数据库同步。
- `docs/extension-points.md`：可插拔扩展点。
- `docs/strategic-intelligence-platform.md`：愿景展开附录。
- `docs/technical-debt-and-refactor-log.md`：技术债务、微重构台账和后续治理计划。
- `docs/ai-collaboration-engineering-case.md`：AI情报官协作研发案例总结。

## 4. 修改规则

改设计时按影响范围同步：

- 改主链路：更新 `docs/00-system-design.md`、`docs/implementation-handoff.md` 和相关 `config/contracts/*.json`。
- 改某个模块：更新对应模块文档和相关 contract。
- 改字段：更新 contract、模块文档、数据样例。
- 改 SQL 导出：更新 `config/contracts/news_sql_mapping.json`、`docs/data-format-mapping.md`、`docs/data-examples.md`。
- 改登录：更新 `config/contracts/auth_modes.json`、`docs/auth-unified-login.md`、`docs/auth-security-roadmap.md`、`docs/deployment-ops.md`。
- 改工作台/模块/共享源：更新 `config/contracts/workspace_model.json`、`config/contracts/source_fields.json`、`docs/workspace-module-model.md`、`docs/00-system-design.md`。
- 改标签体系：更新 `config/contracts/label_model.json`、`config/taxonomy/*.json`、对应模块文档和数据样例。
- 改公网/内网同步：更新 `config/contracts/sync_strategy.json`、`docs/multi-environment-sync.md`。
- 改前端工作台样式：更新 `docs/api-and-ui-implementation.md`，并确认 `AppShell.vue`、`SourcesPage.vue`、`base.css` 没有出现和高保真基线冲突的重复实现。

不要只改一处，让另一个文档保留旧逻辑。
