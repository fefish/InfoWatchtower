# 实施交接任务书

本文档面向能力较弱的工程师或 AI。目标不是重新讨论架构，而是按步骤把 InfoWatchtower 开发成可运行系统。

如果与其他文档有冲突，以 `docs/00-system-design.md`、`config/contracts/*.json` 和本文档为准。

## 1. 先读顺序

接手者不要从零散附录开始。必须按顺序阅读：

1. `docs/00-system-design.md`
2. `docs/01-implementation-plan.md`
3. `docs/data-examples.md`
4. `docs/README.md`
5. `docs/ingestion-adapter-dedup-spec.md`
6. `docs/data-format-mapping.md`
7. `docs/data-lineage-and-storage.md`
8. `docs/auth-unified-login.md`
9. `docs/deployment-ops.md`
10. `docs/multi-environment-sync.md`
11. `docs/extension-points.md`

`docs/strategic-intelligence-platform.md` 是愿景展开附录，核心愿景已经合并到 `docs/00-system-design.md`。实现第一版时不需要先读它。

机器可读契约必须同时遵守：

- `config/contracts/source_fields.json`
- `config/contracts/adapter_pipeline.json`
- `config/contracts/news_sql_mapping.json`
- `config/contracts/auth_modes.json`
- `config/contracts/workspace_model.json`
- `config/contracts/label_model.json`
- `config/contracts/extension_points.json`
- `config/contracts/strategic_loop.json`
- `config/contracts/sync_strategy.json`
- `config/taxonomy/news_categories.json`
- `config/taxonomy/source_tags.json`
- `config/taxonomy/intelligence_domains.json`

## 2. 不要重新发明的决策

以下决策已经定稿，第一版实现不要改：

- 后端：Python FastAPI。
- 数据库：PostgreSQL。
- ORM/迁移：SQLAlchemy + Alembic。
- 前端：Vue 3 + TypeScript + Vite。
- 前后端同一个 monorepo。
- 当前规划部成品新闻一级标签是旧系统约定的 AI 十分类。长期扩展用 domain/domain pack，但不要把数据源方向标签误写进 `generated_news.category`。
- `domain_code`、`visibility_scope`、`sync_policy` 是横切字段，数据源、raw、news 和同步都要保留。
- `workspace_code` 是工作台边界，不要用 `domain_code` 代替工作台。
- 规划部情报工作台等工作台必须复用同一套前后端和同一套情报主链路。
- 所有工作台默认都有数据源管理、候选池、日报、周报和导出；可选模块只能做加法，且默认关闭。
- 数据源先进入共享池 `data_sources`，工作台通过 `workspace_source_links` 启用和配置，不复制数据源定义。
- 成品新闻一级/二级标题统一走 `label_sets/labels/content_labels`，不要给每个工作台或 source_type 增加专用新闻分类字段，也不要为它们新增工具管理页面。
- 工作台统一新闻标签和新闻结构策略保存在 `workspaces.config_json.label_policy`。模型生成新闻结构和去重后标签定稿都必须读取这套策略。`planning_intel` 默认 `label_set_code=ai_sql_categories`、`news_format_code=company_sql_v1`、`export_category_mode=news_primary`，一级标签来自 `config/taxonomy/news_categories.json`，必须生成 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 五个公司 SQL 兼容内容字段；`config/taxonomy/source_tags.json` 只作为数据源侧方向标签，服务源管理、覆盖分析和评分先验；`ai_tools` 默认是“工具新功能、工具新案例、工具新技术”，且每个一级标签下都有 `cursor/claude code/opencode/codex` 二级标签。
- 原始数据必须进入 `raw_items.raw_payload_json`，不能只保存清洗后的字段。
- 去重必须发生在 `news_items` 之后、推荐之前。
- 标准公司 SQL 只导出已发布日报里 `adoption_status = 2` 的条目。
- 公网和内网登录共用本地 `users/roles/permissions`，区别只在 `AuthAdapter`。
- 公网/内网不分叉代码。通过 `.env.production`、`AUTH_MODE` 和 sync 策略切换部署形态。

## 3. 第一版目标

第一版不是一次性做完所有宏大功能。第一版要做到：

- 能登录。
- 能导入旧种子源配置。
- 能抓取 RSS。
- 能保留 raw 数据。
- 能标准化成 `news_items`。
- 能按 URL 和标题日期去重。
- 能生成推荐候选。
- 能人工采信进日报。
- 能编辑日报新闻标题、摘要、正文。
- 能导出兼容公司内部平台的 SQL。
- 能从日报新闻沉淀最小的 insight/requirement/task 闭环。
- 能在单台云服务器 Docker Compose 部署。

