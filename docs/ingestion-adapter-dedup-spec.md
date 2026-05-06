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
- 一级标签：`config/taxonomy/news_categories.json`
- 登录设计：`docs/auth-unified-login.md`
- 旧系统规格：`docs/legacy-system-spec.md`

当前仓库已经有可运行的 `backend/`、`frontend/`、数据库迁移和测试；采集侧已完成 adapter 框架、单源 RSS/paper RSS/page_manual/page_monitor 抓取、工作台级 ingestion run API，以及 Redis/RQ worker + scheduler 调度入口。标准化与去重侧已完成 `POST /api/news-items/normalize`、`GET /api/news-items`、`GET /api/dedupe-groups` 的阶段 4 闭环；推荐与日报侧已完成 `POST /api/pipeline/daily-runs`、`POST /api/recommendation/runs`、日报草稿、发布、条目编辑和点赞/评分/评论的阶段 5 可回填闭环。

## 2. Adapter 的职责

每类数据源都有自己的输入结构，因此必须通过 Adapter 接入。

Adapter 负责：

- 读取 `data_sources.fetch_config`。
- 抓取或接收源数据。
- 生成稳定的 `entry_key`。
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

生成 `generated_news.category` 时必须读取当前工作台的 `workspaces.config_json.label_policy.allowed_primary_categories`；生成二级标签时读取 `secondary_labels_by_primary` 中当前一级标签下的候选项。第一阶段规划部默认使用 `config/taxonomy/news_categories.json` 的 10 个旧系统兼容一级标签；AI 工具桌面默认使用独立工具标签体系。单个数据源不配置标签；同一个信息源可能覆盖多个关注方向，最终标签由新闻内容和工作台统一策略共同决定。

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
- scheduler 可按环境变量定时把每日完整流水线入队，worker 从 Redis/RQ 执行。
- 默认处理当前工作台已启用、且源本身启用的 `rss/paper_rss`。
- `ingestion_runs` 保存 run 参数、状态、处理源数量、成功/失败、拉取数、raw 新增数和 raw 更新数。
- `summary_json.sources` 保存每个源的结果摘要。

尚未实现：失败源重试队列。已实现 scheduler 默认触发 `ingestion -> normalize/dedupe -> recommendation -> daily_report_draft`；如需只抓取，可设置 `SCHEDULER_JOB_MODE=ingestion_only`。

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

## 7. 去重逻辑

第一阶段采用硬去重，沿用旧系统已经验证过的保守逻辑。

### 7.1 canonical URL 去重

如果有 URL，优先使用：

```text
dedupe_key = "url:" + canonical_url
```

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
