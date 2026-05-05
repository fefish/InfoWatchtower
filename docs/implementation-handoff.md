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
- `config/taxonomy/intelligence_domains.json`

## 2. 不要重新发明的决策

以下决策已经定稿，第一版实现不要改：

- 后端：Python FastAPI。
- 数据库：PostgreSQL。
- ORM/迁移：SQLAlchemy + Alembic。
- 前端：Vue 3 + TypeScript + Vite。
- 前后端同一个 monorepo。
- 当前 AI 标签不是长期业务上限。长期以 domain/domain pack 扩展板块。
- `domain_code`、`visibility_scope`、`sync_policy` 是横切字段，数据源、raw、news 和同步都要保留。
- `workspace_code` 是工作台边界，不要用 `domain_code` 代替工作台。
- AI 工具桌面、规划部情报工作台等工作台必须复用同一套前后端和同一套情报主链路。
- 所有工作台默认都有数据源、候选池、日报、周报、专题和导出；可选模块只能做加法。
- 数据源先进入共享池 `data_sources`，工作台通过 `workspace_source_links` 启用和配置，不复制数据源定义。
- 标签统一走 `label_sets/labels/content_labels`，不要给每个工作台或 source_type 增加专用标签字段。
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

从这些文件导入初始源：

- `config/seeds/legacy/wiseflow_sources.json`
- `config/seeds/legacy/rss_sources.json`
- `config/seeds/legacy/page_sources.json`

验收：

- 导入后数量与 `config/contracts/source_fields.json` 的 `seed_counts` 对齐。
- 导入后旧源进入共享数据源池，并为默认规划部工作台创建启用链接。
- `folo_metadata.info_category = 学术论文` 的 RSS 源导入为 `paper_rss`。
- wiseflow 作为 `source_type=wiseflow` 单独存在，不要混成 RSS。

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

### 5.7 去重

实现硬去重：

- URL 去重。
- 标题 + 日期兜底。
- winner 选择。
- loser 回写 `active = false`、`duplicate_of = winner.id`。

验收：

- 同 canonical URL 的两条新闻只保留一个 active winner。
- loser 的 raw 数据仍可追溯，不删除。
- 不同 URL 的相似主题第一版不要自动删除。

### 5.8 推荐

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

- 只推荐 `active = true` 的 winner。
- 每日推荐上限默认 15。
- 同源每日上限默认 2。
- 推荐原因写入 `recommendation_reason`。

### 5.9 日报与编辑

实现：

- 根据推荐 run 生成日报草稿。
- 管理员采信、剔除、排序。
- 管理员编辑标题、摘要、结构化正文。
- 发布日报。

验收：

- 编辑字段写入 `daily_report_items.editor_*`。
- 原始 `generated_news` 不被覆盖。
- 已发布日报可按时间线展示。

### 5.10 公司 SQL 导出

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

### 5.11 公网到内网同步骨架

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
- 数据源列表页。
- 数据源详情页：配置、启停、最近抓取、来源评分。
- 日报时间线页：展示、点赞、评分、评论。
- 日报编辑页：采信、剔除、排序、编辑、发布。
- 周报候选页：先做列表和采信入口。
- SQL 导出页。
- 用户和角色管理页。

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
