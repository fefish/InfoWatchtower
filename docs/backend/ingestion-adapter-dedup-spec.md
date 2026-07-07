# 采集 Adapter、统一结构与去重规格

这份文档是后端采集与候选层的专题附录。项目入口是 `docs/00-system-design.md`；本文只展开多源数据如何进系统、怎么映射成统一结构、在哪里去重、去重规则是什么。

机器可读契约：

- `config/contracts/adapter_pipeline.json`
- `config/contracts/source_fields.json`
- `config/contracts/news_sql_mapping.json`

## 1. 当前是否足够开发

当前仓库已经具备开发前置上下文：

- 全量种子源：`config/seeds/legacy/`
- 数据源字段契约：`config/contracts/source_fields.json`
- 采集与去重契约：`config/contracts/adapter_pipeline.json`
- 新闻到 SQL 映射：`config/contracts/news_sql_mapping.json`
- 新闻一级标签：`config/taxonomy/news_categories.json`
- 数据源方向标签：`config/taxonomy/source_tags.json`
- 登录设计：`docs/auth-unified-login.md`
- 旧系统规格：`docs/legacy-system-spec.md`

当前仓库已经有可运行的 `backend/`、`frontend/`、数据库迁移和测试；采集侧已完成 adapter 框架、单源 RSS/paper RSS/page_manual/page_monitor 抓取、工作台级 ingestion run API，以及 Redis/RQ worker + scheduler 调度入口。标准化与去重侧已完成 `POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups` 的阶段 4 闭环；推荐与日报侧已完成 `POST /api/pipeline/daily-runs`、`POST /api/recommendation/runs`、日报草稿、发布、条目编辑和点赞/评分/评论的阶段 5 可回填闭环。

## 2. Adapter 的职责

每类数据源都有自己的输入结构，因此必须通过 Adapter 接入。

Adapter 负责：

- 读取 `data_sources.fetch_config`。
- 抓取或接收源数据。
- 生成稳定的 `entry_key`。如果源返回的 id/跳转 URL 超过 `raw_items.entry_key` 的 255 长度上限，入库前必须做“前缀 + hash 后缀”的确定性缩短；原始完整值仍保留在 `raw_payload_json`。
- 提取基础字段：标题、URL、摘要、正文候选、发布时间。
- 保存完整原始 payload 到 `raw_payload_json`。
- 输出统一的 `raw_items`。

Adapter 不负责：

- 不做最终推荐。
- 不决定是否进入日报。
- 不删除旧数据。
- 不把候选直接写成公司 SQL。

## 3. 源类型与 Adapter

| source_type | Adapter | 说明 |
| --- | --- | --- |
| `wiseflow` | `WiseflowReadInfoAdapter` | 旧系统原始聚合源，必须走 `POST /read_info` 分页 |
| `rss` | `RssFeedAdapter` | 普通 RSS/Atom |
| `paper_rss` | `RssFeedAdapter + PaperMetadataEnricher` | 论文 RSS，后续补 arXiv/DOI/PDF/作者 |
| `page_monitor` | `PageListingAdapter` | 列表页抓链接，再抓详情页 |
| `page_manual` | `ManualPageAdapter` | 手工 seed URL |
| `crawler` | `CustomCrawlerAdapter` | 自定义爬虫 |
| `csv` | `CsvFileAdapter` | 本地/桌面 CSV 源，后续按 CSV schema 映射为 raw items |
| `paper_api` | `PaperApiAdapter` | arXiv API、Semantic Scholar、OpenAlex、Crossref |
| `paper_page` | `PaperPageAdapter` | Hugging Face Papers 等页面 |
| `manual` | `ManualNewsAdapter` | 人工补录 |
| `internal` | `InternalSourceAdapter` | 未来内部数据源 |

## 4. 是删减还是补充

原则：原始层不删减，标准层做映射和补充。

### 原始层 `raw_items`

必须尽量完整保存：

- 原始 payload 全量进入 `raw_payload_json`。
- 原始标题进入 `source_title`。
- 原始 URL 进入 `source_url`。
- 原始摘要/正文进入 `raw_summary` / `raw_content`。
- 原始发布时间进入 `published_at`。