wiseflow、页面监控、论文 API、自定义爬虫可以先做接口骨架和少量实现，但表结构和 adapter 注册机制必须预留好。

## 4. 代码目录

按这个目录建，不要随意拆散：

```text
backend/
  app/
    main.py
    core/
      config.py
      database.py
      security.py
    models/
    schemas/
    auth/
    adapters/
    ingestion/
    dedupe/
    scoring/
    reports/
    exports/
    admin/
    workers/
  alembic/
  tests/
frontend/
  src/
    pages/
    components/
    api/
    stores/
    router/
deploy/
  docker-compose.prod.yml
  nginx.conf or Caddyfile
```

## 5. 后端实施顺序

### 5.1 项目骨架

交付：

- FastAPI 应用可启动。
- `/healthz` 返回数据库和应用状态。
- Alembic 可运行。
- 测试框架可运行。

验收：

```text
pytest
alembic upgrade head
```

都能通过。

### 5.2 数据库模型

先实现这些表：

- `users`
- `roles`
- `permissions`
- `user_roles`
- `data_sources`
- `workspace_source_links`
- `label_sets`
- `labels`
- `content_labels`
- `raw_items`
- `news_items`
- `dedupe_groups`
- `dedupe_group_items`
- `recommendation_runs`
- `recommendation_items`
- `generated_news`
- `daily_reports`
- `daily_report_items`
- `weekly_reports`
- `weekly_report_items`
- `reactions`
- `ratings`
- `comments`
- `editorial_actions`
- `audit_logs`
- `export_jobs`
- `export_job_items`
- `sync_outbox`
- `sync_inbox`
- `sync_runs`
- `sync_conflicts`
- `insights`
- `strategic_implications`
- `requirements`
- `requirement_source_links`
- `topic_tasks`
- `workspaces`
- `workspace_sections`
- `workspace_memberships`

如果第一版工期紧，`insights/requirements/topic_tasks` 可以先做最小字段，但表和外键必须预留，避免系统停在“新闻展示”层。

最低外键链路必须成立：

```text
daily_report_items
-> generated_news
-> recommendation_items
-> dedupe_group_items
-> news_items
-> raw_items
-> data_sources
```

验收：

- 任意一条日报条目可以查回原始 `raw_items.raw_payload_json`。
- 编辑日报不修改 `raw_items` 和 `generated_news` 原始记录。

### 5.3 登录

先实现：

- `public_password`
- `local`
- `intranet_header`

统一流程：

```text
AuthAdapter -> ExternalIdentity -> IdentityResolver -> users -> session/JWT -> RBAC
```

验收：

- 公网账号密码能登录。
- 内网模式下，可信 header 能自动创建用户。
- 业务接口只认本地 `user_id` 和本地角色。
- 修改认证模式不需要改日报、数据源、评论等业务代码。

### 5.4 数据源导入

