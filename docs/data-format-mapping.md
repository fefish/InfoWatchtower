# 数据格式与 SQL 映射

这份文档回答三个问题：

1. 全量信息源在哪里。
2. 新代码仓自己的字段是什么。
3. 这些字段如何映射到公司内部 SQL。

机器可读契约在：

- `config/taxonomy/news_categories.json`
- `config/taxonomy/source_tags.json`
- `config/taxonomy/news_categories.json`
- `config/contracts/source_fields.json`
- `config/contracts/news_sql_mapping.json`
- `config/contracts/auth_modes.json`

## 1. 全量信息源

新项目自己的种子源放在：

- `config/seeds/legacy/rss_sources.json`
- `config/seeds/legacy/page_sources.json`
- `config/seeds/legacy/wiseflow_sources.json`
- `config/seeds/legacy/all_sources.index.json`
- `config/seeds/legacy/source_registry.md`
- `config/seeds/legacy/source_catalog/folo-rss-link-classification-unified-folo-cli-supplemented.csv`
- `config/seeds/legacy/source_catalog/information_source_registry_20260511.csv`

当前统计：

- Wiseflow 原始 API 源：1 个。
- RSS 源：108 个，其中 74 个启用、34 个停用。
- 页面源：4 个。
- 合并索引：113 个。
- 论文 RSS 源：17 个，其中 14 个启用。
- 补充信息源台账：351 行，其中 248 条标准 RSS 记录可导入。
- 当前合并导入：361 条记录，按 URL 去重后 294 个共享数据源；规划部工作台 v1 默认全部启用。

`all_sources.index.json` 是轻量索引，方便快速浏览；真正的原始完整字段仍以 `wiseflow_sources.json`、`rss_sources.json` 和 `page_sources.json` 为准。
补充台账用于新增数据源、源侧方向标签和源质量评分；CSV 状态/纳入建议保留为运营元数据和评分先验，不参与成品新闻一级标签定稿，也不能改变公司 SQL 的 category。

## 2. 一级标签

成品新闻一级标签沿用旧系统约定的 AI 十分类，落到：

- `config/taxonomy/news_categories.json`

当前默认新闻一级标签为：

- `AI Infra`
- `AI 应用`
- `测评技术`
- `大厂动态`
- `模型`
- `算法`
- `推理加速`
- `训练技术`
- `智能体`
- `基础竞争力`

`config/taxonomy/source_tags.json` 是数据源侧方向标签，用来描述源可能覆盖的方向、帮助源过滤和推荐先验。它不能写入 `generated_news.category`，也不能作为公司 SQL 的 `category`。

## 3. 三层数据格式

这里的“三层”按业务边界理解：

1. 信息源层：wiseflow/RSS/page/crawler/paper/API/manual/internal 的配置和抓取结果。
2. 代码仓业务层：`data_sources`、`raw_items`、`news_items`、`generated_news`、日报/周报条目。
3. 公司内部 SQL 层：`ai_journal`、`ai_journal_focus`、`ai_journal_analysis`、`t_news_data_info`。

中间的模型生成 JSON 是业务层中的 `generated_news`，不是另起一套数据真相。

## 4. 信息源字段

标准数据源字段见：

- `config/contracts/source_fields.json`

关键字段：

- `source_type`
- `domain_code`
- `name`
- `url`
- `enabled`
- `default_focus_id`
- `backfill_days`
- `fetch_interval_minutes`
- `trust_level`
- `daily_source_limit`
- `visibility_scope`
- `sync_policy`
- `credential_ref`
- `primary_category`
- `secondary_category`
- `info_category`
- `topic_flags`
- `fetch_config`
- `paper_config`
- `metadata`

旧 RSS 源映射：

| 旧字段 | 新字段 |
| --- | --- |
| `name` | `data_sources.name` |
| `feed_url` | `data_sources.url` |
| `enabled` | `data_sources.enabled` |
| `default_focus_id` | `data_sources.default_focus_id` |
| `backfill_days` | `data_sources.backfill_days` |
| `folo_metadata.primary_category` | `data_sources.primary_category` |
| `folo_metadata.secondary_category` | `data_sources.secondary_category` |
| `folo_metadata.info_category` | `data_sources.info_category` |
| `folo_metadata.*相关` | `data_sources.topic_flags` |
| `origin + folo_metadata` | `data_sources.metadata` |