如果某个源没有某个字段，就留空并记录 `extract_status` / `extract_error`，不要编造。

### 标准层 `news_items`

标准层做这些事：

- URL canonicalize。
- 时间解析为统一 UTC 存储，展示和日报 key 使用北京时间。
- 内容字段选择：优先正文，其次摘要，再其次标题。
- 生成 `dedupe_key`。
- 记录 `focus_id`、`source_kind`、`source_name`。
- 继承 `domain_code`、`visibility_scope`、`sync_policy`。
- 标记 `active`、`duplicate_of`、`normalization_status`。

这一步是“映射 + 补充 + 派生字段”，不是删除原始信息。原始信息仍可从 `raw_items.raw_payload_json` 找回。

## 5. 统一数据结构

### raw_items

```text
id
data_source_id
domain_code
visibility_scope
sync_policy
source_type
source_name
entry_key
source_url
canonical_url
source_title
raw_summary
raw_content
published_at
fetched_at
raw_payload_json
source_specific_json
extract_status
extract_error
```

### news_items

```text
id
raw_item_id
domain_code
visibility_scope
sync_policy
source_url
canonical_url
source_title
content
created_at
focus_id
source_kind
source_name
dedupe_key
duplicate_of
active
normalization_status
```

### generated_news

```text
id
news_item_id
category
title
summary
key_points
content_json
source_url
created_at
model_provider
model_name
prompt_version
```

生成 `generated_news.category` 时必须读取当前工作台的 `workspaces.config_json.label_policy.allowed_primary_categories`；生成二级标签时读取 `secondary_labels_by_primary` 中当前一级标签下的候选项。生成结构化正文时读取同一策略下的 `news_format_code` 和 `required_content_fields`。第一阶段规划部默认使用 `config/taxonomy/news_categories.json` 的 AI 十分类和 `company_sql_v1` 内容结构，`export_category_mode=news_primary` 时公司 SQL category 直接写 `generated_news.category`。`config/taxonomy/source_tags.json` 只用于数据源侧方向标签，不参与成品新闻 category 定稿。AI 工具桌面默认使用独立工具标签体系。

## 6. 去重在哪一步做

去重发生在：

```text
workspace ingestion run
-> Adapter 抓取
-> raw_items 保存
-> 正文抽取
-> normalize_to_news_item
-> dedupe_grouping
-> post_dedupe_labeling
-> candidate_pool
-> scoring_and_recommendation
-> daily_report_draft
```

也就是说，去重在标准化之后、推荐评分之前。

原因：

- 不同源的原始结构不同，不能在 Adapter 内各自去重后就丢数据。
- 只有映射到统一的 `news_items` 后，wiseflow、RSS、页面源、论文源才能公平比较。
- 推荐评分应该只对去重 winner 进行，否则日报会被重复新闻刷屏。

## 6.1 抓取 run

工作台级抓取 run 是调度层，不改变 adapter 和 raw 字段契约。

第一版已实现：

- `POST /api/ingestion/runs` 创建同步执行的工作台级 run。
- scheduler 可按环境变量把每日完整流水线入队，worker 从 Redis/RQ 执行。生产推荐使用固定墙上时间：`INGESTION_SCHEDULER_DAILY_TIME=09:00`、`INGESTION_SCHEDULER_TIMEZONE=Asia/Shanghai`，并用 `DAILY_PIPELINE_DAY_OFFSET_DAYS=-1` 生成昨天的日报；未设置固定时间时才使用 `INGESTION_SCHEDULER_INTERVAL_SECONDS` 的旧 interval 模式。工作台级抓取支持并发池和单源超时，默认 `INGESTION_CONCURRENCY=8`、`INGESTION_SOURCE_TIMEOUT_SECONDS=25`。
- 默认处理当前工作台已启用、且源本身启用的 `rss/paper_rss/page_manual/page_monitor/wiseflow`。
- `ingestion_runs` 保存 run 参数、状态、处理源数量、成功/失败、拉取数、raw 新增数和 raw 更新数。
- `summary_json.sources` 保存每个源的结果摘要。