当前进度：已实现旧种子源导入 API、补充信息源台账导入、数据源列表 API、工作台统一标签/新闻结构策略 API、工作台源链接配置 API、单源手动抓取 API、工作台级 ingestion run API 和 Redis/RQ worker + scheduler 调度入口。导入器会先读取旧 113 个种子源，再读取 `source_catalog/information_source_registry_20260511.csv` 中 248 条可导入 RSS 记录；合计 361 条导入记录按 `source_type + url` 去重后进入 294 个共享数据源，规划部工作台 v1 默认全部启用。补充台账只用于新增源、源侧方向标签和源质量评分；CSV 状态/纳入建议保留在 metadata 中做评分先验，不再作为初始停用开关。管理员可在数据源页增删改当前工作台统一新闻一级/二级标签策略，并能查看/配置 `news_format_code`、`export_category_mode` 与生成稿必填内容字段；`planning_intel` 成品新闻一级标签已恢复为旧系统 AI 十分类，数据源侧新增 `source_tags/source_secondary_tags` 方向标签。单个源只配置启用、权重和日限。RSS/paper RSS/page_manual/page_monitor 源可手动触发抓取到 `raw_items`，重复抓取按 `(data_source_id, entry_key)` 幂等更新；wiseflow 源保留为 adapter 扩展入口，未配置真实接口时不会贡献数据。`/api/ingestion/runs` 当前同步执行工作台级抓取，默认覆盖该工作台启用的 `rss/paper_rss/page_manual/page_monitor/wiseflow` 源；抓取阶段支持并发池和单源超时，默认 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`，避免几百个源被串行阻塞。完整日报流水线通过 `/api/pipeline/daily-runs` 默认沿用同一套全量源类型。scheduler 默认关闭自动任务，开启后定时把每日完整流水线入队给 worker 执行。前端已改为浅色工作台壳、数据库驱动分组导航、信息流式数据源列表和参考高保真风格的右侧标签策略面板；`/ingestion-runs` 已接入抓取运行历史和安全运行入口，用于解释覆盖率问题。周报、需求、任务、同步和审计目前是模块化路线页，不代表后端 API 已完成。

从这些文件导入初始源：

- `config/seeds/legacy/wiseflow_sources.json`
- `config/seeds/legacy/rss_sources.json`
- `config/seeds/legacy/page_sources.json`
- `config/seeds/legacy/source_catalog/information_source_registry_20260511.csv`

验收：

- 导入后数量与 `config/contracts/source_fields.json` 的 `seed_counts` 对齐。
- 导入后旧源进入共享数据源池，并为所有已启用的默认工作台创建 `workspace_source_links`；源定义仍只保存一份。
- `folo_metadata.info_category = 学术论文` 的 RSS 源导入为 `paper_rss`。
- wiseflow 作为 `source_type=wiseflow` 单独存在，不要混成 RSS。
- 前端首页当前显示阶段 5 进度；数据源页应能继续验收阶段 3 的增删改工作台统一一级/二级标签策略、查看和保存工作台新闻结构字段、单源启用/权重/日限、手动触发 RSS/paper RSS/page_manual/page_monitor 抓取；单源配置里不得维护标签；`/ingestion-runs` 可用 `limit=0` 验收抓取 run 权限和接口链路。
- 重复抓取同一个 RSS 源时，`raw_items` 按 `(data_source_id, entry_key)` 更新，不重复插入。
- `POST /api/ingestion/runs` 能创建工作台级抓取 run；`GET /api/ingestion/runs` 和 `GET /api/ingestion/runs/{id}` 能查看历史与详情。

### 5.5 Adapter 注册

实现统一接口：

```python
class SourceAdapter:
    source_type: str

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        ...
```

第一版必须实现：

- `RssFeedAdapter`
- `ManualNewsAdapter`
- `WiseflowReadInfoAdapter` 的接口骨架
- `PageListingAdapter` 的接口骨架
- `PaperMetadataEnricher` 的接口骨架

验收：

- 新增 source_type 时，只需注册 adapter，不改 dedupe、scoring、report、export 主链路。
- adapter 输出字段满足 `config/contracts/adapter_pipeline.json`。

### 5.6 raw 到 news 标准化

当前进度：已实现最小闭环。`backend/app/normalization/news.py` 提供 `normalize_workspace_raw_items()`，`POST /api/news-items/normalize` 可按工作台把已启用源的 raw 标准化成 news。标准化结果继承 `workspace_code`、`domain_code`、`visibility_scope`、`sync_policy`，保留 `raw_item_id` 和 `data_source_id` 追溯链路，生成 canonical URL、normalized title、summary、content、author 和 dedupe key。URL、标题和日期都不足以生成 dedupe key 的 raw 会被跳过，不进入推荐链路。

实现 `normalize_to_news_item(raw_item)`。

规则：

- `source_url` 来自 raw URL。
- `canonical_url` 由 URL 规范化得到。
- `content` 优先正文，其次摘要，再其次标题。
- `created_at` 优先原始发布时间，没有则用抓取时间并记录质量问题。
- `dedupe_key` 优先 URL，没有 URL 时用标题日期。

验收：

- `docs/data-examples.md` 里的 RSS 样例可以变成对应 `news_items`。
- URL、标题、时间都缺失的 raw item 不进入推荐链路。
- `GET /api/news-items?workspace_code=planning_intel` 能看到 `raw_item_id`、`canonical_url`、`dedupe_key` 和 `active`。

### 5.7 去重

当前进度：已实现保守硬去重。`dedupe_groups` 按 `workspace_code + dedupe_key` 唯一，避免不同工作台争夺同一个 winner；同一共享 raw 可被多个工作台各自标准化和去重。

实现硬去重：

- URL 去重。
- 标题 + 日期兜底。
- winner 选择。
- loser 回写 `active = false`、`duplicate_of = winner.id`。

验收：

- 同 canonical URL 的两条新闻只保留一个 active winner。
- loser 的 raw 数据仍可追溯，不删除。
- 不同 URL 的相似主题第一版不要自动删除。
- `GET /api/dedupe-groups?workspace_code=planning_intel` 能看到 winner、loser、`duplicate_reason` 和 `rank_score`。

### 5.8 推荐

当前进度：已实现可回填闭环，并新增内容级准入层。`POST /api/pipeline/daily-runs` 可按工作台和 `day_key` 执行抓取、标准化/去重、推荐和日报草稿；`POST /api/recommendation/runs` 可只重跑推荐层。推荐读取目标日期的 `dedupe_groups` winner，先计算 `P0/P1/P2/P3/R` 准入等级，再写入 `recommendation_runs/recommendation_items`，并为 selected 推荐生成 `generated_news`。推荐分数包含 `quality_score/topic_score/freshness_score/feedback_score/diversity_score/source_score/heat_score/final_score` 和 `recommendation_reason`；`recommendation_reason` 必须包含 `admission=...`、`pool=...`、`content_value=...`，`recommendation_runs.summary_json.admission` 汇总各等级、内容池和噪声类型。`planning_intel` 默认采用技术情报优先策略：提升 AI 软件、AI 基础设施、模型工程、推理/训练、RAG、多智能体、Agent 记忆、硬件厂商技术路线、友商技术动态、AI 芯片、GPU 集群、数据中心架构和通信系统信号；但源侧方向标签只是弱先验，厂商源/硬件源不能绕过内容级准入，单条内容仍要有架构、推理、模型服务、芯片、数据中心、通信系统、标准或工程实现证据。降权融资、财报、股价、宏观产业收入数据、传闻曝光、采购/中标/集采、消费硬件、活动预告、宣传推广会/品牌行动、泛商业合作、纯营销、航天火箭等离题工程新闻、法律/版权元讨论、标题党、社会/教育离题内容和离题生物医学/纯学术论文。日报选择先选 P0/P1，再用无噪声且有明确技术信号的 P2 补齐；P2 paper_rss、带噪声 P2、P3/R 默认不进日报；每个源仍受 `source_daily_limit` 限制，`paper_rss` 默认不超过日报条数约 10%，单个内容池默认不超过约 40%，避免新闻过度集中。MiniMax 生成通过 `MINIMAX_GENERATION_ENABLED=true` 开启，按旧参考脚本已验证的中国区 OpenAI-compatible `https://api.minimaxi.com/v1/chat/completions` 调用。生成 prompt 强制简体中文和旧系统五段正文；失败时不阻塞流水线，但只会落回 `rule_v1:fallback` 且标记 `fallback_needs_review`，不能直接导出标准公司 SQL。