旧 wiseflow 源映射：

| 旧配置 | 新字段 |
| --- | --- |
| `SOURCE_API_BASE` | `data_sources.fetch_config.base_url_env` |
| `SOURCE_READ_INFO_URL` | `data_sources.fetch_config.read_info_url_env` |
| `READ_INFO_PAGE_SIZE` | `data_sources.fetch_config.page_size_env` |
| `POST /read_info` | `data_sources.fetch_config.required_full_sync_endpoint` |
| `/list_info` 限制 | `data_sources.metadata.do_not_use_for_full_sync` |

wiseflow 是旧系统的原始聚合源，不是 RSS/page 的替代品。新系统导入源时要把它作为 `source_type=wiseflow` 的 adapter 单独建模。

旧页面源映射：

| 旧字段 | 新字段 |
| --- | --- |
| `name` | `data_sources.name` |
| `type=listing` | `source_type=page_monitor` |
| `type=manual` | `source_type=page_manual` |
| `page_url` | `data_sources.url` |
| `articles[].url` | manual 子源或 `fetch_config.articles` |
| `href_contains/exclude_exact/max_links` | `fetch_config` |

论文源映射：

- `folo_metadata.info_category = 学术论文` 的 RSS 源导入为 `paper_rss`。
- arXiv、Nature、Science、PNAS 等源保留原始 RSS 配置，同时在 `paper_config` 中预留论文标识、作者、机构、DOI、PDF、代码链接、引用数等字段。

## 5. 新闻字段

内部业务层建议使用这些主对象：

- `raw_items`：忠实保存抓取结果。
- `news_items`：标准化新闻，参与去重和推荐。
- `generated_news`：模型生成后的结构化稿件。
- `daily_report_items` / `weekly_report_items`：日报/周报采信、排序和编辑态。

核心流转：

| 层 | 字段 | 含义 |
| --- | --- | --- |
| `raw_items` | `source_url` | 原始 URL |
| `raw_items` | `source_title` | 原始标题 |
| `raw_items` | `raw_content` | 原始摘要/正文 |
| `raw_items` | `published_at` | 原始发布时间 |
| `news_items` | `domain_code` | 所属产业情报板块 |
| `news_items` | `visibility_scope` | 公网/内网可见边界 |
| `news_items` | `sync_policy` | 多环境同步策略 |
| `news_items` | `dedupe_key` | 去重键 |
| `news_items` | `active` | 去重 winner |
| `news_items` | `normalization_status` | 标准化状态 |
| `generated_news` | `category` | AI 十分类新闻一级标签 |
| `generated_news` | `title` | 生成标题 |
| `generated_news` | `summary` | 生成摘要 |
| `generated_news` | `key_points` | 关键词 |
| `generated_news` | `content_json` | 结构化正文 |

模型生成 JSON 必须包含：

```json
{
  "category": "智能体",
  "content": {
    "background": "...",
    "effects": "...",
    "eventSummary": "...",
    "technologyAndInnovation": "...",
    "valueAndImpact": "..."
  },
  "keyPoints": "关键词1, 关键词2, 关键词3, 关键词4",
  "sourceUrl": "https://example.com/news",
  "summary": "2-3句话核心洞察",
  "title": "最终展示标题"
}
```

## 6. 公司内部 SQL 映射

完整机器映射见：

- `config/contracts/news_sql_mapping.json`

标准日报导出只导出“已经进入已发布日报、且 `daily_report_items.adoption_status = 2`”的新闻。候选池里没进入日报的新闻、保留但未推荐的新闻，不默认导出到公司内部 SQL。

每条导出的日报新闻固定导出 4 条 SQL，顺序为：

1. `ai_journal`
2. `ai_journal_focus`
3. `ai_journal_analysis`
4. `t_news_data_info`

字段映射：

