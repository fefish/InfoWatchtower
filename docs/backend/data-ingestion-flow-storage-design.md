# Data Ingestion / Flow / Storage 数据抓取、流转与存储设计

> 状态：目标态设计稿。本文是数据源抓取、raw 存储、标准化、去重、候选池和追溯链路
> 的后端模块事实源。旧的 `docs/backend/ingestion-adapter-dedup-spec.md` 和
> `docs/backend/data-lineage-and-storage.md` 作为细节附录继续保留。

## 1. 模块定位

本模块负责把外部信号可靠地带进系统，并形成可追溯、可去重、可推荐的标准情报对象。

主链路：

```text
data_sources
-> workspace_source_links
-> ingestion_runs
-> SourceAdapter.fetch()
-> raw_items
-> news_items
-> dedupe_groups / dedupe_group_items
-> candidate pool
-> recommendation input
```

它不负责：

- 推荐评分权重和排序规则，见 `docs/backend/recommendation-scoring-design.md`。
- 日报/周报采信和成稿，见 `docs/backend/report-renditions-design.md`。
- 公司 SQL 导出，见 `docs/backend/data-format-mapping.md`。
- 前端页面布局，见 `docs/product/frontend-product-design.md`。

## 2. 领域对象与 owner

| 对象 | owner 模块 | 说明 |
|---|---|---|
| `data_sources` | Sources | 全局共享源池，一条源定义可被多个工作台启用 |
| `workspace_source_links` | Workspace + Sources | 工作台对共享源的启用、权重、日限、抓取配置 |
| `ingestion_runs` | Ingestion | 一次抓取/补采运行的参数、状态和摘要 |
| `raw_items` | Storage | 原始事实层；同源同 entry_key 重抓按最新抓取幂等刷新 payload 快照（§6），编辑/流水线等下游环节永不回写 |
| `news_items` | Content Pipeline | 标准化情报对象，按工作台隔离 |
| `dedupe_groups` | Content Pipeline | 去重组，保留 winner/loser 和重复来源 |
| `dedupe_group_items` | Content Pipeline | 去重组成员和内部排序权重 |

## 3. Adapter 目标态

Adapter 只负责把源数据稳定写入 `raw_items`。

Adapter 必须做：

- 读取 `data_sources.fetch_config` 和工作台 link 配置。
- 抓取或接收源数据。
- 生成稳定 `entry_key`。
- 解析标题、URL、摘要、正文候选、发布时间。
- 保存完整原始对象到 `raw_items.raw_payload_json`。
- 写入 `extract_status`、`extract_error` 和源特异字段。

Adapter 禁止做：

- 不直接写 `news_items`。
- 不做最终去重 winner 判断。
- 不做推荐分。
- 不决定采信、日报、周报或 SQL 导出。
- 不因为标准化失败删除 raw。

## 4. source_type 覆盖目标

| 类型 | 目标态 | 当前风险 |
|---|---|---|
| `rss` | RSS/Atom 标准抓取，浏览器 UA，单源上限 | RSS 窗口无法代表历史补采 |
| `paper_rss` | 论文 RSS + 论文元数据补充 | 元数据 enricher 仍需增强 |
| `page_manual` | 手工 URL 页面抓取 | 正文抽取质量需验收 |
| `page_monitor` | 列表页/详情页监控和增量差异 | 深度抽取和增量 diff 仍是轻实现 |
| `paper_api` | arXiv/OpenAlex/Semantic Scholar 等 API | arXiv submittedDate 日期回查 v1、OpenAlex works publication_date 日期回查 v1 和 Semantic Scholar publicationDateOrYear 日期回查 v1 已完成；OpenReview 等 provider 仍待补 |
| `wechat` / `wx://` | wx bridge sidecar 接入 | 依赖外部登录态和 wx 工具事实确认 |
| `manual` / `csv` | 人工导入和 CSV 导入 | 需要 schema、预览、校验和审计 |
| `internal` | 内网源接入 | 必须受 `visibility_scope` 和同步策略保护 |

`metadata_only/needs_entry` 源只能进入源治理，不进入抓取调度，直到补齐可抓取入口。

## 5. 抓取 run 语义

`ingestion_runs` 是调度层和审计层，不是业务内容层。

输入：

```text
workspace_code
source_types
limit
concurrency
source_timeout_seconds
max_items_per_source
mode = regular / historical_backfill
target day/window, if backfill
```