`backend/app/pipeline/daily.py` 已提供每日完整流水线：可选抓取、标准化/去重、按 `day_key` 推荐、结构化生成和日报草稿。`POST /api/pipeline/daily-runs` 与 scheduler 都调用同一套 service；如果只想抓取，设置 `SCHEDULER_JOB_MODE=ingestion_only`。

实现可重跑的推荐 run。

评分字段：

- `quality_score`
- `topic_score`
- `freshness_score`
- `feedback_score`
- `diversity_score`
- `source_score`
- `heat_score`
- `final_score`

验收：

- 只推荐目标 `day_key` 且 `active = true` 的 winner。
- 每日推荐上限默认 15。
- 同源每日上限默认 2。
- 推荐原因写入 `recommendation_reason`。

### 5.9 日报与编辑

当前进度：已实现可回填闭环。推荐 run 可创建或替换 `daily_reports/daily_report_items` 草稿；`GET /api/daily-reports`、`GET /api/daily-reports/{id}` 可查看日报；`PATCH /api/daily-report-items/{id}` 可编辑日报层覆盖字段；`POST /api/daily-reports/{id}/publish` 可发布。`generated_news.content_json` 已按 `company_sql_v1` 保证 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 必填字段；MiniMax 结果会标记 `ready`，规则 fallback 只作为待复核草稿。前端 `/daily-reports` 可选择日期并点击生成日报草稿，触发完整流水线；列表只展示 brief，点击条目后在详情弹窗里查看完整结构化正文，并立即完成采信切换、条目编辑、点赞、评分、评论和追溯查看。

实现：

- 根据推荐 run 生成日报草稿。
- 管理员采信、剔除、排序。
- 管理员编辑标题、摘要、结构化正文。
- 发布日报。

验收：

