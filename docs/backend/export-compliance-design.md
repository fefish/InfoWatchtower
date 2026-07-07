# Export Compliance 导出与合规校验设计

> 状态：目标态设计稿。本文是公司 SQL 导出、导出预检、导出任务、字段合规、追溯和失败报告
> 的后端模块事实源。字段映射细节见 `docs/backend/data-format-mapping.md` 和
> `config/contracts/news_sql_mapping.json`。

## 1. 模块定位

Export Compliance 负责把已发布、已采信、已生成完成的报告条目安全导出到公司内网兼容格式。

它回答：

- 哪些条目允许导出。
- 导出前要检查哪些字段。
- 导出失败如何定位和修复。
- SQL 文件和系统对象如何互相追溯。
- 导出是否会改变报告事实。

它不负责：

- 日报采信。
- 生成稿质量本身。
- 公司内网导入程序。
- 多版 Markdown/HTML 成稿。

## 2. 导出硬门槛

标准公司 SQL 只导出：

```text
daily_reports.status = published
daily_report_items.adoption_status = adopted / 2
generated_news.generation_status = ready
generated_news.generated_by != rule_v1
generated_news.category in AI 十分类
generated_news.content_json contains 五段字段
```

必须拒绝：

- 未发布日报。
- 未采信条目。
- fallback/rule_v1 草稿。
- category 不在十分类。
- content_json 缺五段字段。
- HTML 污染未清洗。
- `source_url` 缺失或超长且无处理策略。
- `created_at` 为空或无法按北京时间字面量渲染。

## 3. 领域对象

```text
export_jobs
  id
  export_type          company_sql_daily / company_sql_batch / rendition_md / rendition_html
  report_type
  report_id
  status               pending / running / succeeded / failed
  preflight_status     passed / failed / skipped
  contract_version
  created_by
  created_at
  finished_at
  output_path
  summary_json

export_job_items
  id
  export_job_id
  daily_report_item_id
  generated_news_id
  news_item_id
  raw_item_id
  data_source_id
  status               exported / skipped / failed
  sql_block_hash
  preflight_errors_json
  created_at
```

## 4. 预检模型

导出前生成 preflight report：

```text
eligible_count
blocked_count
warnings_count
errors[]
warnings[]
items[]
```

预检项：

| 检查 | 级别 |
|---|---|
| 日报状态 published | error |
| adoption_status adopted | skip non-adopted |
| generated_news ready | error per item |
| generated_by != rule_v1 | error per item |
| category 十分类 | error |
| content_json 五段完整 | error |
| key_points 非空且长度可接受 | warning/error |
| title/summary/content 长度 | warning/error |
| source_url 非空、长度、唯一性 | error |
| source_title/content HTML 清洗后非空 | warning/error |
| created_at 北京时间字面量 | error |
| SQL header 标准 | error |

预检失败不得生成“看似成功”的 SQL。

当前实现状态：

- `POST /api/exports/company-sql/daily-reports/{daily_report_id}/preflight` 已实现为只读检查，
  不创建 `export_jobs` 或 `export_job_items`。
- preflight 返回 `passed/failed`、`eligible/blocked/skipped`、report-level errors/warnings、
  item-level errors/warnings 和计数摘要。
- direct export 会复用同一套 preflight；失败时返回 409，不写 SQL。
- HTML 原文进入 `ai_journal.source_title/content` 前会清洗为纯文本；preflight 对该清洗给 warning。
  `content_json` 内部出现 HTML 标签会阻断，因为 validator 会拒绝。
- 大文件下载策略 v1 已完成：导出响应会返回 `sql_text_bytes`、`sql_text_preview_bytes`、
  `sql_text_truncated`、`download_url` 和 `download_filename`；超过 inline 预览上限时，API 只返回截断预览。
  完整 SQL 统一通过 `GET /api/exports/{id}/download` 流式下载，响应带 `Content-Length`、
  `X-InfoWatchtower-SQL-Bytes` 和 `X-InfoWatchtower-Download-Strategy=server_streaming`。
- 批量导出治理 v1 已完成：`POST /api/exports/company-sql/daily-reports/batch` 会在同一 workspace
  内按日报逐个运行 preflight，成功日创建独立 `company_sql` export job，失败日只进入 batch manifest。
  batch 自身写 `export_type=company_sql_batch`，`result_json.manifest` 保存 requested report、逐日结果、
  成功/失败/跳过计数、SQL 总大小、语句总数和 validation summary。

## 5. 导出流程

```text
request export
-> load published report
-> collect adopted items
-> run preflight
-> if failed: return preflight failed / export 409，不写 export_job
-> render SQL statements
-> run validate_company_sql.py compatible checks
-> persist output path and export_job_items
-> expose bounded preview, streaming download and trace
```

导出不修改：

- daily_report_items
- generated_news
- news_items
- raw_items

## 6. SQL 输出约束

必须保持：

- SQL 文件头：`InfoWatchtower Company SQL Preview`
- 4 表顺序：
  1. `ai_journal`
  2. `ai_journal_focus`
  3. `ai_journal_analysis`
  4. `t_news_data_info`