输出：

```text
status
attempted_source_count
succeeded_source_count
failed_source_count
skipped_unimplemented_count
fetched_count
raw_created_count
raw_updated_count
summary_json.sources[]
```

失败语义：

- 单源失败不阻塞整批 run。
- run 可为 `completed`、`partial`、`failed`、`no_sources`、`skipped_unimplemented`。
- `limit=0` 是非法请求，必须返回 422。
- 筛选不到启用源时返回 `no_sources`，不能显示“0 条成功”的假成功。
- 未实现的 stub adapter 返回 `skipped_unimplemented`，不计入成功或失败，run 汇总写
  `summary_json.source_skipped_unimplemented`。
- 每源错误要落到 run 摘要和 source 最近错误字段。

## 6. raw_items 存储边界

`raw_items` 是不可破坏事实层。

必须保留：

```text
data_source_id
workspace_code, if applicable
domain_code
visibility_scope
sync_policy
source_type
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
global_id / revision / content_hash
```

约束：

```text
unique(data_source_id, entry_key)
```

更新原则：

- 再次抓取同一 `entry_key` 可更新可变字段和 payload 快照。
- 不因后续编辑、去重、推荐、采信而修改 raw 事实。
- `raw_payload_json` 不得为前端展示而裁剪。
- secret/token/cookie/.env-like 字段不得进入可同步 payload。

## 7. 标准化 news_items

标准化负责把多源 raw 映射为统一候选对象。

输入：

```text
raw_items selected by workspace_source_links
workspace label policy
normalization rules
```

输出：

```text
news_items
  raw_item_id
  workspace_code
  domain_code
  visibility_scope
  sync_policy
  source_url / canonical_url
  source_title
  title / content / summary
  published_at
  dedupe_key
  normalization_status
```

规则：

- 同一共享 raw 可被不同工作台各自标准化。
- URL canonicalize、标题规范化、时间归属必须可测试。
- 来源缺少发布时间时要显式记录，不得编造。
- 不能满足最低标准的 raw 留在 raw 层，不进入推荐。

## 8. 去重与候选池

去重发生在标准化之后、推荐之前。

```text
news_items
-> dedupe_key
-> dedupe_groups(workspace_code + dedupe_key)
-> winner / loser
-> candidate pool view
```

原则：

- `raw_items` 永不因去重删除。
- `news_items` 可标记 active/duplicate，但不丢追溯。
- `dedupe_groups` 按工作台隔离。
- `rank_score` 是内部去重权重，不是推荐分。
- 候选池是去重 winner 的工作视图，不是新表族。
- `GET /api/dedupe-groups` 是候选池服务端视图，必须返回 winner 发布时间、来源类型、
  同组来源、最近推荐 trace 和最近日报 trace；v1 已支持关键词、推荐状态、日报状态、
  准入等级、来源类型筛选，以及更新时间、推荐分、发布时间、来源数排序。
- 候选池完整 trace 复核 v1 已完成：`GET /api/dedupe-groups` 返回 `lineage.nodes`，按
  `data_source -> raw_item -> news_item -> dedupe_group -> recommendation_item -> generated_news -> daily_report_item`
  串起安全追溯链。raw 层只暴露 entry key、source URL、时间、payload keys 和 content length，
  不返回完整 `raw_payload_json`、credential 或 fetch config；每个节点返回 `review_note`，
  由后端说明该节点在采编复核中证明什么，避免前端把 trace 做成纯 ID 调试链。
- 候选池筛选只改变工作视图，不修改 raw、news 或 dedupe 事实。

## 9. 覆盖率与可解释漏斗

后端必须能解释“为什么源很多但候选少”。

目标漏斗：

```text
enabled sources
-> attempted sources
-> succeeded sources
-> fetched entries
-> target-day raw
-> normalized news
-> active dedupe winners
-> recommendation candidates
-> selected recommendation items
-> generated ready
-> adopted report items
```

`GET /api/ingestion/coverage` 应至少返回：

```text
workspace_code
day_key
run_id
enabled_source_count
attempted_source_count
succeeded_source_count
failed_source_count
raw_created_count
raw_updated_count
target_day_raw_count
news_count
active_winner_count
recommendation_candidate_count
recommendation_selected_count
generated_ready_count
daily_adopted_count
per_source_breakdown[]
top_failure_reasons[]
```