尚未实现：失败源重试队列。已实现并发抓取和 scheduler 触发 `ingestion -> normalize/dedupe -> recommendation -> daily_report_draft`；如需只抓取，可设置 `SCHEDULER_JOB_MODE=ingestion_only`。

## 6.2 标准化与硬去重 API

阶段 4 已实现：

- `POST /api/news-items/normalize`：按工作台选取该工作台已启用源的 raw，幂等创建或更新 `news_items`，并重建受影响的去重组。
- `GET /api/news-items`：查看标准化新闻、`raw_item_id`、canonical URL、dedupe key 和 active/duplicate 状态。
- `GET /api/dedupe-groups`：查看去重组 winner、loser、重复原因和 rank score。

重要边界：

- `raw_items` 属于共享原始事实层，不因去重删除。
- `news_items.workspace_code` 使用处理工作台的 code；同一共享 raw 可以被不同工作台各自标准化。
- `dedupe_groups` 按 `workspace_code + dedupe_key` 唯一，避免不同工作台互相覆盖 winner。
- URL、标题和日期都不足以生成 dedupe key 的 raw 只停留在 raw 层，不进入推荐链路。

## 6.3 候选池是什么

候选池不是新的表族，也不是一个新的信息源。它是 `dedupe_groups` 和 winner `news_items` 的工作视图。

候选池页面应展示：

- 每个去重组的 winner。
- 同组重复项数量和来源列表。
- 命中的标签、来源分、热度分和推荐分。
- 管理员采信、剔除、待观察状态。
- 从候选项追溯到 `raw_items.raw_payload_json` 的链路。

日报和周报都从候选池采信，不直接从 raw 原始数据里挑。

## 6.4 覆盖率、失败源和历史补采

不要把“配置了多少源”和“某天有多少候选”混为一谈。规划部工作台 v1 默认全量启用 294 个共享源，只说明这些源会被纳入抓取计划；它不保证每个源在目标日期都贡献候选。

候选数量取决于：

- 该源是否被当前工作台启用，且源本身没有停用。
- adapter 是否抓取成功。
- RSS/feed 当前窗口是否还保留目标日期条目。
- 原始条目的 `published_at` 是否能解析，且按 Asia/Shanghai 归入目标 `day_key`。
- raw 是否满足标准化进入 `news_items` 的最低条件。
- 去重后是否是 active winner。

当前已经记录 `ingestion_runs.summary_json.sources`，并在前端 `/ingestion-runs` 展示运行历史、每源成功/失败、fetched、raw created/updated，以及历史补采的 in-range、out-of-range、missing published_at 和错误原因。下一阶段继续把这些信息和 raw/news/winner 联动统计产品化：

```text
day_key
workspace_code
enabled_source_count
attempted_source_count
succeeded_source_count
failed_source_count
raw_created_count
raw_updated_count
news_candidate_count
active_winner_count
top_failure_reasons
per_source_breakdown
```

历史补采不能只靠普通 RSS。很多 RSS 只暴露最近 N 条，今天拉取不一定能还原 5 天前或 1 个月前的完整内容。需要为关键源逐步补：

- 论文/API：arXiv、OpenAlex、Semantic Scholar、OpenReview、Hugging Face Papers 等可按日期回查的接口，优先用于恢复历史论文候选。
- 官方归档页：厂商技术博客、标准组织、云厂商、硬件厂商的 archive、sitemap、分页列表和详情页 crawler。
- 页面监控增强：对已知页面源补 `since/until`、URL 发现和详情抽取，不能只依赖当前首页。
- 失败源重试：对 timeout/403/connect error 按低并发、长超时、退避策略重试，并把失败原因写入 run summary。
- 手工补录或 CSV/SQL 导入：作为最后兜底，必须仍然写入 `raw_items.raw_payload_json`，保留追溯。