- `created_at` 字面量：`'YYYY-MM-DD HH:MM:SS'`
- 北京时间 `Asia/Shanghai` 渲染。
- `content_json` 只含：
  - `background`
  - `effects`
  - `eventSummary`
  - `technologyAndInnovation`
  - `valueAndImpact`
- `ai_journal.source_title/content` 必须纯文本。

## 7. 追溯

trace API：

```text
GET /api/exports/{export_job_id}/trace
```

必须能从任意 SQL block 回查：

```text
export_job_item
-> daily_report_item
-> generated_news
-> recommendation_item
-> news_item
-> raw_item
-> data_source
```

trace 只用于审计和排错，不改变公司 SQL 字段。

当前 trace 详情 v1 已返回每条 SQL 的 `sql_excerpt`、`export_title`、来源 URL、来源标题、
daily/generated/news/raw/source ID，以及 `title_source`、`summary_source`、`key_points_source`、
`content_field_sources` 和 `editor_override_fields`。trace 字段差异 v1 进一步返回 `field_diffs`：
按 `source_url/source_title/raw_content/title/summary/key_points/category` 和五个公司 `content_json`
字段展示导出值、生成稿值、日报编辑覆盖值、raw/news 来源值的预览，并标记是否由编辑覆盖、
是否截断。所有字段值都是 320 字符以内的预览；trace 不返回 `raw_payload_json`，也不把私密抓取配置
下发到前端。

导入回执 v1 已补齐：`export_import_receipts` 作为 `export_jobs` 的本地验收附件，记录
`target_system/import_status/imported_at/imported_statement_count/failed_statement_count/failure_items_json/notes`
和 `recorded_by_id`。失败项会尽量按 `sql_sequence + sql_table` 或 `export_job_item_id`
映射回 `export_job_items`，保留 `sql_excerpt`、内网错误码和错误原因。回执只用于导出后验收和审计，
不修改 SQL 文本、不改变公司 SQL 字段契约，且 `sync_policy=local_only`，不进入 extranet feed。
内网 importer 自动回调 v1 已补齐：`POST /api/exports/{id}/import-receipts/callback` 使用
`Authorization: Bearer <token>`，token 来自 `SYNC_SERVICE_TOKENS`，不走用户 cookie；
该机器接口精确豁免 CSRF，人工登记入口仍保持浏览器 CSRF/RBAC 保护。

## 8. API 目标态

```text
POST /api/exports/company-sql/daily-reports/{daily_report_id}/preflight
POST /api/exports/company-sql/daily-reports/{daily_report_id}
POST /api/exports/company-sql/daily-reports/batch
GET  /api/exports
GET  /api/exports/{id}
GET  /api/exports/{id}/download
GET  /api/exports/{id}/trace
GET  /api/exports/{id}/import-receipts
POST /api/exports/{id}/import-receipts
POST /api/exports/{id}/import-receipts/callback
```

## 9. 权限和部署

| 操作 | 权限 |
|---|---|
| 查看导出历史 | workspace viewer/member 按策略；全局列表 super_admin |
| 运行 preflight | member/admin |
| 生成 SQL | member/admin 或 export permission |
| 下载 SQL | workspace admin/super_admin，按部署策略 |
| trace | workspace viewer/member/admin/super_admin |
| 查看导入回执 | workspace viewer/member/admin/super_admin |
| 登记导入回执 | workspace admin/super_admin |
| importer 回调导入回执 | `SYNC_SERVICE_TOKENS` Bearer service token |

部署边界：

- intranet 可本地导出公司 SQL。
- extranet 默认不导出公司 SQL，除非明确开启。
- cloud 可按团队策略导出，但必须保护下载权限。
- 同步 feed 不下发导出文件。

## 10. 当前缺口

| 缺口 | 判定标准 |
|---|---|
| 生产实机 importer 联调证据 | 当前已支持人工/API 登记和 service token 回调；后续需要接入真实内网平台或 importer，并留导入成功、失败语句回写和权限失败的生产证据 |

## 11. 验收设计

- 未发布日报导出失败。
- 含 rule_v1/fallback 条目时 preflight failed。
- content_json 缺任一五段字段时失败。
- HTML 污染被清洗或阻断，并出现在 preflight。
- 生成 SQL 必须通过 `scripts/validate_company_sql.py`。
- trace 可回到 raw payload。
- batch export 必须产出 manifest、逐日结果、validation summary，并保持成功日报的独立下载和 trace。
- import receipt 可记录 imported/failed/partial/pending，失败项能回到 SQL sequence/table/export_job_item。
- importer callback 无 token 返回 401，合法 service token 可在 CSRF 开启时写入回执，且不需要用户 cookie。
- `GET /api/exports/{id}/download` 返回服务端保存的 SQL 文本附件。
- 下载端点必须走服务端流式响应，带文件大小 header；前端不得把截断预览当完整 SQL 下载。
- 普通 viewer 不能下载 SQL 文件，workspace admin/super_admin 可下载。