| 内部字段 | 公司 SQL 字段 |
| --- | --- |
| `raw_items.source_url` | `ai_journal.source_url`、`ai_journal_analysis.source_url`、`t_news_data_info.source_url` |
| `raw_items.source_title` | 清洗为纯文本后写入 `ai_journal.source_title` |
| `raw_items.raw_content` | 清洗为纯文本后写入 `ai_journal.content` |
| `raw_items.published_at` | `ai_journal.created_at`、`ai_journal_analysis.created_at` |
| `news_items.focus_id` | `ai_journal_focus.focus_id` |
| `daily_report_items.adoption_status` | `t_news_data_info.adoption_status` |
| `generated_news.category` | `ai_journal_analysis.category`、`t_news_data_info.category`，必须是 AI 十分类新闻一级标签 |
| `daily_report_items.editor_title` 或 `generated_news.title` | `ai_journal_analysis.title`、`t_news_data_info.title` |
| `daily_report_items.editor_summary` 或 `generated_news.summary` | `ai_journal_analysis.summary`、`t_news_data_info.summary` |
| `daily_report_items.editor_key_points` 或 `generated_news.key_points` | `ai_journal_analysis.key_points`、`t_news_data_info.key_points` |
| `daily_report_items.editor_content_json` 合并 `generated_news.content_json` | `ai_journal_analysis.content_json`、`t_news_data_info.content_json` |

`created_at` 是内网导入的硬契约：`ai_journal.created_at` 和
`ai_journal_analysis.created_at` 都必须和旧系统 `generate_ai_sql.py` 以及已验证 SQL
合集保持一致，使用显式 `created_at` 列和 `'YYYY-MM-DD HH:MM:SS'` 日期字面量。优先使用
原始发布时间；如果来源缺失发布时间，标准日报 SQL 兜底为 `daily_reports.day_key 09:00:00`，
避免内网导入后出现空时间。不要改成 `STR_TO_DATE(...)`、`CAST(...)`，也不要省略
`ai_journal_analysis.created_at`。如果内网 Flask 模型在 `ai_journal_analysis.to_dict()` 中对
`created_at.strftime(...)` 报错，优先排查内网表字段类型、ORM 类型和导入后实际行值，
不应擅自改变 InfoWatchtower 的 SQL 契约。

`content_json` 导出时只保留旧系统可识别的五个正文键：

```text
background / effects / eventSummary / technologyAndInnovation / valueAndImpact
```

`generated_news.content_json.source`、`news_item_id`、`raw_item_id`、`data_source_id`、`recommendationReason` 等新系统追溯或推荐字段不写入公司 SQL 的 `content_json`。这些追溯关系保留在 InfoWatchtower 自己的关系表中，通过 `export_job_items -> daily_report_items -> generated_news -> news_items -> raw_items` 查询。

标准公司 SQL 还要求采信项指向 `generated_news.generation_status = ready` 且 `generated_by` 不是 `rule_v1`。MiniMax 未启用或调用失败时生成的 `rule_v1:fallback` 只能作为页面复核草稿，不允许直接进入标准 SQL，避免英文浅摘要或低质量兜底内容污染内网。

`raw_items.raw_payload_json` 和 `raw_items.raw_content` 在 InfoWatchtower 内部保留原始抓取内容；导出到公司 SQL 的 `ai_journal.source_title` 和 `ai_journal.content` 必须先做 HTML 标签清洗，保持与旧 `generate_ai_sql.py` 输出的纯文本 SQL 形态一致。

导出必须使用旧系统验证过的安全写法：

- `ai_journal` 使用 `INSERT IGNORE`。
- 后续三张表使用 `INSERT ... SELECT id FROM ai_journal WHERE source_url = :source_url LIMIT 1`。
- SQL 文件头统一使用 `InfoWatchtower Company SQL Preview`，本地预览文件可用
  `python3 scripts/validate_company_sql.py --fix-headers` 统一标题。
- 所有公司 SQL 预览在导入内网前必须运行 `python3 scripts/validate_company_sql.py`。脚本以
  `outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql` 为基准，逐字段校验
  4 表顺序、列名、必填字段、`source_url` 串联、`created_at` 同步、AI 十分类 category、
  `content_json` 五段正文、`adoption_status = 2`、无 HTML 标签、无 `NULL created_at`、
  无 `STR_TO_DATE/CAST`、无省略 `ai_journal_analysis.created_at`。

这样可以避免单条新闻插入失败时拖垮整份 SQL。

当前实现入口：

- 后端服务：`backend/app/exports/company_sql.py`
- API：`POST /api/exports/company-sql/daily-reports/{daily_report_id}`
- 导出任务：`export_jobs` 保存整体结果，`export_job_items` 保存每条 SQL 及其日报条目、生成稿、新闻、原始数据链路。