前端不能把 `0 created` 渲染成绿色成功；必须区分 `updated`、`no_sources`、窗口无内容、
目标日无内容、adapter 失败和后续标准化失败。

论文 API provider v1：

- `provider=arxiv` 或 `export.arxiv.org` URL 走 arXiv Atom API，补采时追加
  `submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]` 查询，raw payload 保留 arXiv id、作者、
  分类、DOI、PDF URL 和原始链接。
- `provider=openalex` 或 `api.openalex.org/works` URL 走 OpenAlex Works API，补采时在
  `filter` 中追加 `from_publication_date:YYYY-MM-DD,to_publication_date:YYYY-MM-DD`，
  raw payload 保留完整 work 对象、OpenAlex id、DOI、作者、topic、期刊/来源和开放获取位置。
- `provider=semantic_scholar` 或 `api.semanticscholar.org/graph/v1/paper/search/bulk` URL
  走 Semantic Scholar Academic Graph bulk search，补采时追加
  `publicationDateOrYear=YYYY-MM-DD:YYYY-MM-DD`，raw payload 保留完整 paper 对象、paperId、
  externalIds、authors、venue、openAccessPdf 和原始 abstract。公开限额较低；生产可通过
  `SEMANTIC_SCHOLAR_API_KEY` 环境变量提供 `x-api-key`，该 key 不得写入 source 配置或同步包。
- provider 只能影响抓取入口和 raw 映射，不能绕过去重、推荐、日报采信和 SQL 导出主链路。
- OpenReview、Hugging Face Papers 仍是后续 provider；未完成 provider 不得渲染成
  “成功 0 条”。

长期覆盖趋势 v1：

- API：`GET /api/ingestion/coverage/trends?workspace_code=...&days=14`。
- 权限：当前工作台 viewer 可读；不需要本地采集能力，因此 intranet 只读部署也可查看。
- 数据来源：只读聚合 `ingestion_runs` 和 `summary_json.sources[]`，不引入旁路统计表。
- 时间口径：按 `completed_at`、`started_at` 或 `created_at` 归入北京时间日期桶。
- 返回最近 N 天每日 run 数、最新 run、尝试/成功/失败/未实现源、fetched、raw created/updated、
  成功率，以及 Top 失败源、最后错误和最后失败 run。
- 前端 `/ingestion-runs` 必须把趋势作为诊断面板展示，不能把 `0 raw_created` 或失败源隐藏成正常。

手动失败源重试 v1：

- API：`POST /api/ingestion/runs/{run_id}/retry-failed-sources`。
- 只读取原 run 的 `summary_json.sources[]` 中 `status = failed` 的源。
- 只重试仍属于该工作台且仍启用的失败源；没有失败源或失败源已不可用时返回 409，不创建 0 源成功 run。
- 普通 `workspace_fetch` 重试会保留原 `max_items_per_source`，默认按低并发长超时执行（`concurrency=2`、`source_timeout_seconds=60`）。
- `historical_backfill` 重试会保留 `target_day_start/target_day_end/backfill_mode/include_undated`，并把 `source_scope` 记录为 `failed_sources`、`retry_policy` 记录为 `retry_failed_sources`。
- 新 run 必须在 `params_json.retry_of_run_id` 和 `params_json.source_ids` 中记录来源 run 和重试源，供覆盖率排障追溯。
- `manual_import` 无法仅靠 run summary 还原原始手工 payload，必须重新上传手工补采数据；当前
  API/前端 CSV 粘贴入口会把原始行保存在 `raw_payload_json.payload`，但不把完整手工文件内容写入
  run summary。

失败源自动重试队列 v1：

- 策略配置：`INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED`、`INGESTION_FAILED_SOURCE_RETRY_BASE_SECONDS`、
  `INGESTION_FAILED_SOURCE_RETRY_MAX_SECONDS`、`INGESTION_FAILED_SOURCE_RETRY_MAX_ATTEMPTS`、
  `INGESTION_FAILED_SOURCE_RETRY_LIMIT`。
- 状态 API：`GET /api/ingestion/failed-source-retry-summary?workspace_code=...`。
- 调度入口：scheduler 在 `capability_ingestion=true` 且自动重试开启时投递
  `run_failed_source_auto_retry_job`。