历史补采已经复用 `ingestion_runs`，入口是 `POST /api/ingestion/backfill-runs`，也可以从任务层调用 `run_historical_backfill_job`。当前支持 `rss_window/paper_api/archive_page/sitemap/manual_import`：`rss_window` 不是完整历史恢复承诺，只在目标日期仍出现在当前 feed 窗口时低成本补采；`paper_api` 依赖已注册 adapter；`archive_page` 和 `sitemap` 是轻量 URL 发现入口；`manual_import` 用于人工补录 raw 条目。超出这些能力的完整历史恢复仍要继续建设更强的论文 provider、厂商/标准组织分页归档 crawler 和失败源重试。

补采 run 参数必须明确：

```text
run_type = historical_backfill
target_day_start
target_day_end
backfill_mode = rss_window | paper_api | archive_page | sitemap | manual_import
source_scope = all | selected_source_ids | source_type
retry_policy
include_undated
```

补采验收口径不是“抓了多少源”，而是目标日期新增了多少 `raw_items`、标准化出多少 `news_items`、去重后新增/替换多少 active winner，以及这些新增候选有多少进入推荐/日报。当前 `summary_json` 至少要能回答：

- 每源抓取总数 `fetched`。
- 目标日期内数量 `in_target_range`。
- 目标日期外数量 `out_of_target_range`。
- 缺少 `published_at` 数量 `missing_published_at`。
- 最终 raw `created/updated`。

没有覆盖率和补采之前，日报候选少时应先查 `ingestion_runs`、`raw_items` 和 `news_items` 的日期分布，再判断推荐策略是否需要调整。

## 7. 去重逻辑

第一阶段采用硬去重，沿用旧系统已经验证过的保守逻辑。

### 7.1 canonical URL 去重

如果有 URL，优先使用：

```text
dedupe_key = "url:" + canonical_url
```

`dedupe_key` 必须能写入 `news_items.dedupe_key` 和 `dedupe_groups.dedupe_key` 的 512 长度上限。遇到超长 canonical URL 或超长标题兜底 key 时，标准化层使用确定性 hash 后缀缩短 key；完整 URL 仍保存在 `canonical_url`、`source_url` 和 `raw_items.raw_payload_json`，不影响追溯。

canonicalize 规则：

- scheme 和 host 小写。
- 去掉 URL fragment。
- path 去掉末尾 `/`。
- 去掉追踪参数：`utm_*`、`spm`、`ref`、`ref_src`、`fbclid`、`gclid`。

### 7.2 标题 + 日期兜底

如果没有 URL，使用：

```text
dedupe_key = "title:" + normalize_title(source_title) + "|date:" + published_date
```

`normalize_title`：

- 小写。
- 去 HTML 标签。
- 去标点和多余空格。
- 保留中文、英文、数字。

### 7.3 winner 选择

同一个 `dedupe_key` 下只选一个 winner。

优先级：

1. 有 `source_url/canonical_url` 的优先。
2. wiseflow 有旧系统 legacy bonus，因为它可能包含更完整的抓取材料。
3. 官方源、可信源优先。
4. 有效正文更长者优先。
5. 发布时间更新者优先。

结果：

- winner：`active = true`，`duplicate_of = null`。
- loser：`active = false`，`duplicate_of = winner.id`。
- 所有原始 `raw_items` 都保留，不物理删除。

## 8. 软聚类不是第一阶段硬去重

“同一主题、不同 URL”的新闻，比如官方稿和媒体转述，第一阶段不自动合并删除。

原因：

- 不同 URL 可能有不同事实来源和角度。
- 自动合并容易误杀。
- 管理员周报采信时需要看到来源差异。

第二阶段可以做软聚类：

- 标题相似度。
- 摘要/正文 embedding 相似度。
- 同公司/产品/模型名。
- 同一日期窗口。

软聚类只用于编辑提示、专题聚合、周报候选，不替代第一阶段硬去重。

## 9. 推荐与日报

去重完成后才进入推荐评分。

推荐评分输出：

- `quality_score`
- `topic_score`
- `freshness_score`
- `feedback_score`
- `diversity_score`
- `source_score`
- `heat_score`
- `final_score`
- `recommendation_reason`

日报草稿只从 active winner 中选。进入日报并被采信后，写入 `daily_report_items`。

标准内网 SQL 导出只从已发布日报的 `daily_report_items.adoption_status = 2` 读取。