- 编辑字段写入 `daily_report_items.editor_*`。
- 原始 `generated_news` 不被覆盖。
- 已发布日报可按时间线展示。

### 5.10 反馈

当前进度：已实现日报条目的点赞、评分、评论和楼中楼最小 API：

```text
POST /api/daily-report-items/{id}/reactions
POST /api/daily-report-items/{id}/ratings
GET  /api/daily-report-items/{id}/comments
POST /api/daily-report-items/{id}/comments
```

反馈会同时挂到 `daily_report_item` 和对应 `news_item`，后续推荐 run 可读取这些数据进入 `heat_score/feedback_score`。

### 5.11 公司 SQL 导出

当前进度：已实现标准日报 SQL 导出。`POST /api/exports/company-sql/daily-reports/{daily_report_id}` 会校验日报必须 `status = published`，并且只导出 `daily_report_items.adoption_status = 2`、`generated_news.generation_status = ready` 且 `generated_by` 非 `rule_v1` 的采信项；每条采信项写出旧系统兼容的 4 条 SQL，同时写入 `export_jobs` 和 `export_job_items`。导出的 `content_json` 只保留 `background/effects/eventSummary/technologyAndInnovation/valueAndImpact` 五个旧内网字段，InfoWatchtower 自己的 `source/raw/news` 追溯信息保留在关系表，不进入公司 SQL 的 JSON。标准模式下 `ai_journal_analysis.category` 和 `t_news_data_info.category` 使用 `generated_news.category`，即旧系统 AI 十分类。`ai_journal.source_title` 和 `ai_journal.content` 导出前必须清洗为纯文本，去除 HTML 标签和 script/style 内容；`ai_journal.created_at` 和 `ai_journal_analysis.created_at` 都必须保留旧脚本同款列顺序和旧式日期字面量：`'YYYY-MM-DD HH:MM:SS'`，来源缺失发布时间时兜底为日报 `day_key 09:00:00`，不得改成 `STR_TO_DATE`、`CAST`，也不得省略 `ai_journal_analysis.created_at`；SQL 文件头统一为 `InfoWatchtower Company SQL Preview`；所有预览 SQL 必须先通过 `python3 scripts/validate_company_sql.py` 校验，脚本以 `outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql` 为基准，逐字段校验 4 表顺序、列名、URL 串联、日期、五段正文 JSON、HTML 污染和禁用写法；原始 HTML 保留在 `raw_items.raw_content/raw_payload_json`。前端 `/exports` 已接入已发布日报选择、导出历史、SQL 生成、预览和下载；后续补字段长度/URL/HTML 污染校验和 SQL 条目级追溯 UI。

已验证的本地输出：

- `2026-04-30` 规划部日报草稿、发布和公司 SQL 预览。
- `2026-05-01` 到 `2026-05-08` 批量日报、发布和合并 SQL 预览。
- 批量 SQL 中每条采信新闻固定生成 4 类 SQL，`content_json` 只含旧系统五段字段。
- 第一版 `focus_id` 默认 `1`，`adoption_status` 默认 `2`，日报日期和 SQL 日期按 `day_key` 对齐。
- 导出 SQL 不应包含 `<span>`、`<p>`、script/style 等 HTML 污染。
- 每次导出或手工整理 SQL 后必须运行 `python3 scripts/validate_company_sql.py`；如只需要统一文件标题，先运行 `python3 scripts/validate_company_sql.py --fix-headers`。

注意：`outputs/sql/previews/` 是本地验收产物，已被 `.gitignore` 忽略，不提交 Git。

实现标准导出：

```text
daily_reports.status = published
daily_report_items.adoption_status = 2
```

每条新闻固定导出 4 条 SQL：

1. `ai_journal`
2. `ai_journal_focus`
3. `ai_journal_analysis`
4. `t_news_data_info`

验收：

- 字段映射与 `config/contracts/news_sql_mapping.json` 完全一致。
- SQL 使用旧系统安全写法。
- SQL 导出任务写入 `export_jobs` 和 `export_job_items`。

### 5.11.1 抓取覆盖率和候选数解释

启用源数量不是当天候选数量。当天候选必须经过：

```text
workspace_source_links enabled
-> adapter 抓取成功
-> feed 或页面当天实际有条目
-> published_at 归入目标 day_key
-> raw 标准化成 news
-> dedupe 后保留 active winner
```

例如规划部当前 294 个共享源全部启用，但某一天只有少量候选时，常见原因是：