- 选择规则：只选择原始失败 run（`params_json.retry_of_run_id` 为空）、非 `manual_import`、
  仍有启用失败源、未超过尝试次数且指数退避到期的 run；如果最新 retry run 已无失败源，
  原失败 run 视为已解决。
- 执行规则：复用同一套 `run_workspace_ingestion` / `run_historical_backfill` 服务，限定
  `source_ids` 为失败源，默认低并发和长超时，并继续写 `retry_of_run_id/source_ids` 追溯。
- 前端 `/ingestion-runs` 在自动调度卡展示启用状态、到期数、阻塞数、尝试上限和最近待重试 run。

失败源告警投递 v1：

- 事件归属：通知事件、收件人偏好和跳转解析属于
  `docs/backend/collaboration-notification-design.md` 与 `config/contracts/notifications.json`。
- 触发点：自动重试 job 发现到期或阻塞的失败源 run 时写
  `ingestion.failed_source_retry_due/ingestion.failed_source_retry_blocked` activity event。
- 收件人：active `super_admin` 以及该工作台 owner/admin；通知为 `important` 站内消息。
- 跳转：后端 target resolver 返回 `/ingestion-runs?run_id=...`，前端抓取页选中对应 run。
- 安全：告警只携带 run id、run key、run type、失败源数量、尝试次数、下一次重试时间和最近 retry run，
  不携带 credential、fetch config、cookie、token 或完整 raw payload。
- 幂等：同一 base run、同一事件类型、同一 `attempt_count` 只发一次。

### 9.1 单源详情诊断投影

数据源详情页不是 raw 全量浏览器，也不是密钥/抓取配置管理页。它只提供单源排障所需的安全投影：

```text
GET /api/sources/{source_id}?workspace_code={workspace_code}
```

权限：

- 带 `workspace_code` 时要求当前用户至少是该工作台 viewer。
- 不带 `workspace_code` 时仅 `super_admin` 可读全局源详情。

返回：

- `source`：`DataSourceRead` 安全投影。
- `raw_count` / `news_count`：当前工作台范围内的 raw/news 累计。
- `recent_raw_items[]`：最近 raw 的标题、URL、短 excerpt、抓取时间和发布时间。
- `recent_runs[]`：最近 run 中该源的 fetched/created/updated/status/error 摘要。
- `error_logs[]`：从 `ingestion_runs.summary_json.sources` 派生的该源失败记录。
- `raw_trend[]`：近 14 天 raw 入库计数。

安全边界：

- 不返回 `credential_ref`、`fetch_config`、`paper_config`。
- 不返回 `raw_payload_json`，只给短 excerpt 供人工判断内容是否像目标源。
- `error_logs` 只能来自 run 摘要，后续需要统一走 secret-like 脱敏规则，不能把 header、cookie、token
  或 `.env` 类字段带到前端。
- 该接口只读，不修改 raw、news、推荐、日报或工作台源链接。

## 10. 历史补采目标态

普通 RSS 只能恢复当前 feed 窗口，不等于历史补采。

补采模式：

| 模式 | 目标 |
|---|---|
| `rss_window` | 从当前 feed 窗口中筛目标日期 |
| `paper_api` | 调可按日期回查的论文 API |
| `archive_page` | 厂商/机构归档页分页抓取 |
| `sitemap` | sitemap 深挖目标日期 URL |
| `manual_import` | CSV/SQL/JSON 手工导入，v1 支持后端预览、逐行校验、错误报告和 raw payload 追溯 |

补采只负责 raw 入库；后续仍走标准化、去重、推荐、日报链路。

`manual_import` 当前落地 v1：

- `/ingestion-runs` 在 `manual_import` 模式下支持选择一个已启用归属源，并上传或粘贴 CSV/SQL 文本。
- `POST /api/ingestion/manual-import-preview` 是提交前门禁：它只解析和校验，不写 `raw_items`、
  不创建 `ingestion_runs`。预览返回 `accepted_items`、逐行 `errors`、accepted/rejected 计数和
  `error_report_csv`。
- CSV 表头支持 `data_source_id/source_id`、`source_title/title`、`source_url/url`、
  `raw_content/content/summary`、`published_at` 和 `entry_key`；未提供 `data_source_id` 时使用页面选择的归属源。
- SQL v1 只支持带列名的 `INSERT ... VALUES ...` 文本，列名映射同 CSV；解析失败或不含可识别列时返回
  逐行错误，不猜测字段。
- 后端拒绝空输入、缺少源 ID、源 ID 不属于当前工作台已启用源、没有标题/URL/正文的空行，以及预览
  `accepted_count=0` 的提交路径，避免生成“成功 0 条”或无意义 raw。
- 入库时先写 `raw_items`，`raw_payload_json.backfill_mode = manual_import`，
  `raw_payload_json.payload` 保留原始手工行；后续仍需标准化、去重、推荐和日报采信。
- 预览错误报告由前端下载为 CSV；真实入库审计仍以 `ingestion_runs.params_json/summary_json`
  和 `raw_items.raw_payload_json.payload` 为准。

`paper_api` 当前落地 arXiv v1 + OpenAlex Works v1 + Semantic Scholar v1：

- 自建源允许 `source_type=paper_api`，URL 可使用 `https://export.arxiv.org/api/query?search_query=cat:cs.AI` 形式。
- adapter 在历史补采时接收 `target_day_start/target_day_end`，自动把 arXiv `search_query` 扩展为 `submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]`。
- raw payload 保留 arXiv id、authors、categories、primary category、PDF/alternate link、published/updated、doi/comment/journal_ref 和 summary。
- OpenAlex 源可使用 `https://api.openalex.org/works?search=...`，adapter 在历史补采时把目标窗口追加为 `from_publication_date/to_publication_date` filter，raw payload 保留完整 work 对象、OpenAlex id、DOI、authors、topics、来源和开放获取位置。
- Semantic Scholar 源可使用 `https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=...`，adapter 在历史补采时把目标窗口追加为 `publicationDateOrYear=YYYY-MM-DD:YYYY-MM-DD`，raw payload 保留完整 paper 对象、paperId、externalIds、authors、venue、openAccessPdf 和 abstract；生产高频使用时通过 `SEMANTIC_SCHOLAR_API_KEY` 提升限额。
- OpenReview、Hugging Face Papers 等仍是后续 provider，不能把当前 v1 宣传成全论文平台补采完成。

## 11. 与部署形态的关系

| 部署形态 | 抓取能力 |
|---|---|
| standalone | 开启，可本地配置 adapter |
| cloud | 开启，仅 workspace admin+ 触发 |
| extranet | 开启，作为对 intranet 下发的发布者 |
| intranet | 关闭，不跑外网 crawler，只从 extranet feed 拉取结果 |

API、scheduler、worker、前端入口必须同时受 `capability_ingestion` 控制。

## 12. 当前设计缺口

| 缺口 | 判定标准 |
|---|---|
| 核心主链文档过去过于分散 | 本文成为抓取/流转/存储事实源，旧文档降为细节附录 |
| `wechat/wx://` 真实适配缺失 | wx bridge sidecar 契约、adapter、失败语义和验收完成 |
| `paper_api` provider 覆盖不足 | arXiv 日期回查 v1、OpenAlex Works 日期回查 v1 和 Semantic Scholar 日期回查 v1 已完成；后续补 OpenReview 等 provider |
| 页面监控深度抽取不足 | archive/page_monitor 能分页、抽正文、记录差异 |
| 手工导入深化 | CSV/SQL 上传或粘贴、import-preview、逐行校验和错误报告下载已完成；后续补更复杂 SQL dialect 和大文件分片 |
| 覆盖率漏斗需持续强化 | raw/news/winner/recommendation/daily 全链路可解释 |
| 失败源生产告警深化 | 手动失败源重试 v1、自动重试队列 v1、长期覆盖趋势 v1、Top 失败源聚合和站内告警投递 v1 已完成；后续补邮件/外部告警通道和生产 runbook |

## 13. 验收设计

- `limit=0` 返回 422。
- 无启用源返回 `no_sources`，前端不显示成功。
- 单源失败不阻塞其他源，run 为 `partial` 并记录错误。
- 同一源同一 `entry_key` 重复抓取幂等更新。
- 任意日报条目可追溯到 `raw_items.raw_payload_json`。
- 同一 raw 在不同工作台可各自生成 news 和 dedupe group。
- `DEPLOY_MODE=intranet` 下抓取 API、scheduler 和前端入口全部关闭。
- 补采结果先进入 raw，再复用标准主链。
- 手动失败源重试只跑失败源；没有失败源时返回 409，前端不显示成功。