- 源当天没有发布内容，尤其周末。
- RSS 只暴露最近窗口，无法从今天回拉完整历史。
- 源返回 403、timeout 或解析失败。
- 条目的 `published_at` 落在别的日期。
- 去重后多个来源合并成一个 winner。

后续实现必须补：

- 抓取覆盖率页面或 API：按 day_key 展示启用源数、成功源数、失败源数、每源 raw 数、失败原因、最近成功时间。
- 失败源重试和告警。
- 历史补采/backfill：RSS 当前窗口以外的日期要走页面归档、官方 API 或 crawler，不能只靠普通 RSS 拉取。
- 历史补采任务模型：第一版可以复用 `ingestion_runs`，在 `params_json` 写入 `run_type=historical_backfill`、`target_day_start`、`target_day_end`、`backfill_mode`、`source_scope` 和 `retry_policy`；`summary_json.sources` 仍记录每源成功、失败、raw 新增/更新和失败原因。
- 补采 adapter 顺序：`paper_api/arxiv/openalex/semantic_scholar` 按日期回查优先；其次是厂商/标准组织归档页、sitemap 和分页 crawler；最后才是通用搜索、手工 CSV 或 SQL 导入。普通 RSS 只能作为当前窗口抓取，不承担完整历史恢复承诺。

### 5.12 公网到内网同步骨架

第一版先实现应用层同步骨架，不需要一开始做实时同步。

必须实现：

- `sync_outbox`
- `sync_inbox`
- `sync_runs`
- `sync_conflicts`
- 公网生成同步包。
- 内网导入同步包。

验收：

- 同步包格式符合 `docs/multi-environment-sync.md`。
- 同步包不包含 token、cookie、password、secret、`.env`。
- 重复导入同一包不会重复写数据。
- `visibility_scope = restricted` 的对象不会自动同步。
- 内网评论、评分、采信、需求、任务默认不回流公网。

## 6. 前端实施顺序

API 与页面细节见 `docs/api-and-ui-implementation.md`。

第一版页面：

- 登录页。
- 数据源列表页：已实现共享源信息流、工作台统一标签/新闻结构、单源启停/权重/日限。
- 数据源详情页：已实现配置、启停、最近抓取、来源评分。
- 候选池页：已实现 winner/loser、重复来源和候选搜索；后续补推荐分、采信状态和追溯入口。
- 推荐运行页：已实现推荐 run 历史、创建推荐 run、分数拆解和是否进入日报。
- 抓取覆盖率页：已实现 ingestion run 摘要和安全运行入口；后续补每源明细和历史补采。
- 日报时间线页：已实现展示、点赞、评分、评论、采信和编辑弹窗。
- 日报详情/编辑路由：已实现独立详情与轻编辑入口。
- SQL 导出页：已实现已发布日报选择、导出历史、SQL 生成、预览和下载。
- 用户和角色管理页：已实现。
- 周报、需求、任务、同步、审计：当前为模块路线页，后续补真实 API 后升级为业务页。

前端不要做营销首页，打开后就是工作台。

## 7. 必须写的测试

最低测试：

- RSS entry -> `raw_items`。
- `raw_items` -> `news_items`。
- URL canonicalize。
- URL 硬去重。
- 标题日期兜底去重。
- 推荐只处理 active winner。
- 日报编辑不覆盖原始数据。
- 评论支持 `parent_id/root_id`。
- `intranet_header` 自动创建用户。
- 一条日报新闻导出 4 条 SQL。
- SQL 字段映射与契约一致。

## 8. 容易犯错的地方

不要犯这些错：

- 不要只实现 RSS，忘记 wiseflow、页面、论文和内部源的 adapter 插槽。
- 不要在 adapter 里做全局最终去重。
- 不要物理删除重复新闻和 raw payload。
- 不要把模型输出的 `sourceUrl` 当真，导出时必须使用原始 `news_items.source_url`。
- 不要把公网账号体系和内网账号体系写成两套业务用户表。
- 不要把数据库密码、API token、`.env` 提交到 GitHub。
- 不要把候选新闻全部导出到公司 SQL，只导出已发布且已采信的日报新闻。

## 9. 第一版完成定义

当以下流程跑通，第一版才算完成：

```text
管理员登录
-> 导入旧种子源
-> 抓取至少一个 RSS 源
-> raw_items 入库
-> news_items 标准化
-> 去重
-> 推荐
-> 生成日报草稿
-> 管理员编辑并发布
-> 用户点赞/评论/评分
-> 导出公司 SQL
-> 从 SQL 追溯回 raw_items
```
